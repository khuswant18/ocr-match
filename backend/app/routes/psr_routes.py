"""
API routes for PSR (handwritten Sales Invoice) extraction + amount matching.
Synchronous, PaddleOCR-only — no worker/queue, no LLM.
"""
import logging
from flask import Blueprint, jsonify, request

from app.config import MAX_UPLOAD_BYTES
from app.ocr.paddleOCR import ExtractionError

logger = logging.getLogger(__name__)

psr_bp = Blueprint('psr', __name__)


@psr_bp.route('/api/psr/extract-and-match', methods=['POST'])
def psr_extract_and_match():
    """Upload a PSR image/PDF, OCR the total, and match it against the invoice data by invoice number (file name as fallback)."""
    from app.services.psr_service import run_psr_extract_and_match

    file = request.files.get('file') or request.files.get('image') or request.files.get('pdf')
    if not file or not file.filename:
        return jsonify({'error': 'No valid image or PDF found in request.'}), 400

    # Size guard at the API boundary.
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_UPLOAD_BYTES:
        return jsonify({'error': f'File too large ({size} bytes). Max is {MAX_UPLOAD_BYTES}.'}), 400

    # Allow linking a renamed upload back to its CSV row.
    override_name = request.form.get('file_name')

    try:
        result = run_psr_extract_and_match(file.read(), file.filename, override_name)
        return jsonify(result), 200
    except ExtractionError as e:
        return jsonify({'error': e.message, **e.payload}), e.status_code
    except Exception:
        logger.exception('Fatal error in PSR pipeline:')
        return jsonify({'error': 'An internal server error occurred.'}), 500
