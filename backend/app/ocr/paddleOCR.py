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
from app.utils.utils import load_images_from_bytes, _is_pdf
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


def extract_and_parse(file_bytes, filename, po_number=None, job_id=None, existing_path=None):
    """
    Run the full OCR + LLM extraction pipeline on raw document bytes and,
    if it is an invoice, persist it. Returns (invoice_id, parsed_data, text, meta).

    This is the single source of truth for extraction. The /paddleOCR HTTP
    route and the background match worker both call it directly (in-process),
    so PaddleOCR is serialized by `_ocr_lock` without any self-HTTP hop.

    Raises JobCancelledError on cancellation and ExtractionError on any
    pipeline failure the caller should surface (bad input, low confidence,
    invalid LLM output, LLM unavailable).
    """
    ocr_method = 'PaddleOCR'

    images = load_images_from_bytes(file_bytes)
    if not images:
        raise ExtractionError('No valid image or PDF found in request.', status_code=400)

    check_cancelled(job_id)

    start_time_recognition = time.time()
    # Hold the lock for the whole document so one caller owns the predictor
    # start-to-finish (no interleaving with a concurrent OCR request), and
    # self-heal the predictor if a previous call left it corrupted.
    with _ocr_lock:
        all_results = _run_document_ocr(images, job_id=job_id)
    recognition_time = time.time() - start_time_recognition

    if not all_results:
        raise ExtractionError('OCR failed to extract any text from the document.', status_code=400)

    average_confidence, text = process_paddleocr_text(all_results)
    word_count = len(text.split())

    if average_confidence * 100 < MIN_OCR_CONFIDENCE:
        raise ExtractionError(
            f'OCR confidence too low ({average_confidence*100:.1f}%). Please upload a clearer scan.',
            status_code=400,
            payload={'average_confidence': average_confidence * 100, 'text': text},
        )

    if word_count < MIN_OCR_WORDS:
        raise ExtractionError(
            f'OCR extracted too few words ({word_count}). The document may be blank or unreadable.',
            status_code=400,
            payload={'average_confidence': average_confidence * 100, 'text': text},
        )

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
            raise ExtractionError(
                'Failed to parse LLM output as JSON.',
                status_code=500,
                payload={'raw_output': parsed_data},
            )

    # OCR succeeded but the LLM returned nothing usable — treat as an explicit
    # failure so the job gets a clear message instead of a misleading
    # "No invoice items extracted" downstream.
    if not parsed_data:
        raise ExtractionError('LLM parsing failed or unavailable. Please retry.', status_code=502)

    check_cancelled(job_id)

    if isinstance(parsed_data, dict):
        if po_number:
            parsed_data["po_number"] = po_number
        parsed_data = verify_and_fix(parsed_data, text)

    print("\n" + "=" * 60)
    print("[LLM] FINAL PARSED DATA (after verification):")
    print("=" * 60)
    print(json.dumps(parsed_data, indent=4))
    print("=" * 60 + "\n")

    meta = {
        'recognition_time': recognition_time,
        'parsing_time': parsing_time,
        'average_confidence': average_confidence * 100,
    }

    invoice_id = None
    if isinstance(parsed_data, dict) and check_if_invoice(parsed_data):
        inv_num = parsed_data.get("invoice_number", "")
        inv_num = inv_num.strip() if isinstance(inv_num, str) else str(inv_num).strip()

        po_num = parsed_data.get("po_number", "")
        po_num = po_num.strip() if isinstance(po_num, str) else str(po_num).strip()

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

        # Persist a copy of the source document for the invoice record. The
        # worker already has the file on disk (existing_path); the HTTP route
        # passes bytes we save here.
        save_path = existing_path
        if not save_path:
            safe_name = secure_filename(filename or 'upload')
            save_path = os.path.join(UPLOAD_FOLDER, f"{int(time.time())}_{safe_name}")
            with open(save_path, 'wb') as out:
                out.write(file_bytes)

        is_pdf = _is_pdf(file_bytes)
        pdf_path_string = save_path if is_pdf else None
        img_path_string = None if is_pdf else save_path

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
    else:
        meta['warning'] = 'Document was not recognized as a valid invoice. Not saved to database.'

    return invoice_id, parsed_data, text, meta


@paddleocr_bp.route('/paddleOCR', methods=['POST'])
def process_paddleocr():
    try:
        # job_id passed by the match worker so we can check cancellation
        job_id = request.form.get('job_id', type=int)
        po_number = request.form.get('po_number')

        file = request.files.get('file')
        if file is None:
            return jsonify({'error': 'No valid image or PDF found in request.'}), 400

        invoice_id, parsed_data, text, meta = extract_and_parse(
            file.read(), file.filename, po_number=po_number, job_id=job_id,
        )

        response = {
            'text': text,
            'parsed_data': parsed_data,
            'time': {
                'recognition': meta['recognition_time'],
                'parsing': meta['parsing_time'],
            },
            'average_confidence': meta['average_confidence'],
        }
        if invoice_id is not None:
            response['invoice_id'] = invoice_id
        if meta.get('warning'):
            response['warning'] = meta['warning']

        return jsonify(response), 200

    except JobCancelledError as e:
        print(f"[OCR] Job cancelled: {e}")
        return jsonify({'error': 'Job cancelled by user.'}), 499

    except ExtractionError as e:
        return jsonify({'error': e.message, **e.payload}), e.status_code

    except Exception as e:
        logging.exception("Fatal error in OCR pipeline:")
        return jsonify({
            'error': 'An internal server error occurred processing the document.',
            'details': str(e)
        }), 500
