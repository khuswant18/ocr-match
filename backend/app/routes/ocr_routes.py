"""
Flask route for the PaddleOCR extraction endpoint.
"""

import logging
from flask import Blueprint, jsonify, request
from app.ocr.engine import extract_and_parse, ExtractionError
from app.cancel_registry import JobCancelledError

logger = logging.getLogger(__name__)

paddleocr_bp = Blueprint('paddleocr', __name__)


@paddleocr_bp.route('/paddleOCR', methods=['POST'])
def process_paddleocr():
    try:
        # job_id = request.form.get('job_id', type=int)
        # po_number = request.form.get('po_number')

        file = request.files.get('file')
        if file is None:
            return jsonify({'error': 'No valid image or PDF found in request.'}), 400

        response = extract_and_parse(file.read(),file.filename)
        print("response===============================================>",response) 
        # invoice_id, parsed_data, text, meta = extract_and_parse(
        #     file.read(), file.filename, po_number=po_number, job_id=job_id,
        # )
        # print("Parsed data: ", parsed_data)

        # response = {
        #     'text': text,
        #     'parsed_data': parsed_data,
        #     'time': {
        #         'recognition': meta['recognition_time'],
        #         'parsing': meta['parsing_time'],
        #     },
        #     'average_confidence': meta['average_confidence'],
        # }
        # if invoice_id is not None:
        #     response['invoice_id'] = invoice_id
        # if meta.get('warning'):
        #     response['warning'] = meta['warning']

        return jsonify({"message": "TEST VERSION 123"}), 200

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
