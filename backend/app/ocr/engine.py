"""
PaddleOCR + LayoutLMv3 + LLM extraction engine.

This module is the **single source of truth** for invoice extraction.
Both the /paddleOCR HTTP route and the background match worker call
`extract_and_parse()` directly (in-process), so PaddleOCR is serialized
by `_ocr_lock` without any self-HTTP hop.

No Flask imports — this is a pure service/engine module.
"""

import os
import json
import time
import logging
import threading
from paddleocr import PaddleOCR
from PIL import Image as PILImage
import numpy as np
from app.parsers.llm_parser import parse_with_gemini, verify_and_fix
from app.parsers.layoutlm_parser import extract_fields_multi_page as layoutlm_extract
from app.utils.operations import add_invoice_to_db, check_if_invoice, process_paddleocr_text
from app.utils.utils import load_images_from_bytes, _is_pdf
from app.models import db, Invoice
from app.cancel_registry import check_cancelled, JobCancelledError
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

MIN_OCR_CONFIDENCE = 40.0
MIN_OCR_WORDS = 10

UPLOAD_FOLDER = 'uploads/invoices/'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _build_ocr():
    return PaddleOCR(
        use_angle_cls=True,
        lang='en',
        show_log=False,
        det_db_thresh=0.3,
        det_db_box_thresh=0.5,
        det_db_unclip_ratio=1.8,
    )

print("[STARTUP] Loading PaddleOCR models into memory...", flush=True)
ocr = _build_ocr()
print("[STARTUP] PaddleOCR models loaded successfully.", flush=True)

# The PaddleOCR predictor reuses fixed tensor buffers and is NOT thread-safe.
# Flask's dev server is multi-threaded and a background worker also calls this
# endpoint, so concurrent requests would corrupt the shared predictor
# ("Tensor holds no memory"). Serialise all predictor access with this lock.
_ocr_lock = threading.Lock()

class ExtractionError(Exception):
    """
    A non-cancellation failure in the OCR/parse pipeline that should be
    surfaced to the caller with a specific HTTP status and payload.
    Both the HTTP route and the in-process worker raise/handle this.
    """
    def __init__(self, message, status_code=400, payload=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload or {}

def _extract_words_and_boxes(all_results, images):
    """
        page_words:  list of list[str]         — one list of words per page
        page_boxes:  list of list[[x0,y0,x1,y1]] — normalised to 0-1000
        page_images: list of PIL.Image.Image   — RGB images per page
    """
    page_words = []
    page_boxes = []
    page_images = []

    for page_idx, page_result in enumerate(all_results):
        if not page_result:
            continue

        if page_idx < len(images):
            img_np = images[page_idx]
            h, w = img_np.shape[:2]
            pil_img = PILImage.fromarray(img_np).convert("RGB")
        else:
            continue

        words = []
        boxes = []
        for line in page_result:
            bbox = line[0]
            text = line[1][0]

            if not text or not text.strip():
                continue

            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x0, x1 = min(xs), max(xs)
            y0, y1 = min(ys), max(ys)

            norm_box = [
                max(0, min(1000, int(1000 * float(x0) / w))),
                max(0, min(1000, int(1000 * float(y0) / h))),
                max(0, min(1000, int(1000 * float(x1) / w))),
                max(0, min(1000, int(1000 * float(y1) / h))),
            ]
            words.append(text.strip())
            boxes.append(norm_box)

        if words:
            page_words.append(words)
            page_boxes.append(boxes)
            page_images.append(pil_img)

    return page_words, page_boxes, page_images

def _merge_layoutlm_and_llm(layoutlm_data, llm_data):
    """
    Merge LayoutLMv3 header fields with LLM parsed data.
    LayoutLMv3 wins for header/footer fields it confidently extracted.
    LLM wins for line items and any fields LayoutLMv3 missed.
    """
    if not layoutlm_data:
        return llm_data
    if not llm_data:
        return layoutlm_data

    merged = dict(llm_data)

    for key in ("invoice_number", "po_number", "invoice_date", "so_number", "terms"):
        lm_val = layoutlm_data.get(key, "").strip() if layoutlm_data.get(key) else ""
        if lm_val:
            merged[key] = lm_val

    for key in ("supplier", "buyer"):
        lm_sub = layoutlm_data.get(key, {})
        llm_sub = merged.get(key, {})
        if not isinstance(llm_sub, dict):
            llm_sub = {}
        for sub_key in ("name", "address", "tin", "contact", "vendor_number"):
            lm_val = lm_sub.get(sub_key, "").strip() if lm_sub.get(sub_key) else ""
            llm_val = str(llm_sub.get(sub_key, "")).strip() if llm_sub.get(sub_key) else ""
            if lm_val and not llm_val:
                llm_sub[sub_key] = lm_val
        merged[key] = llm_sub

    lm_fin = layoutlm_data.get("financials", {})
    llm_fin = merged.get("financials", {})
    if not isinstance(llm_fin, dict):
        llm_fin = {}
    for sub_key in ("subtotal", "total_amount", "discount"):
        lm_val = lm_fin.get(sub_key, "").strip() if lm_fin.get(sub_key) else ""
        llm_val = str(llm_fin.get(sub_key, "")).strip() if llm_fin.get(sub_key) else ""
        if lm_val and not llm_val:
            llm_fin[sub_key] = lm_val
    merged["financials"] = llm_fin

    merged.pop("_layoutlm_used", None)
    merged.pop("_item_words", None)

    return merged

def _run_document_ocr(images, job_id=None):
    """
    Run OCR over every page image while holding the predictor lock.
    A single "Tensor holds no memory" failure leaves the shared predictor
    corrupted, so on a RuntimeError we rebuild it once and retry the whole
    document — otherwise every later request would fail until a manual restart.
    """
    global ocr
    for attempt in (1, 2):
        try:
            all_results = []
            for page_img in images:
                check_cancelled(job_id) #if user cancelled the job
                page_result = ocr.ocr(page_img, cls=True)
                if page_result and page_result[0]:
                    all_results.extend(page_result)
            return all_results
        except JobCancelledError:
            raise
        except RuntimeError as e:
            if attempt == 1:
                logger.error(f"[OCR] predictor error, rebuilding and retrying once: {e}")
                ocr = _build_ocr()
                continue
            raise

def extract_and_parse(file_bytes, filename, po_number=None, job_id=None, existing_path=None):
    ocr_method = 'PaddleOCR+LayoutLMv3'

    images = load_images_from_bytes(file_bytes)
    if not images:
        raise ExtractionError('No valid image or PDF found in request.', status_code=400)

    check_cancelled(job_id)

    start_time_recognition = time.time()
    with _ocr_lock:
        all_results = _run_document_ocr(images, job_id=job_id)
    recognition_time = time.time() - start_time_recognition
    print("\n" + "=" * 60)
    print("[OCR] All results: ", all_results)
    if not all_results:
        raise ExtractionError('OCR failed to extract any text from the document.', status_code=400)
    average_confidence, text = process_paddleocr_text(all_results)
    word_count = len(text.split())

    # if average_confidence * 100 < MIN_OCR_CONFIDENCE:
    #     raise ExtractionError(
    #         f'OCR confidence too low ({average_confidence*100:.1f}%). Please upload a clearer scan.',
    #         status_code=400,
    #         payload={'average_confidence': average_confidence * 100, 'text': text},
    #     )

    # if word_count < MIN_OCR_WORDS:
    #     raise ExtractionError(
    #         f'OCR extracted too few words ({word_count}). The document may be blank or unreadable.',
    #         status_code=400,
    #         payload={'average_confidence': average_confidence * 100, 'text': text},
    #     )

    # print("\n" + "=" * 60)
    # print("[OCR] EXTRACTED TEXT:")
    # print("=" * 60)
    # print(text)
    # print("=" * 60 + "\n")

    check_cancelled(job_id)

    layoutlm_data = {}
    try:
        page_words, page_boxes, page_images = _extract_words_and_boxes(
            all_results, images,
        )
        print("\n==============================")
        print("[LayoutLMv3] Page words: ", page_words)
        print("[LayoutLMv3] Page boxes: ", page_boxes)
        print("[LayoutLMv3] Page images: ", page_images)
        print("==============================\n")
        if page_words:
            start_layoutlm = time.time()
            layoutlm_data = layoutlm_extract(page_images, page_words, page_boxes)
            layoutlm_time = time.time() - start_layoutlm
            # print(f"\n[LayoutLMv3] Extracted fields in {layoutlm_time:.2f}s:")
            display = {k: v for k, v in layoutlm_data.items()
                       if not k.startswith("_")}
            # print(json.dumps(display, indent=2))
    except Exception as e:
        print(f"[LayoutLMv3] Warning: inference failed, falling back to LLM only: {e}")
        layoutlm_data = {}
    print("layoutlm_data================================================>", layoutlm_data)

    check_cancelled(job_id)

    # LLM: extract full structured data (esp. line items)
    # start_time_parsing = time.time()
    # parsed_data = parse_with_gemini(text, job_id=job_id)
    # parsing_time = time.time() - start_time_parsing

    # if isinstance(parsed_data, str):
    #     try:
    #         clean_string = parsed_data.strip().removeprefix('```json').removesuffix('```').strip()
    #         parsed_data = json.loads(clean_string)
    #     except json.JSONDecodeError:
    #         logging.error(f"LLM returned invalid JSON string: {parsed_data}")
    #         raise ExtractionError(
    #             'Failed to parse LLM output as JSON.',
    #             status_code=500,
    #             payload={'raw_output': parsed_data},
    #         )

    # if not parsed_data and layoutlm_data:
    #     parsed_data = layoutlm_data
    # elif not parsed_data:
    #     raise ExtractionError('Both LayoutLMv3 and LLM parsing failed. Please retry.', status_code=502)

    # check_cancelled(job_id)

    # Merge LayoutLMv3 + LLM results
    # if isinstance(parsed_data, dict):
    #     parsed_data = _merge_layoutlm_and_llm(layoutlm_data, parsed_data)
    #     if po_number:
    #         parsed_data["po_number"] = po_number
    #     parsed_data = verify_and_fix(parsed_data, text)

    # print("\n" + "=" * 60)
    # print("[MERGED] FINAL PARSED DATA (LayoutLMv3 + LLM + verification):")
    # print("=" * 60)
    # print(json.dumps(parsed_data, indent=4))
    # print("=" * 60 + "\n")

    meta = {
        'recognition_time': recognition_time,
        # 'parsing_time': parsing_time,
        'average_confidence': average_confidence * 100,
    }

    invoice_id = None
    # if isinstance(parsed_data, dict) and check_if_invoice(parsed_data):
    #     inv_num = parsed_data.get("invoice_number", "")
    #     inv_num = inv_num.strip() if isinstance(inv_num, str) else str(inv_num).strip()

    #     po_num = parsed_data.get("po_number", "")
    #     po_num = po_num.strip() if isinstance(po_num, str) else str(po_num).strip()

    #     existings = []
    #     if po_num:
    #         existings = Invoice.query.filter_by(po_number=po_num).all()
    #     elif inv_num:
    #         existings = Invoice.query.filter_by(invoice_number=inv_num).all()

    #     if existings:
    #         for existing in existings:
    #             match_type = f"PO {po_num}" if po_num else f"invoice {inv_num}"
    #             logger.warning(f"[DUPLICATE REPLACED] Match found for {match_type}. Deleting old invoice (id={existing.id}).")
    #             db.session.delete(existing)
    #         db.session.commit()

    #     save_path = existing_path
    #     if not save_path:
    #         safe_name = secure_filename(filename or 'upload')
    #         save_path = os.path.join(UPLOAD_FOLDER, f"{int(time.time())}_{safe_name}")
    #         with open(save_path, 'wb') as out:
    #             out.write(file_bytes)

    #     is_pdf = _is_pdf(file_bytes)
    #     pdf_path_string = save_path if is_pdf else None
    #     img_path_string = None if is_pdf else save_path

    #     invoice_id = add_invoice_to_db(
    #         parsed_data=parsed_data,
    #         text=text,
    #         pdf_file=pdf_path_string,
    #         img_file=img_path_string,
    #         average_confidence=average_confidence * 100,
    #         recognition_time=recognition_time,
    #         parsing_time=parsing_time,
    #         ocr_method=ocr_method
    #     )
    # else:
    #     meta['warning'] = 'Document was not recognized as a valid invoice. Not saved to database.'

    return invoice_id, layoutlm_data, text, meta
