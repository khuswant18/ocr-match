import os
import re
import json
import time
import logging
from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename
from paddleocr import PaddleOCR
from app.parsers.llm_parser import parse_with_gemini, verify_and_fix
from app.utils.operations import add_invoice_to_db, check_if_invoice, process_paddleocr_text
from app.utils.utils import load_images_from_request
from app.models import db, Invoice

logger = logging.getLogger(__name__)

MIN_OCR_CONFIDENCE = 40.0  # reject if average OCR confidence below this %
MIN_OCR_WORDS = 10         # reject if fewer than this many words extracted

paddleocr_bp = Blueprint('paddleocr', __name__)

UPLOAD_FOLDER = 'uploads/invoices/'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

print("[STARTUP] Loading PaddleOCR models into memory...", flush=True)
ocr = PaddleOCR(
    use_angle_cls=True,
    lang='en',
    show_log=False,
    det_db_thresh=0.3,
    det_db_box_thresh=0.5,
    det_db_unclip_ratio=1.8,
)
print("[STARTUP] PaddleOCR models loaded successfully.", flush=True)


def _merge_ocr_passes(results_list: list) -> list:
    """
    Merge OCR results from multiple preprocessing passes.
    For overlapping detections (IoU > 0.4), keep the higher-confidence one.
    Non-overlapping detections from either pass are kept — this catches
    items that one pass misses entirely.
    """
    if len(results_list) == 1:
        return results_list[0]

    all_detections = []
    for pass_results in results_list:
        if not pass_results:
            continue
        for res in pass_results:
            if not res:
                continue
            for line in res:
                all_detections.append(line)

    if not all_detections:
        return []

    def _box_iou(a, b):
        ax1, ay1, ax2, ay2 = a[0][0], a[0][1], a[2][0], a[2][1]
        bx1, by1, bx2, by2 = b[0][0], b[0][1], b[2][0], b[2][1]
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        return inter / (area_a + area_b - inter)

    all_detections.sort(key=lambda d: d[1][1], reverse=True)

    kept = []
    used = [False] * len(all_detections)
    for i, det_i in enumerate(all_detections):
        if used[i]:
            continue
        kept.append(det_i)
        used[i] = True
        for j in range(i + 1, len(all_detections)):
            if used[j]:
                continue
            if _box_iou(det_i[0], all_detections[j][0]) > 0.4:
                used[j] = True

    return [kept] if kept else []


@paddleocr_bp.route('/paddleOCR', methods=['POST'])
def process_paddleocr():
    try:
        page_variants_list = load_images_from_request()
        if not page_variants_list:
            return jsonify({'error': 'No valid image or PDF found in request.'}), 400

        ocr_method = 'PaddleOCR'

        # ── STEP 1: Dual-pass OCR on every page ──────────────────────
        start_time_recognition = time.time()

        all_results = []
        for page_variants in page_variants_list:
            pass_results = []
            for variant_img in page_variants:
                page_result = ocr.ocr(variant_img, cls=True)
                if page_result and page_result[0]:
                    pass_results.append(page_result)

            merged = _merge_ocr_passes(pass_results) if pass_results else []
            if merged:
                all_results.extend(merged)

        recognition_time = time.time() - start_time_recognition

        if not all_results:
            return jsonify({'error': 'OCR failed to extract any text from the document.'}), 400

        average_confidence, text = process_paddleocr_text(all_results)
        word_count = len(text.split())

        logger.info(f"[OCR] confidence={average_confidence*100:.1f}% words={word_count} time={recognition_time:.1f}s")

        if average_confidence * 100 < MIN_OCR_CONFIDENCE:
            return jsonify({
                'error': f'OCR confidence too low ({average_confidence*100:.1f}%). Please upload a clearer scan.',
                'average_confidence': average_confidence * 100,
                'text': text,
            }), 400

        if word_count < MIN_OCR_WORDS:
            return jsonify({
                'error': f'OCR extracted too few words ({word_count}). The document may be blank or unreadable.',
                'average_confidence': average_confidence * 100,
                'text': text,
            }), 400

        print("\n" + "=" * 60)
        print("[OCR] EXTRACTED TEXT (dual-pass, tab-separated columns):")
        print("=" * 60)
        print(text)
        print("=" * 60 + "\n")

        # ── STEP 2: LLM parsing ───────────────────────────────────────
        start_time_parsing = time.time()
        print("[LLM] Sending OCR text to Groq for structured extraction...")

        parsed_data = parse_with_gemini(text)
        parsing_time = time.time() - start_time_parsing

        if isinstance(parsed_data, str):
            try:
                clean_string = parsed_data.strip().removeprefix('```json').removesuffix('```').strip()
                parsed_data = json.loads(clean_string)
            except json.JSONDecodeError:
                logging.error(f"LLM returned invalid JSON string: {parsed_data}")
                return jsonify({
                    'error': 'Failed to parse LLM output as JSON.',
                    'raw_output': parsed_data
                }), 500

        # ── STEP 2b: Self-verification — fix qty/price math errors ───
        if isinstance(parsed_data, dict):
            parsed_data = verify_and_fix(parsed_data)

        print("\n" + "=" * 60)
        print("[LLM] FINAL PARSED DATA (after verification):")
        print("=" * 60)
        print(json.dumps(parsed_data, indent=4))
        print("=" * 60 + "\n")

        # ── STEP 2c: Filename-based PO hint ──────────────────────────
        # If the filename contains a long digit sequence that looks like
        # a PO, and the LLM extracted a different one, prefer the filename.
        # Works with any PO length (6-10 digits).
        if isinstance(parsed_data, dict):
            filename_po = None
            for key in ('file', 'pdf'):
                f = request.files.get(key)
                if f and f.filename:
                    digit_groups = re.findall(r'\d{6,10}', f.filename)
                    if digit_groups:
                        filename_po = max(digit_groups, key=len)
                        break

            if filename_po:
                llm_po = str(parsed_data.get("po_number", "")).strip()
                llm_digits = re.findall(r'\d+', llm_po)
                llm_po_clean = max(llm_digits, key=len) if llm_digits else ""
                if llm_po_clean != filename_po:
                    parsed_data["po_number"] = filename_po
                    logger.info(f"[PO-FIX] filename={filename_po} overrides LLM={llm_po_clean}")

        response = {
            'text': text,
            'parsed_data': parsed_data,
            'time': {
                'recognition': recognition_time,
                'parsing': parsing_time,
            },
            'average_confidence': average_confidence * 100
        }

        # ── STEP 3: Save to DB if it looks like an invoice ────────────
        if isinstance(parsed_data, dict) and check_if_invoice(parsed_data):
            # Duplicate detection — skip if this exact invoice_number already exists
            inv_num = parsed_data.get("invoice_number", "").strip()
            if inv_num:
                existing = Invoice.query.filter_by(invoice_number=inv_num).first()
                if existing:
                    logger.warning(f"[DUPLICATE] Invoice {inv_num} already exists (id={existing.id})")
                    response['warning'] = f'Invoice {inv_num} was already processed (ID: {existing.id}). Showing results but not saving duplicate.'
                    response['existing_invoice_id'] = existing.id
                    return jsonify(response), 200

            pdf_file = request.files.get('pdf')
            image_file = request.files.get('image')

            pdf_path_string = None
            img_path_string = None

            if pdf_file and pdf_file.filename:
                filename = secure_filename(pdf_file.filename)
                save_path = os.path.join(UPLOAD_FOLDER, f"{int(time.time())}_{filename}")
                pdf_file.save(save_path)
                pdf_path_string = save_path

            if image_file and image_file.filename:
                filename = secure_filename(image_file.filename)
                save_path = os.path.join(UPLOAD_FOLDER, f"{int(time.time())}_{filename}")
                image_file.save(save_path)
                img_path_string = save_path

            invoice_id = add_invoice_to_db(
                parsed_data=parsed_data,
                text=text,
                pdf_file=pdf_path_string,
                img_file=img_path_string,
                average_confidence=average_confidence * 100,
                recognition_time=recognition_time,
                parsing_time=parsing_time,
                ocr_method=ocr_method
            )
            response['invoice_id'] = invoice_id
        else:
            response['warning'] = 'Document was not recognized as a valid invoice. Not saved to database.'

        return jsonify(response), 200

    except Exception as e:
        logging.exception("Fatal error in OCR pipeline:")
        return jsonify({
            'error': 'An internal server error occurred processing the document.',
            'details': str(e)
        }), 500
