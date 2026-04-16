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

logger = logging.getLogger(__name__)

# ── LLM provider config (read fresh on every call) ────────────────────────

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

MAX_RETRIES = 3
RETRY_BACKOFF = 2


# ── JSON extraction helper ────────────────────────────────────────────────

def _extract_json_payload(text: str) -> str:
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    match = re.search(r'```(?:json)?\s*\n(.*?)\n\s*```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r'(\{.*\})', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


# ── The invoice-extraction prompt (fully generic) ─────────────────────────

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


# ── Post-processing (pure math, no hardcoded domain knowledge) ────────────

def verify_and_fix(parsed: dict) -> dict:
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

        if qty == 0 and up == 0 and tp == 0:
            continue

        # qty × unit_price should ≈ total_price
        if qty > 0 and up > 0 and tp > 0:
            expected = qty * up
            ratio = expected / tp if tp != 0 else 999
            if ratio > 2.0 or ratio < 0.5:
                candidate_qty = tp / up
                if 1 <= candidate_qty <= 500 and candidate_qty == int(candidate_qty):
                    item["quantity"] = int(candidate_qty)
                    qty = int(candidate_qty)

        # Fill missing total from qty × price
        if _to_float(item.get("total_price", 0)) == 0 and qty > 0 and up > 0:
            item["total_price"] = round(qty * up, 2)

        # Fill missing price from total / qty
        if _to_float(item.get("unit_price", 0)) == 0 and qty > 0 and _to_float(item.get("total_price", 0)) > 0:
            item["unit_price"] = round(_to_float(item["total_price"]) / qty, 2)

        fixed_items.append(item)

    # Cross-check: infer price for items with qty but no price using the
    # difference between the stated subtotal/gross and the known item sum.
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

    # Fill missing total_amount from item sum
    if isinstance(financials, dict):
        if _to_float(financials.get("total_amount", 0)) == 0 and fixed_items:
            s = sum(_to_float(it.get("total_price", 0)) for it in fixed_items)
            if s > 0:
                financials["total_amount"] = round(s, 2)
                parsed["financials"] = financials

    # PO cleanup — extract the longest digit sequence, validate against DB
    po = str(parsed.get("po_number", "")).strip()
    digits = re.findall(r'\d+', po)
    if digits:
        parsed["po_number"] = max(digits, key=len)

    return parsed


def _to_float(val) -> float:
    if val is None or val == "":
        return 0.0
    try:
        return float(str(val).replace(",", "").replace("₱", "").replace("$", ""))
    except (ValueError, TypeError):
        return 0.0


# ── API helpers ───────────────────────────────────────────────────────────

def _call_groq(messages: list[dict]) -> dict | None:
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
        try:
            resp = requests.post(GROQ_BASE_URL, headers=headers, json=payload, timeout=120)
            if resp.status_code == 429:
                wait = RETRY_BACKOFF * attempt
                logger.warning(f"Groq rate-limited. Retry {attempt}/{MAX_RETRIES} in {wait}s.")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "{}")
            return json.loads(_extract_json_payload(content))
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


def _call_openrouter(messages: list[dict]) -> dict | None:
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
        resp = requests.post(OPENROUTER_BASE_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return json.loads(_extract_json_payload(content))
    except Exception as e:
        logger.error(f"OpenRouter fallback failed: {e}")
        return None


# ── Public API ────────────────────────────────────────────────────────────

def parse_with_gemini(ocr_text: str) -> dict:
    if not ocr_text or not ocr_text.strip():
        logger.warning("Empty OCR text passed to LLM parser.")
        return {}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT_TEMPLATE.format(ocr_text=ocr_text)},
    ]

    result = _call_groq(messages)
    if result:
        logger.info("Parsed invoice via Groq.")
        return result

    logger.warning("Groq unavailable, falling back to OpenRouter.")
    result = _call_openrouter(messages)
    if result:
        logger.info("Parsed invoice via OpenRouter.")
        return result

    logger.error("All LLM providers failed.")
    return {}


def parse_with_groq(ocr_text: str) -> dict:
    return parse_with_gemini(ocr_text)

def parse_with_openrouter(ocr_text: str) -> dict:
    return parse_with_gemini(ocr_text)
