import json
import logging
import google.generativeai as genai
import re

logger = logging.getLogger(__name__)

# Configure Gemini with the provided API key
genai.configure(api_key="AIzaSyCQiDqS-kdqBJJuHAGW_9RsOJeVTQPzDc4")

def parse_with_gemini(ocr_text: str) -> dict: 
    """ 
    Sends the noisy OCR text to Google Gemini model to extract structured JSON.
    """
    prompt = f"""You are an AI system specialized in extracting structured data from OCR text of Indian invoices. 
The input is noisy OCR output from English invoices. The text may contain spelling mistakes, broken formatting, incorrect alignment, and irrelevant text.

EXTRACTION RULES:
1. Fix OCR errors automatically (e.g. "DELVERY" -> "DELIVERY").
2. Understand Indian keywords: 
   - "inv", "inv no.", "Invoice No", "invoice number" -> invoice_number
   - "Invoice Date", "Date" -> invoice_date 
   - "PO number", "p.o no", "po no", "PO", "po" -> po_number 
   - "Due Date" -> due_date 
   - "Total", "Grand Total" -> total_amount
   - "TIN" -> tin
3. Extract items carefully: group quantity, unit price, total correctly.
4. Normalize numbers: "1,660.00" -> 1660.00 (remove commas, use dot for decimals).
5. Ignore signatures and legal text. 
6. If uncertain, return null or empty string.

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
  "items": [ {{ "description": "", "quantity": 0, "unit_price": 0, "total_price": 0 }} ],
  "financials": {{ "subtotal": 0, "cgst": 0, "sgst": 0, "igst": 0, "total_amount": 0 }}
}}

OCR TEXT:
{ocr_text}
 
FINAL RULE: Return ONLY valid JSON matching the schema. No explanation. 
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
