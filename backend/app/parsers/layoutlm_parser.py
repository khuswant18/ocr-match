"""
LayoutLMv3-based invoice field extractor.
Loads the fine-tuned LayoutLMv3 model once at startup and provides
`extract_fields()` - takes a PIL image + PaddleOCR words/boxes and
returns structured invoice data matching the LLM parser's JSON schema.
Model directory: backend/models/layoutlmv3-invoices/
"""
import json
import logging
import os
import threading
import torch
from PIL import Image
from transformers import AutoProcessor, LayoutLMv3ForTokenClassification
logger = logging.getLogger(__name__)
_MODEL_DIR = os.environ.get(
    "LAYOUTLM_MODEL_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "models", "layoutlmv3-invoices"),
)
_model = None
_processor = None
_load_lock = threading.Lock()
_FIELD_MAP = {
    "INVOICE_NUMBER":   ("invoice_number",),
    "PO_NUMBER":        ("po_number",),
    "INVOICE_DATE":     ("invoice_date",),
    "SO_NUMBER":        ("so_number",),
    "TERMS":            ("terms",),
    "VENDOR_NAME":      ("supplier", "name"),
    "VENDOR_ADDRESS":   ("supplier", "address"),
    "VENDOR_GSTIN":     ("supplier", "tin"),
    "VENDOR_TIN":       ("supplier", "tin"),
    "VENDOR_CONTACT":   ("supplier", "contact"),
    "VENDOR_NUMBER":    ("supplier", "vendor_number"),
    "CUSTOMER_NAME":    ("buyer", "name"),
    "CUSTOMER_ADDRESS": ("buyer", "address"),
    "CUSTOMER_GSTIN":   ("buyer", "tin"),
    "CUSTOMER_TIN":     ("buyer", "tin"),
    "TOTAL_AMOUNT":     ("financials", "total_amount"),
    "SUBTOTAL":         ("financials", "subtotal"),
    "DISCOUNT":         ("financials", "discount"),
}
_ITEM_LABELS = {
    "ITEM_DESCRIPTION", "QUANTITY", "UNIT_PRICE", "LINE_AMOUNT",
    "UNIT", "TOTAL_PIECES_PER_ITEM",
}
_SKIP_LABELS = {"OTHER", "TOTAL_BOX", "TOTAL_PIECES", "SUPPLIER_NUMBER"}
def _ensure_loaded():
    """Load the model + processor exactly once (thread-safe)."""
    global _model, _processor
    if _model is not None:
        return
    with _load_lock:
        if _model is not None:
            return
        model_dir = os.path.abspath(_MODEL_DIR)
        if not os.path.isdir(model_dir):
            raise FileNotFoundError(
                f"LayoutLMv3 model not found at {model_dir}. "
                f"Copy the trained model into backend/models/layoutlmv3-invoices/"
            )
        print(f"[STARTUP] Loading LayoutLMv3 model from {model_dir} ...", flush=True)
        _processor = AutoProcessor.from_pretrained(
            "microsoft/layoutlmv3-base", apply_ocr=False,
        )
        _model = LayoutLMv3ForTokenClassification.from_pretrained(model_dir)
        _model.eval()
        print("[STARTUP] LayoutLMv3 model loaded successfully.", flush=True)
def predict_labels(image: Image.Image, words: list[str], boxes: list[list[int]]):
    """
    Run LayoutLMv3 inference on a single page.
    Returns: List of (word, label) tuples one per input word.
    """
    _ensure_loaded()
    if not words:
        return []
def _predict_single_pass(
    image: Image.Image, words: list[str], boxes: list[list[int]]
) -> list[tuple[str, str]]:
    """Run LayoutLMv3 inference in a single pass (all words fit in 512 tokens)."""
    encoding = _processor(
        image, words, boxes=boxes,
        truncation=True, return_tensors="pt",
    )
    with torch.no_grad():
        outputs = _model(**encoding)
    preds = outputs.logits.argmax(-1).squeeze().tolist()
    if isinstance(preds, int):
        preds = [preds]
    word_ids = encoding.word_ids(batch_index=0)
    per_word_labels = ["OTHER"] * len(words)
    seen = set()
    for token_idx, word_id in enumerate(word_ids):
        if word_id is None or word_id in seen:
            continue
        seen.add(word_id)
        if token_idx < len(preds):
            per_word_labels[word_id] = _model.config.id2label[preds[token_idx]]
    return list(zip(words, per_word_labels))
def predict_labels(image: Image.Image, words: list[str], boxes: list[list[int]]):
    """
    Run LayoutLMv3 inference on a single page.
    When the input exceeds the model's 512-token limit, a sliding-window
    approach is used: words are split into overlapping chunks that each
    fit within 512 tokens, inference is run on each chunk, and per-word
    predictions are merged by keeping the highest-confidence label.
    Returns: List of (word, label) tuples, one per input word.
    """
    _ensure_loaded()
    if not words:
        return []
    # --- Count approximate subword tokens per word ---
    _tokenizer = _processor.tokenizer
    tokens_per_word = []
    for w in words:
        n_toks = len(_tokenizer.tokenize(w)) if w.strip() else 1
        tokens_per_word.append(max(n_toks, 1))
    MAX_SEQ_LEN = 512
    SPECIAL_TOKENS = 2          # CLS + SEP
    available = MAX_SEQ_LEN - SPECIAL_TOKENS  # 510 content tokens
    total_content_tokens = sum(tokens_per_word)
    if total_content_tokens <= available:
        return _predict_single_pass(image, words, boxes)
    # --- Sliding window: build word-level windows ---
    logger.info(
        "[LayoutLMv3] Input has ~%d tokens (>%d), "
        "using sliding window over %d words",
        total_content_tokens + SPECIAL_TOKENS, MAX_SEQ_LEN, len(words),
    )
    windows: list[tuple[int, int]] = []   # (start_word_idx, end_word_idx)
    start = 0
    while start < len(words):
        token_budget = 0
        end = start
        while end < len(words) and token_budget + tokens_per_word[end] <= available:
            token_budget += tokens_per_word[end]
            end += 1
        if end == start:
            end = start + 1             # force progress on huge single words
        windows.append((start, end))
        if end >= len(words):
            break
        # Step back by ~20 % of the window size so boundary words get
        # a second prediction from the next window.
        overlap_words = max((end - start) // 5, 3)
        start = end - overlap_words
    logger.info(
        "[LayoutLMv3] Created %d windows: %s",
        len(windows),
        [(s, e) for s, e in windows],
    )
    # --- Run inference per window and merge by confidence ---
    per_word_labels = ["OTHER"] * len(words)
    per_word_confidence = [-1.0] * len(words)
    for win_start, win_end in windows:
        win_words = words[win_start:win_end]
        win_boxes = boxes[win_start:win_end]
        encoding = _processor(
            image, win_words, boxes=win_boxes,
            truncation=True, return_tensors="pt",
        )
        with torch.no_grad():
            outputs = _model(**encoding)
        logits = outputs.logits.squeeze(0)          # (seq_len, num_labels)
        probs = torch.softmax(logits, dim=-1)
        preds = logits.argmax(-1).tolist()
        if isinstance(preds, int):
            preds = [preds]
        word_ids = encoding.word_ids(batch_index=0)
        seen: set[int] = set()
        for token_idx, word_id in enumerate(word_ids):
            if word_id is None or word_id in seen:
                continue
            seen.add(word_id)
            if token_idx >= len(preds):
                continue
            global_idx = win_start + word_id
            if global_idx >= len(words):
                continue
            label = _model.config.id2label[preds[token_idx]]
            conf = probs[token_idx].max().item()
            if conf > per_word_confidence[global_idx]:
                per_word_labels[global_idx] = label
                per_word_confidence[global_idx] = conf
    return list(zip(words, per_word_labels))
_KEEP_FIRST_FIELDS = {"name"}
_KEEP_LAST_FIELDS = {"total_amount", "subtotal", "discount"}
def _set_nested(d: dict, path: tuple, value: str):
    """Set a value in a nested dict using a path tuple.
    - For name fields: keep first occurrence (avoid 'VIRGINIA FOOD VIRGINIA FOOD').
    - For financial fields: keep last occurrence (bottom-of-page value).
    - For everything else: append (e.g. multi-word addresses).
    """
    for key in path[:-1]:
        d = d.setdefault(key, {})
    field_name = path[-1]
    existing = d.get(field_name, "")
    if not existing:
        d[field_name] = value
    elif field_name in _KEEP_FIRST_FIELDS:
        pass
    elif field_name in _KEEP_LAST_FIELDS:
        d[field_name] = value
    else:
        d[field_name] = f"{existing} {value}"
def _parse_numeric(value: str, default=0.0):
    """Parse a numeric string, stripping commas and currency symbols."""
    if not value or not value.strip():
        return default
    try:
        clean = value.replace(',', '').replace('$', '').replace('\u20b1', '').replace('P', '').strip()
        return float(clean)
    except (ValueError, TypeError):
        return default
import re as _re

def _contains_chinese(text: str) -> bool:
    if not text:
        return False
    return bool(_re.search(r'[\u4e00-\u9fff]', text))

def _dedup_name(name: str) -> str:
    """Remove duplicate company names concatenated by OCR.
    E.g. 'VIRGINIA FOOD, INC. VIRGINIA FOOD,INC.' -> 'VIRGINIA FOOD, INC.'
         'PRINCEPAN CORPORATION PRINCEPAN CORPORATION-POTOTAN'
         -> 'PRINCEPAN CORPORATION-POTOTAN'
    """
    if not name or len(name) < 10:
        return name
    # Normalize for comparison: collapse whitespace, lowercase
    normalized = ' '.join(name.split()).strip()
    # Try to find the point where the name repeats itself
    words = normalized.split()
    n = len(words)
    best_split = None
    # Check if the first K words appear again starting at position K
    for k in range(2, n // 2 + 1):
        prefix = ' '.join(words[:k]).lower()
        # Strip punctuation for fuzzy matching
        prefix_clean = _re.sub(r'[^a-z0-9 ]', '', prefix).strip()
        if len(prefix_clean) < 5:
            continue
        for start in range(k, n - 1):
            candidate = ' '.join(words[start:start + k]).lower()
            candidate_clean = _re.sub(r'[^a-z0-9 ]', '', candidate).strip()
            if candidate_clean == prefix_clean:
                # Found duplicate - keep everything from 'start' onward
                # (it usually has the branch name appended)
                remainder = ' '.join(words[start:])
                original_prefix = ' '.join(words[:start]).strip()
                if len(remainder) >= len(original_prefix):
                    best_split = remainder
                else:
                    best_split = original_prefix
                break
        if best_split:
            break
    return best_split if best_split else normalized
_ITEM_LABEL_TO_FIELD = {
    "ITEM_DESCRIPTION":     "description",
    "QUANTITY":             "quantity",
    "UNIT_PRICE":           "unit_price",
    "LINE_AMOUNT":          "total_price",
    "UNIT":                 "uom",
    "TOTAL_PIECES_PER_ITEM": "total_pieces",
}
def _monotonic_assign(
    values: list[dict], slots_y: list[float]
) -> list[int | None]:
    """Solve monotonic assignment from M values to N slots (M ≤ N).
    Finds the order-preserving mapping (each value goes to a slot index ≥
    the previous value's slot) that minimises total |y_value - y_slot| cost.
    Slots with no assigned value get ``None``.
    Returns a length-N list: ``slot_to_value[i]`` is the index into *values*
    assigned to slot *i*, or ``None`` if the slot is empty.
    Algorithm: DP similar to sequence alignment with gap/skip.
    ``dp[j][i]`` = min cost of assigning the first *j* values to some
    monotonic subset of the first *i* slots.
    """
    M = len(values)
    N = len(slots_y)
    if M == 0:
        return [None] * N
    values_y = [v["_y_center"] for v in values]
    INF = float("inf")
    # dp[j][i]: min cost assigning first j values into first i slots
    # j in 0..M, i in 0..N
    dp = [[INF] * (N + 1) for _ in range(M + 1)]
    dp[0] = [0.0] * (N + 1)
    for j in range(1, M + 1):
        for i in range(j, N + 1):  # need at least j slots for j values
            # Option 1: skip slot i (don't assign any value to slot i)
            skip = dp[j][i - 1]
            # Option 2: assign value j to slot i
            cost = abs(values_y[j - 1] - slots_y[i - 1])
            assign = dp[j - 1][i - 1] + cost
            dp[j][i] = min(skip, assign)
    # Backtrack to recover the assignment
    slot_to_value: list[int | None] = [None] * N
    j, i = M, N
    while j > 0 and i > 0:
        if i > j and dp[j][i - 1] <= dp[j][i]:
            # This slot was skipped
            i -= 1
        else:
            # Value j was assigned to slot i
            slot_to_value[i - 1] = j - 1
            j -= 1
            i -= 1
    return slot_to_value
def _arithmetic_check(
    qty: float, unit_price: float, line_amount: float, tol: float = 0.01
) -> bool:
    """Check whether qty × unit_price ≈ line_amount within tolerance.
    Returns True (passes) if any of the three values is 0/missing — there's
    nothing to check — or if the computed product is within tolerance.
    """
    if qty == 0 or unit_price == 0 or line_amount == 0:
        return True  # can't verify with missing data
    expected = qty * unit_price
    abs_tol = max(abs(line_amount) * tol, 0.01)
    return abs(expected - line_amount) <= abs_tol
def _swap_correction(items: list[dict], field: str) -> list[dict]:
    """Try pairwise adjacent swaps of *field* to maximise arithmetic-passing rows.
    For each row that fails ``_arithmetic_check``, try swapping *field* with
    the adjacent row and keep whichever configuration produces more passing
    rows across the whole table.
    """
    if len(items) < 2:
        return items
    def _count_passing(itms: list[dict]) -> int:
        return sum(
            1
            for it in itms
            if _arithmetic_check(it["quantity"], it["unit_price"], it["total_price"])
        )
    best_score = _count_passing(items)
    # Try swapping each consecutive pair for the given field
    for idx in range(len(items) - 1):
        a, b = items[idx], items[idx + 1]
        # Only try if at least one of the pair currently fails
        if _arithmetic_check(a["quantity"], a["unit_price"], a["total_price"]) and \
           _arithmetic_check(b["quantity"], b["unit_price"], b["total_price"]):
            continue
        # Swap
        a[field], b[field] = b[field], a[field]
        new_score = _count_passing(items)
        if new_score > best_score:
            best_score = new_score  # keep the swap
        else:
            # Revert
            a[field], b[field] = b[field], a[field]
    return items
def _group_item_words_into_rows(item_words: list[dict]) -> list[dict]:
    """Spatially group labeled item words into structured line-item rows.
    Each entry in ``item_words`` has:
        word  – the OCR text
        label – LayoutLMv3 label (e.g. QUANTITY, ITEM_DESCRIPTION)
        box   – [x0, y0, x1, y1] normalised to 0-1000
    Strategy (description-anchored, monotonic DP alignment):
      1. ITEM_DESCRIPTION words sorted by y are the N row anchors.
      2. For each field column, solve a monotonic (order-preserving)
         assignment to the N row slots that minimises total y-distance.
      3. Pairwise swap correction using qty×price≈amount arithmetic.
      4. Backfill missing total_price or unit_price from the other two.
      5. Tag rows that still fail the arithmetic check with _low_confidence.
    """
    if not item_words:
        return []
    valid = [w for w in item_words if w.get("box") and len(w["box"]) == 4]
    if not valid:
        return []
    for w in valid:
        w["_y_center"] = (w["box"][1] + w["box"][3]) / 2.0
    desc_words = [w for w in valid if w["label"] == "ITEM_DESCRIPTION"]
    if not desc_words:
        return _group_by_y_clustering(valid)
    # --- Step 1: Row anchors from descriptions (sorted by y) ---
    desc_words.sort(key=lambda w: w["_y_center"])
    N = len(desc_words)
    slots_y = [dw["_y_center"] for dw in desc_words]
    # --- Step 2: Separate each field column, sorted by y ---
    field_columns: dict[str, list[dict]] = {}
    for w in valid:
        if w["label"] == "ITEM_DESCRIPTION":
            continue
        field_columns.setdefault(w["label"], []).append(w)
    for col_words in field_columns.values():
        col_words.sort(key=lambda w: w["_y_center"])
    # --- Step 3: Monotonic DP assignment per field ---
    # slot_assignments[label] = list of length N, each entry is assigned word or None
    slot_assignments: dict[str, list[dict | None]] = {}
    for label, col_words in field_columns.items():
        mapping = _monotonic_assign(col_words, slots_y)
        slot_assignments[label] = [
            col_words[mapping[i]] if mapping[i] is not None else None
            for i in range(N)
        ]
    # --- Assemble row dicts ---
    items: list[dict] = []
    for row_idx in range(N):
        item: dict = {
            "description": desc_words[row_idx]["word"],
            "quantity": 0,
            "unit_price": 0.0,
            "total_price": 0.0,
            "uom": "",
            "product_code": "",
            "_dp_row": True,
        }
        # Collect all assigned words for this row, grouped by field
        field_texts: dict[str, list[str]] = {}
        for label, assignments in slot_assignments.items():
            assigned_word = assignments[row_idx]
            if assigned_word is not None:
                field = _ITEM_LABEL_TO_FIELD.get(label)
                if field:
                    field_texts.setdefault(field, []).append(assigned_word["word"])
        if "uom" in field_texts:
            item["uom"] = " ".join(field_texts["uom"])
        if "quantity" in field_texts:
            item["quantity"] = _parse_numeric(field_texts["quantity"][0])
        if "unit_price" in field_texts:
            item["unit_price"] = _parse_numeric(field_texts["unit_price"][0])
        if "total_price" in field_texts:
            item["total_price"] = _parse_numeric(field_texts["total_price"][0])
        items.append(item)
    for field in ("quantity", "unit_price", "total_price"):
        _swap_correction(items, field)
    for item in items:
        qty = item["quantity"]
        up = item["unit_price"]
        tp = item["total_price"]
        if tp == 0 and qty > 0 and up > 0:
            item["total_price"] = round(qty * up, 2)
        elif up == 0 and qty > 0 and tp > 0:
            item["unit_price"] = round(tp / qty, 2)
    # --- Step 6: Flag low-confidence rows ---
    for item in items:
        qty = item["quantity"]
        up = item["unit_price"]
        tp = item["total_price"]
        if qty != 0 and up != 0 and tp != 0:
            if not _arithmetic_check(qty, up, tp):
                item["_low_confidence"] = True
    return _merge_continuation_items(items)
def _merge_continuation_items(items: list[dict]) -> list[dict]:
    """
    Merge consecutive items where the second has a description but
    no qty/price - these are continuation lines (e.g. product codes
    like 'HC80195 (1 X 480 pcs)' on a second row).
    The continuation description is appended to the previous item's
    description and the empty item is removed.
    """
    if len(items) <= 1:
        return items
    merged = [items[0]]
    for item in items[1:]:
        has_desc = bool(item.get("description", "").strip())
        has_numbers = (
            item.get("quantity", 0) not in (0, 0.0)
            or item.get("unit_price", 0) not in (0, 0.0)
            or item.get("total_price", 0) not in (0, 0.0)
        )
        if has_desc and not has_numbers and not item.get("_dp_row") and merged:
            prev = merged[-1]
            prev["description"] = f"{prev['description']} {item['description']}".strip()
            if item.get("uom") and not prev.get("uom"):
                prev["uom"] = item["uom"]
        else:
            merged.append(item)
    for item in merged:
        item.pop("_dp_row", None)
    return merged
def _group_by_y_clustering(valid: list[dict]) -> list[dict]:
    """
    Fallback: group item words into rows by Y-coordinate clustering
    when no ITEM_DESCRIPTION labels are present.
    """
    valid.sort(key=lambda w: w["_y_center"])
    heights = [abs(w["box"][3] - w["box"][1]) for w in valid]
    avg_height = sum(heights) / len(heights) if heights else 30
    row_threshold = max(avg_height * 0.6, 15)
    rows: list[list[dict]] = []
    current_row = [valid[0]]
    current_y_sum = valid[0]["_y_center"]
    for w in valid[1:]:
        row_mean_y = current_y_sum / len(current_row)
        if abs(w["_y_center"] - row_mean_y) <= row_threshold:
            current_row.append(w)
            current_y_sum += w["_y_center"]
        else:
            rows.append(current_row)
            current_row = [w]
            current_y_sum = w["_y_center"]
    rows.append(current_row)
    items = []
    for row_words in rows:
        row_words.sort(key=lambda w: w["box"][0])
        item = {
            "description": "",
            "quantity": 0,
            "unit_price": 0.0,
            "total_price": 0.0,
            "uom": "",
            "product_code": "",
        }
        field_texts: dict[str, list[str]] = {}
        for w in row_words:
            field = _ITEM_LABEL_TO_FIELD.get(w["label"])
            if field:
                field_texts.setdefault(field, []).append(w["word"])
        if "description" in field_texts:
            item["description"] = " ".join(field_texts["description"])
        if "uom" in field_texts:
            item["uom"] = " ".join(field_texts["uom"])
        if "quantity" in field_texts:
            item["quantity"] = _parse_numeric(field_texts["quantity"][0])
        if "unit_price" in field_texts:
            item["unit_price"] = _parse_numeric(field_texts["unit_price"][0])
        if "total_price" in field_texts:
            item["total_price"] = _parse_numeric(field_texts["total_price"][0])
        qty = item["quantity"]
        up = item["unit_price"]
        tp = item["total_price"]
        if tp == 0 and qty > 0 and up > 0:
            item["total_price"] = round(qty * up, 2)
        elif up == 0 and qty > 0 and tp > 0:
            item["unit_price"] = round(tp / qty, 2)
        if not item["description"] and qty == 0 and up == 0 and tp == 0:
            continue
        items.append(item)
    return items
def extract_fields(image: Image.Image, words: list[str], boxes: list[list[int]]) -> dict:
    labeled = predict_labels(image, words, boxes)
    if not labeled:
        return {}
    result = {
        "supplier": {},
        "buyer": {},
        "financials": {},
        "_layoutlm_used": True,
    }
    item_words = []
    for i, (word, label) in enumerate(labeled):
        if label in _SKIP_LABELS:
            continue
        if label in _FIELD_MAP:
            _set_nested(result, _FIELD_MAP[label], word)
        elif label in _ITEM_LABELS:
            item_words.append({
                "word": word,
                "label": label,
                "box": boxes[i] if i < len(boxes) else [],
            })
    result["_item_words"] = item_words
    all_items = _group_item_words_into_rows(item_words)
    result["items"] = [item for item in all_items if not _contains_chinese(item.get("description", ""))]
    for entity_key in ("supplier", "buyer"):
        entity = result.get(entity_key, {})
        name = entity.get("name", "")
        if name:
            entity["name"] = _dedup_name(name)
    for key in ("supplier", "buyer", "financials"):
        if not result[key]:
            result[key] = {}
    return result
def extract_fields_multi_page(
    images: list[Image.Image],
    all_words: list[list[str]],
    all_boxes: list[list[list[int]]],
) -> dict:
    """
    Run LayoutLMv3 across multiple pages and merge results.
    Each argument is a list (one element per page).
    """
    merged = {
        "supplier": {},
        "buyer": {},
        "financials": {},
        "_layoutlm_used": True,
        "_item_words": [],
        "items": [],
    }
    for page_img, page_words, page_boxes in zip(images, all_words, all_boxes):
        page_result = extract_fields(page_img, page_words, page_boxes)
        print("page_result=====================", page_result)
        if not page_result:
            continue
        for key in ("invoice_number", "po_number", "invoice_date", "so_number", "terms"):
            if key not in merged and page_result.get(key):
                merged[key] = page_result[key]
        for key in ("supplier", "buyer", "financials"):
            page_sub = page_result.get(key, {})
            for sub_key, sub_val in page_sub.items():
                if sub_val and not merged[key].get(sub_key):
                    merged[key][sub_key] = sub_val
        merged["_item_words"].extend(page_result.get("_item_words", []))
        merged["items"].extend(page_result.get("items", []))
    return merged