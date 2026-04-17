import logging
from app.models import db, Invoice, CorrectionLog
from datetime import datetime
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)


def delete_invoice_service(invoice_id):
    invoice = Invoice.query.get(invoice_id)
    if not invoice:
        return None

    db.session.delete(invoice)
    db.session.commit()

    return invoice_id


def _parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return value

    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))

    cleaned = str(value).replace("₹", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _log_correction(invoice, field_name, old_val, new_val, correction_type="field"):
    """Record a single field correction to the learning database."""
    old_str = str(old_val) if old_val is not None else ""
    new_str = str(new_val) if new_val is not None else ""
    if old_str == new_str:
        return

    log = CorrectionLog(
        invoice_id=invoice.id,
        supplier_name=invoice.supplier_name or "",
        correction_type=correction_type,
        field_name=field_name,
        original_value=old_str,
        corrected_value=new_str,
    )
    db.session.add(log)
    logger.info(f"[FEEDBACK] {invoice.supplier_name}: {field_name} '{old_str}' → '{new_str}'")


def update_invoice_service(new_data):
    invoice_id = new_data.get("id")
    invoice = Invoice.query.get(invoice_id)
    if not invoice:
        return None, None

    parsed_invoice_date = _parse_date(new_data.get("invoice_date"))
    if new_data.get("invoice_date") not in (None, "") and parsed_invoice_date is None:
        return None, "Invalid invoice_date format"

    parsed_total = _parse_decimal(new_data.get("total_amount"))
    if new_data.get("total_amount") not in (None, "") and parsed_total is None:
        return None, "Invalid total_amount value"

    # Log corrections for every field that changed
    field_map = {
        "invoice_number": invoice.invoice_number,
        "po_number": invoice.po_number,
        "supplier_name": invoice.supplier_name,
        "status": invoice.status,
    }
    for field, old_val in field_map.items():
        new_val = new_data.get(field)
        if new_val is not None and str(new_val) != str(old_val or ""):
            _log_correction(invoice, field, old_val, new_val)

    if parsed_invoice_date and parsed_invoice_date != invoice.invoice_date:
        _log_correction(invoice, "invoice_date", invoice.invoice_date, parsed_invoice_date)

    if parsed_total is not None and parsed_total != invoice.total_amount:
        _log_correction(invoice, "total_amount", invoice.total_amount, parsed_total)

    # Apply the updates
    invoice.invoice_number = new_data.get("invoice_number", invoice.invoice_number)
    invoice.po_number = new_data.get("po_number", invoice.po_number)
    invoice.invoice_date = parsed_invoice_date if parsed_invoice_date is not None else invoice.invoice_date
    invoice.total_amount = parsed_total if parsed_total is not None else invoice.total_amount
    invoice.supplier_name = new_data.get("supplier_name", invoice.supplier_name)
    invoice.status = new_data.get("status", invoice.status)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return None, "Failed to save invoice data"

    return invoice_id, None
