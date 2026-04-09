from app.models import db, Invoice
from datetime import datetime
from decimal import Decimal, InvalidOperation


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
