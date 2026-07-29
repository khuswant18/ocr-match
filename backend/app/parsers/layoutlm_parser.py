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

# Fields where we should keep only the FIRST occurrence (names)
_KEEP_FIRST_FIELDS = {"name"}
# Fields where we should keep only the LAST occurrence (financials at page bottom)
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
        pass  # keep the first value, ignore subsequent duplicates
    elif field_name in _KEEP_LAST_FIELDS:
        d[field_name] = value  # overwrite with the latest value
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
                # Pick whichever is longer (the one with branch info)
                if len(remainder) >= len(original_prefix):
                    best_split = remainder
                else:
                    best_split = original_prefix
                break
        if best_split:
            break

    return best_split if best_split else normalized


# ── Label-to-item-field mapping for row assembly ──
_ITEM_LABEL_TO_FIELD = {
    "ITEM_DESCRIPTION":     "description",
    "QUANTITY":             "quantity",
    "UNIT_PRICE":           "unit_price",
    "LINE_AMOUNT":          "total_price",
    "UNIT":                 "uom",
    "TOTAL_PIECES_PER_ITEM": "total_pieces",
}


def _group_item_words_into_rows(item_words: list[dict]) -> list[dict]:
    """
    Spatially group labeled item words into structured line-item rows.

    Each entry in `item_words` has:
        word  - the OCR text
        label - LayoutLMv3 label (e.g. QUANTITY, ITEM_DESCRIPTION)
        box   - [x0, y0, x1, y1] normalised to 0-1000

    Strategy (description-anchored):
      1. Find all ITEM_DESCRIPTION words - these anchor the rows.
      2. Find all numeric/unit words (QUANTITY, UNIT_PRICE, LINE_AMOUNT, UNIT).
      3. For each numeric word, assign it to the nearest description by
         Y-coordinate distance.  This handles the common invoice layout
         where numbers sit slightly above or below the description.
      4. Assemble each group into a structured item dict.
    """
    if not item_words:
        return []

    # Filter out words with no box info
    valid = [w for w in item_words if w.get("box") and len(w["box"]) == 4]
    if not valid:
        return []

    # Compute Y-centre for every word
    for w in valid:
        w["_y_center"] = (w["box"][1] + w["box"][3]) / 2.0

    # Separate descriptions from numeric/unit fields
    desc_words = [w for w in valid if w["label"] == "ITEM_DESCRIPTION"]
    numeric_words = [w for w in valid if w["label"] != "ITEM_DESCRIPTION"]

    if not desc_words:
        # No descriptions found - fall back to pure Y-clustering
        return _group_by_y_clustering(valid)

    # Sort descriptions by Y position (top to bottom)
    desc_words.sort(key=lambda w: w["_y_center"])

    # Build one bucket per description
    buckets: list[list[dict]] = [[] for _ in desc_words]

    # Assign each numeric word to its nearest description by Y-distance
    for nw in numeric_words:
        best_idx = 0
        best_dist = abs(nw["_y_center"] - desc_words[0]["_y_center"])
        for i, dw in enumerate(desc_words[1:], 1):
            dist = abs(nw["_y_center"] - dw["_y_center"])
            if dist < best_dist:
                best_dist = dist
                best_idx = i
        buckets[best_idx].append(nw)

    # Assemble each bucket into a structured item
    items = []
    for desc_w, bucket in zip(desc_words, buckets):
        item = {
            "description": desc_w["word"],
            "quantity": 0,
            "unit_price": 0.0,
            "total_price": 0.0,
            "uom": "",
            "product_code": "",
        }

        # Collect fields from the bucket
        field_texts: dict[str, list[str]] = {}
        for w in bucket:
            field = _ITEM_LABEL_TO_FIELD.get(w["label"])
            if field:
                field_texts.setdefault(field, []).append(w["word"])

        # Assign text fields
        if "uom" in field_texts:
            item["uom"] = " ".join(field_texts["uom"])

        # Assign numeric fields
        if "quantity" in field_texts:
            item["quantity"] = _parse_numeric(field_texts["quantity"][0])
        if "unit_price" in field_texts:
            item["unit_price"] = _parse_numeric(field_texts["unit_price"][0])
        if "total_price" in field_texts:
            item["total_price"] = _parse_numeric(field_texts["total_price"][0])

        # Cross-check: infer missing total_price or unit_price
        qty = item["quantity"]
        up = item["unit_price"]
        tp = item["total_price"]
        if tp == 0 and qty > 0 and up > 0:
            item["total_price"] = round(qty * up, 2)
        elif up == 0 and qty > 0 and tp > 0:
            item["unit_price"] = round(tp / qty, 2)

        items.append(item)

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

        if has_desc and not has_numbers and merged:
            # This is a continuation line - merge into previous item
            prev = merged[-1]
            prev["description"] = f"{prev['description']} {item['description']}".strip()
            # Inherit UOM if the continuation line has one and the previous doesn't
            if item.get("uom") and not prev.get("uom"):
                prev["uom"] = item["uom"]
        else:
            merged.append(item)

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

    # Attach raw item words so the pipeline can attempt spatial grouping
    result["_item_words"] = item_words

    # Group item words into structured line items
    result["items"] = _group_item_words_into_rows(item_words)

    # Deduplicate supplier/buyer names that still got concatenated
    # (e.g. from multi-word names where _set_nested appended)
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