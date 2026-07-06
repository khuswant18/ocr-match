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
from app.cancel_registry import check_cancelled, JobCancelledError

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
                check_cancelled(job_id)
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


@paddleocr_bp.route('/paddleOCR', methods=['POST'])
def process_paddleocr():
    try:
        # job_id passed by the match worker so we can check cancellation
        job_id = request.form.get('job_id', type=int)

        images = load_images_from_request()
        if not images:
            return jsonify({'error': 'No valid image or PDF found in request.'}), 400

        ocr_method = 'PaddleOCR'

        check_cancelled(job_id)

        start_time_recognition = time.time()

        # Hold the lock for the whole document so one request owns the predictor
        # start-to-finish (no interleaving with a concurrent OCR request), and
        # self-heal the predictor if a previous call left it corrupted.
        with _ocr_lock:
            all_results = _run_document_ocr(images, job_id=job_id)

        recognition_time = time.time() - start_time_recognition
        if not all_results:
            return jsonify({'error': 'OCR failed to extract any text from the document.'}), 400

        average_confidence, text = process_paddleocr_text(all_results)
        word_count = len(text.split())

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
        print("[OCR] EXTRACTED TEXT:")
        print("=" * 60)
        print(text)
        print("=" * 60 + "\n")

        check_cancelled(job_id)

        start_time_parsing = time.time()

        parsed_data = parse_with_gemini(text, job_id=job_id)
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

        check_cancelled(job_id)

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

    except JobCancelledError as e:
        print(f"[OCR] Job cancelled: {e}")
        return jsonify({'error': 'Job cancelled by user.'}), 499

    except Exception as e:
        logging.exception("Fatal error in OCR pipeline:")
        return jsonify({
            'error': 'An internal server error occurred processing the document.',
            'details': str(e)
        }), 500
