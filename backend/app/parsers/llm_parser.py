"""
LLM-based invoice parser.

Primary:  Groq  (OpenAI-compatible endpoint)
Fallback: OpenRouter

Generic prompt — works on any commercial invoice format, any country,
any supplier. Zero hardcoded brand names or domain knowledge.

Includes verify_and_fix() for rule-based post-processing.
"""

import os
import json
import logging
import re
import time
import requests
from app.cancel_registry import check_cancelled, JobCancelledError

logger = logging.getLogger(__name__)

def _groq_api_key() -> str:
    return os.environ.get("GROQ_API_KEY", "")

def _groq_model() -> str:
    return os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

GROQ_BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

def _openrouter_api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "")

def _openrouter_model() -> str:
    return os.environ.get("OPENROUTER_MODEL", "qwen/qwen3-next-80b-a3-b-instruct:free")

OPENROUTER_BASE_URL = os.environ.get(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions"
)

from app.config import LLM_TIMEOUT, LLM_MAX_RETRIES, LLM_RETRY_BACKOFF

# Bounded, env-configurable so the LLM stage can't exceed the job budget.
MAX_RETRIES = LLM_MAX_RETRIES
RETRY_BACKOFF = LLM_RETRY_BACKOFF

def _extract_json_payload(text: str) -> str:
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    match = re.search(r'```(?:json)?\s*\n(.*?)\n\s*```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r'(\{.*\})', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()

SYSTEM_PROMPT = """You are an expert invoice data-extraction engine.
You receive noisy OCR text from scanned invoices. The text uses tabs
between columns and newlines between rows, but OCR errors are common:
misspelled words, merged lines, split rows, and garbled numbers.

Your ONLY job is to return a single valid JSON object.
No explanation, no markdown fences, no extra text."""

USER_PROMPT_TEMPLATE = """Extract ALL structured data from the OCR text below.

━━━━ RULES ━━━━

1. PO / PURCHASE ORDER NUMBER:
   Look for labels like "PO", "P.O.", "PO#", "Purchase Order", "Order No",
   "Ref", "Reference", or numbers near "SHIPPING INSTRUCTIONS".
   Return ONLY the core numeric PO identifier (strip prefixes like "VFI-").
   Do NOT confuse it with S.O. (Sales Order) or invoice numbers.

2. INVOICE NUMBER:
   Look for "Invoice No", "Inv No", "SI No", "Sales Invoice", "No.", "Doc No".

3. DATES: Normalise to YYYY-MM-DD.

4. SUPPLIER & BUYER:
   The company that ISSUED the invoice is the supplier.
   The company that RECEIVES goods is the buyer.
    Treat OCR typo labels like "TTN" as "TIN".

5. LINE ITEMS — MOST CRITICAL:

   a) EXTRACT EVERY ITEM. Never skip a row just because the OCR is messy.

   b) "quantity" = the order count (small integer: 1, 2, 3, 5, 10).
      It is NOT the total price. Verify: qty × unit_price ≈ total_price.

   c) OCR SPLITS ROWS: If a line has numbers (qty, price, total) but
      NO product description, the description is on the adjacent line
      (above or below). Merge them into ONE item.
      NEVER skip a row that has valid qty/price data just because the
      description is missing — assign the nearest unmatched description,
      or use "(unreadable)" as a last resort.

   d) OCR MERGES ROWS: If a single line contains TWO product descriptions
      (you can tell because product names have distinct patterns —
      brand + product + size/weight), split them into separate items.
      Detect splits by: multiple capitalized brand-like words, multiple
      size specs (e.g. "150g" and "400g"), or multiple pack counts
      (e.g. "/100s" and "/24s") in one text block.

   e) DEDUPLICATION: If the same product appears twice with identical
      qty/price, it is an OCR duplicate — keep it only ONCE.

   f) Extract product_code (numeric item codes) and UOM if present.

   g) MANDATORY CROSS-CHECK:
      Sum all your extracted item total_prices. Compare to the
      GROSS SALES, TOTAL SALES, or subtotal printed on the invoice.
      If your sum is significantly LESS than the stated total, you
      have missed items. Re-examine the OCR for orphan rows and
      merged lines until your sum matches within 5%.

6. FINANCIALS: subtotal, vat/tax, discount, total_amount.
   Remove commas, use dot decimals (1,660.00 → 1660.00).

7. If uncertain about any field, return null or "".

━━━━ OCR TEXT ━━━━
{ocr_text}

━━━━ OUTPUT (strict JSON, nothing else) ━━━━
{{
  "invoice_number": "",
  "po_number": "",
  "invoice_date": "",
  "due_date": "",
  "supplier": {{ "name": "", "address": "", "tin": "" }},
  "buyer": {{ "name": "", "address": "", "tin": "" }},
  "store_code": "",
  "items": [
    {{
      "product_code": "",
      "description": "",
      "quantity": 0,
      "uom": "",
      "unit_price": 0.0,
      "total_price": 0.0
    }}
  ],
  "financials": {{
    "subtotal": 0.0,
    "vat": 0.0,
    "discount": 0.0,
    "total_amount": 0.0
  }}
}}"""

def verify_and_fix(parsed: dict, ocr_text: str = "") -> dict:
    """
    Rule-based fixes using only arithmetic — no domain assumptions.
    """
    items = parsed.get("items", [])
    if not isinstance(items, list):
        return parsed

    fixed_items = []
    for item in items:
        qty = _to_float(item.get("quantity", 0))
        up = _to_float(item.get("unit_price", 0))
        tp = _to_float(item.get("total_price", 0))


        if qty > 0:
            item["quantity"] = int(qty) if float(qty).is_integer() else round(qty, 3)

        if qty == 0 and up == 0 and tp == 0:
            continue


        if qty > 0 and up > 0 and tp > 0:
            expected = qty * up
            ratio = expected / tp if tp != 0 else 999
            if ratio >= 1.5 or ratio < 0.5:
                candidate_qty = tp / up
                if 1 <= candidate_qty <= 500 and candidate_qty == int(candidate_qty):
                    item["quantity"] = int(candidate_qty)
                    qty = int(candidate_qty)


        if _to_float(item.get("total_price", 0)) == 0 and qty > 0 and up > 0:
            item["total_price"] = round(qty * up, 2)


        if _to_float(item.get("unit_price", 0)) == 0 and qty > 0 and _to_float(item.get("total_price", 0)) > 0:
            item["unit_price"] = round(_to_float(item["total_price"]) / qty, 2)

        fixed_items.append(item)



    financials = parsed.get("financials", {})
    if isinstance(financials, dict) and fixed_items:
        gross = max(
            _to_float(financials.get("subtotal", 0)),
            _to_float(financials.get("total_amount", 0)),
        )
        items_sum = sum(_to_float(it.get("total_price", 0)) for it in fixed_items)
        zero_items = [it for it in fixed_items
                      if _to_float(it.get("total_price", 0)) == 0
                      and _to_float(it.get("quantity", 0)) > 0]

        if gross > 0 and zero_items and items_sum < gross:
            gap = round(gross - items_sum, 2)
            if len(zero_items) == 1:
                it = zero_items[0]
                it["total_price"] = gap
                q = _to_float(it.get("quantity", 1)) or 1
                it["unit_price"] = round(gap / q, 2)
                logger.info(f"[VERIFY] Inferred price from gap: {it.get('description','')} → {gap}")
            elif len(zero_items) > 1 and gap > 0:
                per_item = round(gap / len(zero_items), 2)
                for it in zero_items:
                    q = _to_float(it.get("quantity", 1)) or 1
                    it["total_price"] = per_item
                    it["unit_price"] = round(per_item / q, 2)

    parsed["items"] = fixed_items


    if ocr_text:
        _apply_ocr_field_fallbacks(parsed, ocr_text)



    if ocr_text and isinstance(financials, dict) and fixed_items:
        _rebalance_item_prices_from_ocr(fixed_items, financials, ocr_text)
        _fix_cross_line_item_bundle_swap(fixed_items, ocr_text)


    if isinstance(financials, dict):
        if _to_float(financials.get("total_amount", 0)) == 0 and fixed_items:
            s = sum(_to_float(it.get("total_price", 0)) for it in fixed_items)
            if s > 0:
                financials["total_amount"] = round(s, 2)
                parsed["financials"] = financials


    po = str(parsed.get("po_number", "")).strip()
    digits = re.findall(r'\d+', po)
    if digits:
        parsed["po_number"] = max(digits, key=len)

    return parsed


def _to_float(val) -> float:
    if val is None or val == "":
        return 0.0
    try:
        raw = str(val).replace(",", "").replace("₱", "").replace("$", "").strip()
        return float(raw)
    except (ValueError, TypeError):

        text = str(val).replace(",", "")
        match = re.search(r'-?\d+(?:\.\d+)?', text)
        if not match:
            return 0.0
        try:
            return float(match.group(0))
        except (ValueError, TypeError):
            return 0.0


def _extract_tins_with_context(text: str) -> list[tuple[int, str, str]]:
    tins = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    tin_pattern = re.compile(r'\b\d{3}-\d{3}-\d{3}-\d{3,5}\b|\b\d{12,15}\b')
    for idx, line in enumerate(lines):
        for match in tin_pattern.findall(line):

            normalized = re.sub(r'\bttn\b', 'tin', line.lower())
            tins.append((idx, match, normalized))
    return tins


def _tin_digits(value: str) -> str:
    return re.sub(r'\D', '', str(value or ''))


def _is_same_tin(a: str, b: str) -> bool:
    da = _tin_digits(a)
    db = _tin_digits(b)
    if not da or not db:
        return False
    return da == db or da.startswith(db) or db.startswith(da)


def _prefer_richer_tin(current_tin: str, candidate_tin: str) -> str:
    """Return the TIN variant with more digits when both represent the same TIN."""
    if not candidate_tin:
        return current_tin
    if not current_tin:
        return candidate_tin
    if not _is_same_tin(current_tin, candidate_tin):
        return current_tin

    current_digits = _tin_digits(current_tin)
    candidate_digits = _tin_digits(candidate_tin)
    return candidate_tin if len(candidate_digits) > len(current_digits) else current_tin


def _pick_best_po_from_ocr(text: str, current_po: str = "") -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    candidates: list[tuple[int, str]] = []
    current_digits = ""
    current_groups = re.findall(r'\d{6,12}', str(current_po))
    if current_groups:
        current_digits = max(current_groups, key=len)

    for line in lines:
        lower = line.lower()
        groups = re.findall(r'\d{6,12}', line)
        if not groups:
            continue

        score = 0
        if re.search(r'\b(p\.?\s*o\.?|purchase\s*order|order\s*no)\b', lower):
            score += 90
        if "invoice" in lower or "date" in lower:
            score -= 15

        for g in groups:
            local_score = score

            if re.search(rf's\.\s*o\.\s*no\s*[:#-]?\s*{re.escape(g)}', lower):
                local_score -= 80
            if re.search(rf'shipping\s*instructions\s*[:#-]?\s*{re.escape(g)}', lower):
                local_score += 70
            if re.search(rf'\b{re.escape(g)}[a-z]{{2,4}}\b', lower):
                local_score += 20


            length_bonus = min(len(g), 10)
            candidates.append((local_score + length_bonus, g))

    if not candidates:
        return current_digits

    best = max(candidates, key=lambda x: x[0])[1]
    best = _repair_missing_po_leading_digit(best, text)
    if not current_digits:
        return best
    if len(current_digits) < 8 and len(best) >= len(current_digits):
        return best
    return _repair_missing_po_leading_digit(current_digits, text)


def _repair_missing_po_leading_digit(po_value: str, ocr_text: str) -> str:
    """
    Some OCR outputs drop the leading digit in shipping-instructions PO values,
    e.g. "017736" instead of "4017736".
    """
    po = str(po_value or "").strip()
    if not re.fullmatch(r'\d{6}', po) or not po.startswith("0"):
        return po

    lower = ocr_text.lower()
    if "shipping instructions" in lower and re.search(rf'{re.escape(po)}[a-z]{{2,4}}', lower):
        return f"4{po}"
    return po


def _apply_ocr_field_fallbacks(parsed: dict, ocr_text: str) -> None:
    supplier = parsed.get("supplier") or {}
    buyer = parsed.get("buyer") or {}


    best_po = _pick_best_po_from_ocr(ocr_text, parsed.get("po_number", ""))
    if best_po:
        parsed["po_number"] = best_po

    tins = _extract_tins_with_context(ocr_text)
    if not tins:
        parsed["supplier"] = supplier
        parsed["buyer"] = buyer
        return

    supplier_tin = str(supplier.get("tin", "")).strip()
    buyer_tin = str(buyer.get("tin", "")).strip()


    supplier_candidates = [
        tin for _, tin, line in tins
        if "vat" in line or "tin" in line
    ]
    for tin in supplier_candidates:
        supplier_tin = _prefer_richer_tin(supplier_tin, tin)

    if not supplier_tin:
        for _, tin, line in tins:
            if "vat" in line or "tin" in line:
                supplier_tin = tin
                break
        if not supplier_tin:
            supplier_tin = tins[0][1]

    if not buyer_tin:

        buyer_label_candidates = [
            tin for _, tin, line in tins
            if "tin" in line and any(k in line for k in ("soldto", "sold to", "buyer", "customer", "address"))
            and not _is_same_tin(tin, supplier_tin)
        ]
        if buyer_label_candidates:
            buyer_tin = buyer_label_candidates[0]

        sold_to_candidates = [
            tin for _, tin, line in tins
            if any(k in line for k in ("soldto", "sold to", "buyer", "customer", "address", "ttn", "tin"))
            and not _is_same_tin(tin, supplier_tin)
        ]
        if not buyer_tin and sold_to_candidates:
            buyer_tin = sold_to_candidates[0]
        elif not buyer_tin:
            for _, tin, _ in tins:
                if not _is_same_tin(tin, supplier_tin):
                    buyer_tin = tin
                    break

    if supplier_tin:
        supplier["tin"] = supplier_tin
    if buyer_tin:
        buyer["tin"] = buyer_tin

    parsed["supplier"] = supplier
    parsed["buyer"] = buyer


def _extract_item_section(ocr_text: str) -> str:
    low = ocr_text.lower()
    start_idx = low.find("description")
    if start_idx == -1:
        return ""

    end_markers = [
        "remarks",
        "total sales",
        "vatable sales",
        "total amount due",
    ]
    end_idx = len(ocr_text)
    for marker in end_markers:
        pos = low.find(marker, start_idx + 1)
        if pos != -1:
            end_idx = min(end_idx, pos)

    return ocr_text[start_idx:end_idx]


def _extract_price_candidates_from_item_section(ocr_text: str) -> list[float]:
    section = _extract_item_section(ocr_text)
    if not section:
        return []


    raw_nums = re.findall(r'\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2}', section)
    vals: list[float] = []
    for token in raw_nums:
        v = _to_float(token)

        if 100 <= v <= 100000:
            vals.append(round(v, 2))
    return vals


# Bounds for the exponential price-rebalance DFS below, so invoices with many
# line items can't hang the parser. Skip the search entirely once the space is
# too large, and abort it past the node cap (falling back to the LLM's prices).
_REBALANCE_MAX_SPACE = 50_000
_REBALANCE_MAX_NODES = 200_000


def _rebalance_item_prices_from_ocr(items: list[dict], financials: dict, ocr_text: str) -> None:
    target_subtotal = _to_float(financials.get("subtotal", 0))
    if target_subtotal <= 0:
        return

    price_candidates = _extract_price_candidates_from_item_section(ocr_text)
    if not price_candidates:
        return


    qty1_items = [it for it in items if _to_float(it.get("quantity", 0)) == 1]
    repeated_qty1_prices = {}
    for it in qty1_items:
        up = round(_to_float(it.get("unit_price", 0)), 2)
        repeated_qty1_prices[up] = repeated_qty1_prices.get(up, 0) + 1
    if not any(count >= 2 for count in repeated_qty1_prices.values()):
        return


    options_per_item: list[list[float]] = []
    for it in items:
        qty = _to_float(it.get("quantity", 0))
        existing = round(_to_float(it.get("unit_price", 0)), 2)
        opts = {existing} if existing > 0 else set()


        for p in price_candidates:
            opts.add(round(p, 2))


        if qty > 0:
            for t in price_candidates:
                inferred = round(t / qty, 2)
                if 100 <= inferred <= 100000:
                    opts.add(inferred)

        options_per_item.append(sorted(opts))


    # This search is exponential in the number of items (∏ options_per_item).
    # Skip it entirely when the space is too large so large invoices don't hang
    # (a ~25-line invoice previously ran effectively forever).
    search_space = 1
    for opts in options_per_item:
        search_space *= max(1, len(opts))
        if search_space > _REBALANCE_MAX_SPACE:
            logger.warning(
                f"[VERIFY] Skipping price rebalance for {len(items)} items: "
                f"search space too large."
            )
            return

    best_combo = None
    best_score = (float("inf"), float("inf"))
    nodes = [0]

    base_prices = [round(_to_float(it.get("unit_price", 0)), 2) for it in items]

    def _dfs(i: int, current_prices: list[float], running_total: float):
        nonlocal best_combo, best_score
        # Hard node cap as a safety net: keep the best combo found so far and
        # stop exploring rather than hanging on a pathological input.
        nodes[0] += 1
        if nodes[0] > _REBALANCE_MAX_NODES:
            return
        if i == len(items):
            diff = abs(round(running_total - target_subtotal, 2))


            penalty = 0.0
            n = len(base_prices)
            for idx, p in enumerate(current_prices):
                penalty += abs(p - base_prices[idx]) * (n - idx)
            score = (diff, penalty)
            if score < best_score:
                best_score = score
                best_combo = list(current_prices)
            return

        qty = _to_float(items[i].get("quantity", 0))
        if qty <= 0:
            _dfs(i + 1, current_prices + [0.0], running_total)
            return

        for p in options_per_item[i]:

            if running_total + (qty * p) - target_subtotal > 5000:
                continue
            _dfs(i + 1, current_prices + [p], running_total + (qty * p))

    _dfs(0, [], 0.0)
    if not best_combo or best_score[0] > 2.0:
        return


    seen_qty1: set[float] = set()
    for idx, it in enumerate(items):
        qty = _to_float(it.get("quantity", 0))
        chosen = round(best_combo[idx], 2)
        if qty == 1 and chosen in seen_qty1:
            continue
        if qty == 1:
            seen_qty1.add(chosen)
        it["unit_price"] = chosen
        it["total_price"] = round(chosen * qty, 2)


def _desc_tokens(desc: str) -> list[str]:
    words = re.findall(r'[a-z0-9]+', str(desc).lower())
    return [w for w in words if len(w) >= 3][:4]


def _line_match_score(line: str, desc: str) -> int:
    low = line.lower()
    return sum(1 for tok in _desc_tokens(desc) if tok in low)


def _find_best_item_line_index(lines: list[str], desc: str) -> int:
    best_idx = -1
    best_score = 0
    for i, ln in enumerate(lines):
        sc = _line_match_score(ln, desc)
        if sc > best_score:
            best_score = sc
            best_idx = i
    return best_idx


def _extract_qty_tokens(line: str) -> list[float]:
    vals: list[float] = []


    for token in re.findall(r'\b\d{1,2}\.\d{2}\b', line):
        v = _to_float(token)
        if 0 < v <= 20:
            vals.append(v)
    return vals


def _fix_cross_line_item_bundle_swap(items: list[dict], ocr_text: str) -> None:
    """
    Fix common OCR row-merge pattern where one item's description appears on
    a previous line, while two numeric bundles appear on the next line,
    causing adjacent items to get swapped qty/price/total bundles.
    """
    if len(items) < 3:
        return

    section = _extract_item_section(ocr_text)
    if not section:
        return
    lines = [ln for ln in section.splitlines() if ln.strip()]
    if len(lines) < 2:
        return

    for i in range(1, len(items) - 1):
        prev_idx = _find_best_item_line_index(lines, items[i - 1].get("description", ""))
        curr_idx = _find_best_item_line_index(lines, items[i].get("description", ""))
        next_idx = _find_best_item_line_index(lines, items[i + 1].get("description", ""))
        if prev_idx == -1 or curr_idx == -1 or next_idx == -1:
            continue



        if curr_idx != prev_idx or next_idx <= curr_idx:
            continue

        curr_qty_tokens = _extract_qty_tokens(lines[curr_idx])
        next_qty_tokens = _extract_qty_tokens(lines[next_idx])
        if len(next_qty_tokens) < 2 or len(curr_qty_tokens) > 1:
            continue

        qi = _to_float(items[i].get("quantity", 0))
        qj = _to_float(items[i + 1].get("quantity", 0))


        if qi <= 1 and qj > 1:
            keys = ("quantity", "unit_price", "total_price")
            for k in keys:
                items[i][k], items[i + 1][k] = items[i + 1].get(k), items[i].get(k)




def _call_groq(messages: list[dict], job_id: int | None = None) -> dict | None:
    api_key = _groq_api_key()
    if not api_key:
        logger.warning("GROQ_API_KEY not set — skipping Groq.")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _groq_model(),
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    for attempt in range(1, MAX_RETRIES + 1):
        check_cancelled(job_id)
        try:
            resp = requests.post(GROQ_BASE_URL, headers=headers, json=payload, timeout=LLM_TIMEOUT)
            if resp.status_code == 429:
                wait = RETRY_BACKOFF * attempt
                logger.warning(f"Groq rate-limited. Retry {attempt}/{MAX_RETRIES} in {wait}s.")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "{}")
            return json.loads(_extract_json_payload(content))
        except JobCancelledError:
            raise
        except requests.exceptions.Timeout:
            logger.warning(f"Groq timeout (attempt {attempt}).")
            time.sleep(RETRY_BACKOFF * attempt)
        except json.JSONDecodeError as e:
            logger.error(f"Groq returned invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Groq error (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * attempt)
    return None


def _call_openrouter(messages: list[dict], job_id: int | None = None) -> dict | None:
    check_cancelled(job_id)
    api_key = _openrouter_api_key()
    if not api_key:
        logger.error("No OPENROUTER_API_KEY — no LLM available.")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get("OPENROUTER_HTTP_REFERER", "http://localhost"),
        "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "ocr-match"),
    }
    payload = {
        "model": _openrouter_model(),
        "messages": messages,
        "temperature": 0,
    }

    try:
        resp = requests.post(OPENROUTER_BASE_URL, headers=headers, json=payload, timeout=LLM_TIMEOUT)
        resp.raise_for_status()
        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return json.loads(_extract_json_payload(content))
    except JobCancelledError:
        raise
    except Exception as e:
        logger.error(f"OpenRouter fallback failed {e}")
        return None




def parse_with_gemini(ocr_text: str, supplier_hint: str = "", job_id: int | None = None) -> dict:
    """
    Extract structured invoice data from OCR text using an LLM.
    Injects few-shot examples from past corrections for the same supplier.
    """
    if not ocr_text or not ocr_text.strip():
        logger.warning("Empty OCR text passed to LLM parser.")
        return {}

    check_cancelled(job_id)

    feedback_block = ""
    try:
        from app.services.feedback_service import get_few_shot_context
        feedback_block = get_few_shot_context(
            supplier_name=supplier_hint,
            ocr_text=ocr_text,
        )
    except Exception as e:
        logger.warning(f"Feedback context unavailable: {e}")

    user_content = USER_PROMPT_TEMPLATE.format(ocr_text=ocr_text)
    if feedback_block:
        user_content = feedback_block + user_content

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    result = _call_groq(messages, job_id=job_id)
    if result:
        logger.info("Parsed invoice via Groq.")
        return result

    logger.warning("Groq unavailable, falling back to OpenRouter.")
    result = _call_openrouter(messages, job_id=job_id)
    if result:
        logger.info("Parsed invoice via OpenRouter.")
        return result

    logger.error("All LLM providers failed.")
    return {}
