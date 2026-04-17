import importlib
import os
import unittest
from unittest.mock import Mock, patch


def load_parser_module(api_key="test-openrouter-key"):
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": api_key,
            "OPENROUTER_MODEL": "qwen/qwen3-next-80b-a3-b-instruct:free",
            "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1/chat/completions",
        },
        clear=False,
    ):
        from app.parsers import llm_parser

        return importlib.reload(llm_parser)


class LlmParserTests(unittest.TestCase):
    def test_parse_with_gemini_parses_openrouter_response(self):
        parser = load_parser_module()

        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"invoice_number": "INV-123", "items": []}'
                    }
                }
            ]
        }

        with patch("app.parsers.llm_parser.requests.post", return_value=mock_response) as mock_post:
            result = parser.parse_with_gemini("sample invoice text")

        self.assertEqual(result["invoice_number"], "INV-123")
        self.assertEqual(result["items"], [])
        mock_post.assert_called_once()

        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["model"], "qwen/qwen3-next-80b-a3-b-instruct:free")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-openrouter-key")

    def test_parse_with_gemini_strips_json_fence(self):
        parser = load_parser_module()

        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "```json\n{\"total_amount\": 6549.66}\n```"
                    }
                }
            ]
        }

        with patch("app.parsers.llm_parser.requests.post", return_value=mock_response):
            result = parser.parse_with_gemini("sample invoice text")

        self.assertEqual(result["total_amount"], 6549.66)

    def test_parse_with_gemini_returns_empty_dict_when_key_missing(self):
        parser = load_parser_module(api_key="")
        self.assertEqual(parser.parse_with_gemini("sample invoice text"), {})

    def test_verify_and_fix_prefers_stronger_po_and_fills_buyer_tin(self):
        parser = load_parser_module()
        parsed = {
            "po_number": "017736",
            "supplier": {"name": "", "address": "", "tin": "000-065-503-000"},
            "buyer": {"name": "", "address": "", "tin": ""},
            "items": [],
            "financials": {},
        }
        ocr_text = """
        SHIPPING INSTRUCTIONS017736MFL\tS.O.No48129667
        SOLDTO:\tPRINCEPAN CORPORATION
        ADDRESS:\t445-348-464-002\tTERMS 30 days
        VATREG.TIN:000-065-503-00037
        """

        fixed = parser.verify_and_fix(parsed, ocr_text)

        self.assertEqual(fixed["po_number"], "4017736")
        self.assertEqual(fixed["supplier"]["tin"], "000-065-503-000")
        self.assertEqual(fixed["buyer"]["tin"], "445-348-464-002")

    def test_verify_and_fix_handles_noisy_numeric_tokens(self):
        parser = load_parser_module()
        parsed = {
            "items": [
                {
                    "description": "CHAMPION Tocino Rol",
                    "quantity": "2.00 1.00",
                    "uom": "case",
                    "unit_price": "1,731.50",
                    "total_price": "3463.00",
                }
            ],
            "financials": {},
        }

        fixed = parser.verify_and_fix(parsed, "")

        self.assertEqual(fixed["items"][0]["quantity"], 2)
        self.assertEqual(fixed["items"][0]["unit_price"], "1,731.50")

    def test_verify_and_fix_ttn_label_maps_to_tin_for_buyer(self):
        parser = load_parser_module()
        parsed = {
            "supplier": {"name": "", "address": "", "tin": "000-065-503-000"},
            "buyer": {"name": "", "address": "", "tin": ""},
            "items": [],
            "financials": {},
        }
        ocr_text = """
        VIRGINIA FOOD INC VATREG.TIN:000-065-503-00037
        PRINCEPAN CORPORATION
        TTN 445-348-464-002
        """

        fixed = parser.verify_and_fix(parsed, ocr_text)
        self.assertEqual(fixed["buyer"]["tin"], "445-348-464-002")

    def test_verify_and_fix_upgrades_supplier_tin_to_richer_ocr_value(self):
        parser = load_parser_module()
        parsed = {
            "supplier": {"name": "", "address": "", "tin": "000-065-503-000"},
            "buyer": {"name": "", "address": "", "tin": ""},
            "items": [],
            "financials": {},
        }
        ocr_text = """
        VAT REG.TIN:000-065-503-00037 (CHARGE SALES)
        TTN 445-348-464-002
        """

        fixed = parser.verify_and_fix(parsed, ocr_text)
        self.assertEqual(fixed["supplier"]["tin"], "000-065-503-00037")


if __name__ == "__main__":
    unittest.main()