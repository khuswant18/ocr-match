import os
import json
import logging
import google.generativeai as genai
import re

logger = logging.getLogger(__name__)

# Configure Gemini with the provided API key
api_key = os.environ.get("GEMINI_API_KEY", "AIzaSyCQiDqS-kdqBJJuHAGW_9RsOJeVTQPzDc4")
if not api_key:
    logger.error("CRITICAL: GEMINI_API_KEY environment variable is missing.")
genai.configure(api_key=api_key)

def parse_with_gemini(ocr_text: str) -> dict: 
    """ 
    Sends the noisy OCR text to Google Gemini model to extract structured JSON.
    """
    prompt = f"""You are an AI system specialized in extracting structured data from OCR text of invoices.
The input is noisy OCR output. It may contain spelling mistakes, broken formatting, incorrect alignment, and irrelevant text.

EXTRACTION RULES:
1. Fix OCR errors automatically (e.g. "DELVERY" -> "DELIVERY", "lnvoice" -> "Invoice").
2. Understand keywords:
   - "inv", "inv no.", "Invoice No", "invoice number" -> invoice_number
   - "Invoice Date", "Date" -> invoice_date
   - "PO number", "p.o no", "po no", "PO", "po" -> po_number (IMPORTANT: extract the EXACT PO number as printed, including all digits)
   - "Due Date" -> due_date
   - "Total", "Grand Total" -> total_amount
   - "TIN", "VAT Reg TIN" -> tin
3. ITEM EXTRACTION — THIS IS CRITICAL:
   a. Extract the FULL product description exactly as printed. Include brand names, sizes, pack info, parenthetical notes like "(Premium Hotdog)".
      DO NOT SKIP items because of special characters like parentheses (), quotes "", or dashes -.
   b. The "quantity" field must be the NUMBER OF CASES/PACKS/UNITS ordered (e.g., 3, 2, 1), NOT the total individual pieces.
      Example: "CHAMPION Hotdog Jumbo 2k/5 .... 3 .... 1,520.00 .... 4,560.00" → quantity=3, unit_price=1520.00, total_price=4560.00
   c. If a "UOM" (unit of measure) column exists, extract it (e.g. "CS", "PC", "KG", "CASE", "BOX", "PACK"). If not present, return "".
   d. If a product/item code column exists (numeric codes like "2738", "2751"), extract it as "product_code". If not present, return "".
4. Normalize numbers: "1,660.00" -> 1660.00 (remove commas, use dot for decimals).
5. Ignore signatures, legal text, and terms & conditions.
6. If uncertain about a field, return null or empty string.

OUTPUT FORMAT (STRICT JSON ONLY):
{{
  "invoice_number": "",
  "po_number": "",
  "invoice_date": "",
  "due_date": "",
  "supplier": {{ "name": "", "address": "", "tin": "" }},
  "buyer": {{ "name": "", "address": "", "tin": "" }},
  "payment_method": "",
  "bank_details": {{ "account_number": "", "ifsc": "", "bank_name": "" }},
  "items": [ {{ "product_code": "", "description": "", "quantity": 0, "uom": "", "unit_price": 0, "total_price": 0 }} ],
  "financials": {{ "subtotal": 0, "cgst": 0, "sgst": 0, "igst": 0, "discount": 0, "total_amount": 0 }}
}}

OCR TEXT:
{ocr_text}

FINAL RULE: Return ONLY valid JSON matching the schema above. No explanation, no markdown, no extra text.
"""

    try:
        model = genai.GenerativeModel('gemini-2.5-pro')
        response = model.generate_content(prompt)
        text_response = response.text

        # Use regex to find JSON block in case there's markdown formatting
        match = re.search(r'```json\n(.*)\n```', text_response, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            # Fallback if no markdown block is used
            json_str = text_response.strip()
            
        parsed_data = json.loads(json_str)
        return parsed_data

    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        # Return an empty structure if it fails
        return {}
