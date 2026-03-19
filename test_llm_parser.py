from pydantic import BaseModel, Field
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMParser:
    def __init__(self, model_mock=None):
        self.model = model_mock

    def parse(self, text: str) -> dict:
        """
        Takes raw noisy OCR text and returns strictly structured data.
        In a real implementation, this would call out to Gemini, Claude, or OpenAI.
        """
        # Simulated LLM interaction
        prompt = f"""
        You are an AI system specialized in extracting structured data from OCR text of invoices.
        The input is noisy OCR output from Slovak/English invoices. Extract the following fields
        using the specified strict JSON schema...
        
        {text}
        """ 
        return {
              "invoice_number": "20230012",
              "issue_date": "15.03.2023",
              "due_date": "29.03.2023",
              "supplier": {
                "name": "Zelovoc s.r.o.",
                "address": "Jozefska 12, 811 06 Bratislava",
                "ico": "12345678",
                "dic": "2020123456",
                "ic_dph": "SK2020123456"
              },
              "buyer": {
                "name": "Local Restaurant",
                "address": "Panska 5, 811 01 Bratislava", 
                "ico": "87654321",
                "dic": "2020987654",
                "ic_dph": "SK2020987654"
              },
              "payment_method": "Prevodom",
              "bank_details": {
                "iban": "SK1202000000001234567890",
                "swift": "SUBASEBV",
                "bank_name": "VUB Banka"
              },
              "items": [
                {
                  "description": "Apples",
                  "quantity": 10.5,
                  "unit_price": 1.20,
                  "total_price": 12.60
                },
                {
                  "description": "Potatoes",
                  "quantity": 25.0,
                  "unit_price": 0.80,
                  "total_price": 20.00
                }
              ],
              "financials": {
                "subtotal": 32.60,
                "vat": 6.52,
                "total": 39.12
              }
        }
