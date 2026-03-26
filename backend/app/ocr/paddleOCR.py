import os
import json
import time
import logging
from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename
from paddleocr import PaddleOCR
from app.parsers.llm_parser import parse_with_gemini
from app.utils.operations import add_invoice_to_db, check_if_invoice, process_paddleocr_text
from app.utils.utils import load_image, get_files_from_request

paddleocr_bp = Blueprint('paddleocr', __name__)

UPLOAD_FOLDER = 'uploads/invoices/'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# This loads the model into RAM once when Flask starts, not on every request.
print("[STARTUP] Loading PaddleOCR models into memory...", flush=True)
ocr = PaddleOCR(
    det_model_dir='paddle_models/en_PP-OCRv3_det_infer',
    rec_model_dir='paddle_models/en_PP-OCRv3_rec_infer',
    cls_model_dir='paddle_models/ch_ppocr_mobile_v2.0_cls_infer',
    use_angle_cls=True,
    lang='en'
)
print("[STARTUP] PaddleOCR models loaded successfully.", flush=True)


@paddleocr_bp.route('/paddleOCR', methods=['POST'])
def process_paddleocr():
    try:
        # Load Image
        img = load_image()
        if img is None:
            return jsonify({'error': 'No valid image found in request.'}), 400
            
        ocr_method = 'PaddleOCR'

        # --- STEP 1: OCR EXTRACTION ---
        start_time_recognition = time.time()
        result = ocr.ocr(img, cls=True)
        recognition_time = time.time() - start_time_recognition

        if not result or not result[0]:
            return jsonify({'error': 'OCR failed to extract any text from the image.'}), 400

        average_confidence, text = process_paddleocr_text(result)

        print("\n" + "="*50)
        print("[LOG] TEXT EXTRACTED BY PADDLE OCR (BEFORE GEMINI):")
        print("="*50)
        print(text)
        print("="*50 + "\n")

        # --- STEP 2: GEMINI PARSING ---
        start_time_parsing = time.time()
        print("[LOG] SENDING TEXT TO GEMINI FOR EXTRACTION...")
        
        parsed_data = parse_with_gemini(text)
        parsing_time = time.time() - start_time_parsing

        print("\n" + "="*50)
        print("[LOG] PARSED DATA RETURNED FROM GEMINI:")
        print("="*50)
        
        #ensuring parsed_data is actually a dictionary
        if isinstance(parsed_data, str):
            try:
                # In case Gemini wrapped it in markdown like ```json ... ```
                clean_string = parsed_data.strip().removeprefix('```json').removesuffix('```').strip()
                parsed_data = json.loads(clean_string)
            except json.JSONDecodeError:
                logging.error(f"Gemini returned invalid JSON string: {parsed_data}")
                return jsonify({
                    'error': 'Failed to parse Gemini output as JSON.',
                    'raw_output': parsed_data
                }), 500

        print(json.dumps(parsed_data, indent=4))
        print("="*50 + "\n")

        response = {
            'text': text,
            'parsed_data': parsed_data,
            'time': {
                'recognition': recognition_time,
                'parsing': parsing_time,
            },
            'average_confidence': average_confidence * 100
        } 

        # --- STEP 4: DATABASE INSERTION ---
        if isinstance(parsed_data, dict) and check_if_invoice(parsed_data):
            # Safe to assume parsed_data is a dict here
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
        # CRITICAL FIX 3: Catch-all error handler so the server doesn't crash
        logging.exception("Fatal error occurred during OCR pipeline:")
        return jsonify({
            'error': 'An internal server error occurred processing the document.',
            'details': str(e)
        }), 500