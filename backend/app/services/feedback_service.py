"""
Builds few-shot learning context from the correction_log table.

Given a supplier name (or raw OCR text to detect the supplier), returns
a block of text that can be injected into the LLM prompt so it learns
from past human corrections.
"""
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# Max examples to inject per category to keep prompt size reasonable
MAX_PRODUCT_CODE_EXAMPLES = 20
MAX_FIELD_EXAMPLES = 10


def get_few_shot_context(supplier_name: str = "", ocr_text: str = "") -> str:
    """
    Query the correction_log for past corrections relevant to this invoice.
    Returns a formatted string to inject into the LLM prompt, or "" if
    no relevant corrections exist.
    """
    try:
        from app.models import db, CorrectionLog

        # Find the supplier — try exact match first, then partial
        supplier = _resolve_supplier(supplier_name, ocr_text)
        if not supplier:
            return ""

        corrections = CorrectionLog.query.filter(
            CorrectionLog.supplier_name.ilike(f"%{supplier}%")
        ).order_by(CorrectionLog.created_at.desc()).limit(100).all()

        if not corrections:
            return ""

        return _format_corrections(corrections, supplier)

    except Exception as e:
        logger.warning(f"[FEEDBACK] Could not load corrections: {e}")
        return ""


def _resolve_supplier(supplier_name: str, ocr_text: str) -> str:
    """
    Try to identify the supplier. First from the explicit name,
    then by scanning the OCR text for known supplier names from
    past corrections.
    """
    if supplier_name and len(supplier_name) > 2:
        return supplier_name.strip()

    if not ocr_text:
        return ""

    try:
        from app.models import CorrectionLog
        known_suppliers = db.session.query(
            CorrectionLog.supplier_name
        ).distinct().all()

        ocr_upper = ocr_text.upper()
        for (name,) in known_suppliers:
            if name and len(name) > 3 and name.upper() in ocr_upper:
                return name
    except Exception:
        pass

    return ""


def _format_corrections(corrections, supplier: str) -> str:
    """Format corrections into a human-readable block for the LLM prompt."""
    product_code_map = {}
    field_corrections = defaultdict(list)

    for c in corrections:
        if c.correction_type == "product_code" and c.item_description and c.corrected_value:
            desc = c.item_description.strip()
            code = c.corrected_value.strip()
            if desc and code and desc not in product_code_map:
                product_code_map[desc] = code

        elif c.correction_type == "field" and c.field_name and c.corrected_value:
            key = c.field_name
            if len(field_corrections[key]) < MAX_FIELD_EXAMPLES:
                field_corrections[key].append({
                    "from": c.original_value or "",
                    "to": c.corrected_value,
                })

    if not product_code_map and not field_corrections:
        return ""

    lines = [f"\n━━━━ LEARNED CORRECTIONS (from past invoices by {supplier}) ━━━━\n"]

    if product_code_map:
        lines.append("PRODUCT CODE MAPPINGS (use these when you see matching descriptions):")
        for desc, code in list(product_code_map.items())[:MAX_PRODUCT_CODE_EXAMPLES]:
            lines.append(f'  "{desc}" → product_code "{code}"')
        lines.append("")

    for field, edits in field_corrections.items():
        if edits:
            lines.append(f"COMMON {field.upper()} CORRECTIONS:")
            for e in edits:
                lines.append(f'  OCR read "{e["from"]}" → correct value is "{e["to"]}"')
            lines.append("")

    lines.append("Apply these corrections when you see similar patterns in the OCR text below.\n")

    result = "\n".join(lines)
    logger.info(f"[FEEDBACK] Injecting {len(product_code_map)} product codes + "
                f"{sum(len(v) for v in field_corrections.values())} field corrections for {supplier}")
    return result
