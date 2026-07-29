"""
LayoutLMv3-based invoice field extractor.

Loads the fine-tuned LayoutLMv3 model once at startup and provides
`extract_fields()` — takes a PIL image + PaddleOCR words/boxes and
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

def _set_nested(d: dict, path: tuple, value: str):
    """Set a value in a nested dict using a path tuple, appending if already set."""
    for key in path[:-1]:
        d = d.setdefault(key, {})
    existing = d.get(path[-1], "")
    if existing:
        d[path[-1]] = f"{existing} {value}"
    else:
        d[path[-1]] = value

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

    return merged