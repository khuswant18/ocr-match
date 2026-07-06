import os
import json
import logging
# pyrefly: ignore [missing-import]
import torch
# pyrefly: ignore [missing-import]
from transformers import AutoProcessor, AutoModelForMultimodalLM

from app.parsers.llm_parser import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, _extract_json_payload

logger = logging.getLogger(__name__)

HF_TOKEN = "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"
MODEL_ID = "google/gemma-4-E4B-it"

_processor = None
_model = None

def _load_model():
    global _processor, _model
    if _processor is None or _model is None:
        print(f"Loading multimodal Gemma model {MODEL_ID}...")
        try:
            _processor = AutoProcessor.from_pretrained(MODEL_ID, token=HF_TOKEN)
            _model = AutoModelForMultimodalLM.from_pretrained(
                MODEL_ID,
                token=HF_TOKEN,
                device_map="auto",
                torch_dtype=torch.bfloat16
            )
            print("Multimodal Gemma model loaded successfully.")
        except Exception as e:
            print(f"Failed to load multimodal Gemma model: {e}")
            raise

def parse_with_local_gemma(ocr_text: str, supplier_hint: str = "") -> dict:
    """
    Extract structured invoice data from OCR text using local multimodal Gemma model.
    """
    if not ocr_text or not ocr_text.strip():
        print("Empty OCR text passed to local Gemma parser.")
        return {}

    _load_model()

    feedback_block = ""
    try:
        from app.services.feedback_service import get_few_shot_context
        feedback_block = get_few_shot_context(
            supplier_name=supplier_hint,
            ocr_text=ocr_text,
        )
    except Exception as e:
        print(f"Feedback context unavailable: {e}")

    user_content = USER_PROMPT_TEMPLATE.format(ocr_text=ocr_text)
    if feedback_block:
        user_content = feedback_block + user_content

    combined_prompt = f"{SYSTEM_PROMPT}\n\n{user_content}"
    
    messages = [
        {"role": "user", "content": [{"type": "text", "text": combined_prompt}]},
    ]

    try:
        prompt = _processor.apply_chat_template(
            messages, 
            tokenize=False, 
            add_generation_prompt=True
        )

        inputs = _processor(text=prompt, return_tensors="pt").to(_model.device)

        print("Generating structured data with local Gemma...")
        outputs = _model.generate(
            **inputs,
            max_new_tokens=2048,
            temperature=0.0,
            do_sample=False
        )

        input_length = inputs.input_ids.shape[1]
        generated_tokens = outputs[0][input_length:]
        response_text = _processor.decode(generated_tokens, skip_special_tokens=True)

        print(f"Raw output from local Gemma: {response_text}")

        json_str = _extract_json_payload(response_text)
        return json.loads(json_str)

    except json.JSONDecodeError as e:
        print(f"Local Gemma returned invalid JSON: {e}")
        return {}
    except Exception as e:
        print(f"Failed to generate or parse with local Gemma: {e}")
        return {}
