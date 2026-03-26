from app.models import db, Invoice


def delete_invoice_service(invoice_id):
    invoice = Invoice.query.get(invoice_id)
    if not invoice:
        return None

    db.session.delete(invoice)
    db.session.commit()

    return invoice_id

def update_invoice_service(new_data):
    invoice_id = new_data.get("id")
    invoice = Invoice.query.get(invoice_id)
    if not invoice:
        return None

    invoice.invoice_number = new_data.get("invoice_number", invoice.invoice_number)
    invoice.po_number = new_data.get("po_number", invoice.po_number)
    invoice.invoice_date = new_data.get("invoice_date", invoice.invoice_date)
    invoice.total_amount = new_data.get("total_amount", invoice.total_amount)
    invoice.supplier_name = new_data.get("supplier_name", invoice.supplier_name)
    invoice.status = new_data.get("status", invoice.status)

    db.session.commit()

    return invoice_id
