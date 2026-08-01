"""
Flask routes for the PaddleOCR extraction endpoint and the invoice-quality
vendor decision.
"""

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app.config import QUALITY_BYPASS_TOKEN
from app.ocr.engine import (
    extract_and_parse, resume_extraction, discard_hold,
    ExtractionError, QualityHold,
)
from app.ocr.quality import QUALITY_ACTIONS
from app.cancel_registry import JobCancelledError

logger = logging.getLogger(__name__)

paddleocr_bp = Blueprint('paddleocr', __name__)


def _iso(ts):
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(
        timespec='seconds').replace('+00:00', 'Z')


def _bypass_requested():
    """The batch harness sets this so a tuning run measures extraction quality
    instead of being blocked by the gate under test."""
    if not QUALITY_BYPASS_TOKEN:
        return False
    return request.headers.get('X-Quality-Bypass', '').strip() == QUALITY_BYPASS_TOKEN


def _success_response(parsed_data, text, meta, invoice_id=None):
    """Shared body for a normal extraction and for a resumed one.

    `status` is always present so callers never have to guess which of the
    three outcomes they received.
    """
    response = {
        'status': 'ok' if meta.get('quality_flag', 'ok') == 'ok'
                  else meta['quality_flag'],
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
    if meta.get('quality'):
        response['quality'] = meta['quality']
    if meta.get('warning'):
        response['warning'] = meta['warning']
    return response


def _hold_response(exc: QualityHold):
    """HTTP 200 with a `status` discriminator rather than a 4xx.

    A hold is not an error - the server did everything right, the document is
    poor. It is also load-bearing that this stays 2xx: the frontend's axios
    instance has no interceptors, so a non-2xx throws into a catch block that
    discards the payload, and the batch harness counts any non-200 as a
    failure.
    """
    return {
        'status': 'quality_hold',
        'assessment_id': exc.assessment_id,
        'expires_at': _iso(exc.expires_at),
        'quality': exc.report,
        'warning': exc.warning,
        'actions': QUALITY_ACTIONS,
    }


@paddleocr_bp.route('/paddleOCR', methods=['POST'])
def process_paddleocr():
    try:
        file = request.files.get('file')
        if file is None:
            return jsonify({'error': 'No valid image or PDF found in request.'}), 400

        # po_number / job_id passthrough stays disabled here, as before.
        invoice_id, parsed_data, text, meta = extract_and_parse(
            file.read(), file.filename,
            quality_decision='proceed' if _bypass_requested() else None,
            source='sync',
        )

        return jsonify(_success_response(parsed_data, text, meta, invoice_id)), 200

    except QualityHold as e:
        # Must be caught before the generic handler below, which would
        # otherwise turn a deliberate pause into a 500.
        return jsonify(_hold_response(e)), 200

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


@paddleocr_bp.route('/paddleOCR/quality-decision', methods=['POST'])
def paddleocr_quality_decision():
    """Record the vendor's answer to a low-quality hold.

    proceed -> replay the cached OCR result and finish extraction (no re-OCR)
    retry   -> drop the cached result; the client returns to the upload step
    """
    payload = request.get_json(silent=True) or {}
    assessment_id = (payload.get('assessment_id') or '').strip()
    decision = (payload.get('decision') or '').strip().lower()

    if not assessment_id:
        return jsonify({'error': 'assessment_id is required.'}), 400
    if decision not in ('proceed', 'retry'):
        return jsonify({
            'error': "decision must be either 'proceed' or 'retry'."
        }), 400

    if decision == 'retry':
        found = discard_hold(assessment_id)
        if not found:
            return jsonify({
                'error': 'This quality assessment has expired. '
                         'Please upload the invoice again.',
                'code': 'ASSESSMENT_EXPIRED',
            }), 410
        return jsonify({
            'status': 'retry_acknowledged',
            'assessment_id': assessment_id,
            'message': 'Upload a new invoice to continue.',
        }), 200

    try:
        invoice_id, parsed_data, text, meta = resume_extraction(assessment_id)
        return jsonify(_success_response(parsed_data, text, meta, invoice_id)), 200

    except JobCancelledError:
        return jsonify({'error': 'Job cancelled by user.'}), 499

    except ExtractionError as e:
        return jsonify({'error': e.message, **e.payload}), e.status_code

    except Exception as e:
        logging.exception("Fatal error resuming a held extraction:")
        return jsonify({
            'error': 'An internal server error occurred processing the document.',
            'details': str(e),
        }), 500
