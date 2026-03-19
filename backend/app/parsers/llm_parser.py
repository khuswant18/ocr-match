import requests
import json
import logging

logger = logging.getLogger(__name__)

OLLAMA_API_URL = "http://host.docker.internal:11434/api/generate"
# You can change this to 'llama3', 'mistral', 'phi3' depending on what you've pulled locally
OLLAMA_MODEL = "llama3" 

def parse_with_ollama(ocr_text: str) -> dict:
    """
    Sends the noisy OCR text to a local Ollama model to extract structured JSON.
    """
    prompt = f"""You are an AI system specialized in extracting structured data from OCR text of invoices.

The input is noisy OCR output from Slovak/English invoices. The text may contain spelling mistakes, broken formatting, mixed languages, incorrect alignment, and irrelevant text.

EXTRACTION RULES:
1. Fix OCR errors automatically (e.g. "DELVERY" -> "DELIVERY").
2. Understand Slovak keywords: "č. faktúry" -> invoice_number, "dátum vystavenia" -> issue_date, "dátum splatnosti" -> due_date, "spolu / celkom" -> total, "IČO" -> ico, "DIČ / IČ DPH" -> dic.
3. Extract items carefully: group quantity, unit price, total correctly.
4. Normalize numbers: "1 660,00" -> 1660.00 (remove spaces, use dot for decimals).
5. Ignore signatures and legal text.
6. If uncertain, return null.

OUTPUT FORMAT (STRICT JSON ONLY):
{{
  "invoice_number": "",
  "issue_date": "",
  "due_date": "",
  "supplier": {{ "name": "", "address": "", "ico": "", "dic": "", "ic_dph": "" }},
  "buyer": {{ "name": "", "address": "", "ico": "", "dic": "", "ic_dph": "" }},
  "payment_method": "",
  "bank_details": {{ "iban": "", "swift": "", "bank_name": "" }},
  "items": [ {{ "description": "", "quantity": 0, "unit_price": 0, "total_price": 0 }} ],
  "financials": {{ "subtotal": 0, "vat": 0, "total": 0 }}
}}

OCR TEXT:
{ocr_text}

FINAL RULE: Return ONLY valid JSON matching the schema. No explanation. 
"""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.0
        }
    }

    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=120)
        response.raise_for_status()
        
        result_json = response.json()
        model_response = result_json.get("response", "{}")
        
        # Parse the JSON string returned by the model
        parsed_data = json.loads(model_response)
        return parsed_data

    except Exception as e:
        logger.error(f"Error calling Ollama API: {{e}}")
        # Return an empty structure if it fails
        return {}

