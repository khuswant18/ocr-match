import os
import json
import time
import logging
import threading
# pyrefly: ignore [missing-import]
from flask import Blueprint, jsonify, request
# pyrefly: ignore [missing-import]
from werkzeug.utils import secure_filename
from paddleocr import PaddleOCR
from app.parsers.llm_parser import parse_with_gemini, verify_and_fix
from app.utils.operations import add_invoice_to_db, check_if_invoice, process_paddleocr_text
from app.utils.utils import load_images_from_request
from app.models import db, Invoice

logger = logging.getLogger(__name__)

MIN_OCR_CONFIDENCE = 40.0
MIN_OCR_WORDS = 10

paddleocr_bp = Blueprint('paddleocr', __name__)

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


def _run_document_ocr(page_variants_list):
    """
    Run OCR over every page variant while holding the predictor lock.
    A single "Tensor holds no memory" failure leaves the shared predictor
    corrupted, so on a RuntimeError we rebuild it once and retry the whole
    document — otherwise every later request would fail until a manual restart.
    """
    global ocr
    for attempt in (1, 2):
        try:
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
            return all_results
        except RuntimeError as e:
            if attempt == 1:
                logger.error(f"[OCR] predictor error, rebuilding and retrying once: {e}")
                ocr = _build_ocr()
                continue
            raise

def _merge_ocr_passes(results_list: list) -> list:
    print(f"\n>>>>>>>> MERGING OCR PASSES ({len(results_list)} passes) >>>>>>>>")
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

    print(f"<<<<<<<< MERGED INTO {len(kept) if kept else 0} DETECTIONS <<<<<<<<\n")
    return [kept] if kept else []


@paddleocr_bp.route('/paddleOCR', methods=['POST'])
def process_paddleocr():
    try:
        page_variants_list = load_images_from_request()
        if not page_variants_list:
            return jsonify({'error': 'No valid image or PDF found in request.'}), 400

        ocr_method = 'PaddleOCR'

        start_time_recognition = time.time()

        # Hold the lock for the whole document so one request owns the predictor
        # start-to-finish (no interleaving with a concurrent OCR request), and
        # self-heal the predictor if a previous call left it corrupted.
        with _ocr_lock:
            all_results = _run_document_ocr(page_variants_list)

        recognition_time = time.time() - start_time_recognition
        print(f"\n>>>>>>>> OCR RECOGNITION COMPLETED IN {recognition_time:.2f} SECONDS >>>>>>>>\n")
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


        if isinstance(parsed_data, dict):
            po_number_override = request.form.get("po_number")
            if po_number_override:
                parsed_data["po_number"] = po_number_override
                
            parsed_data = verify_and_fix(parsed_data, text)

        print("\n" + "=" * 60)
        print("[LLM] FINAL PARSED DATA (after verification):")
        print("=" * 60)
        print(json.dumps(parsed_data, indent=4))
        print("=" * 60 + "\n")

        response = {
            'text': text,
            'parsed_data': parsed_data,
            'time': {
                'recognition': recognition_time,
                'parsing': parsing_time,
            },
            'average_confidence': average_confidence * 100
        }

        if isinstance(parsed_data, dict) and check_if_invoice(parsed_data):

            inv_num = parsed_data.get("invoice_number", "")
            inv_num = inv_num.strip() if isinstance(inv_num, str) else str(inv_num).strip()
            
            po_num = parsed_data.get("po_number", "")
            po_num = po_num.strip() if isinstance(po_num, str) else str(po_num).strip()
            
            supp_name = parsed_data.get("supplier_name", "")
            supp_name = supp_name.strip() if isinstance(supp_name, str) else str(supp_name).strip()

            existings = []
            if po_num:
                existings = Invoice.query.filter_by(po_number=po_num).all()
            elif inv_num:
                existings = Invoice.query.filter_by(invoice_number=inv_num).all()

            if existings:
                for existing in existings:
                    match_type = f"PO {po_num}" if po_num else f"invoice {inv_num}"
                    logger.warning(f"[DUPLICATE REPLACED] Match found for {match_type}. Deleting old invoice (id={existing.id}).")
                    db.session.delete(existing)
                db.session.commit()

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
