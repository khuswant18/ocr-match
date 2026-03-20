from app.models import db, Invoice, User
import base64

def create_entity_data(entity):
    return {
        'TIN': entity.tin,
        'Name': entity.name,
        'Address': entity.address,
        'City': entity.city,
        'State': entity.state,
        'Pincode': entity.pincode,
    } if entity else {}

def serializable_invoices(invoices):
    return [{
        'id': invoice.id,
        'invoice_number': invoice.invoice_number,
        'po_number': invoice.po_number,
        'invoice_date': invoice.invoice_date,
        'due_date': invoice.due_date,
        'payment_method': invoice.payment_method,
        'total_amount': invoice.total_amount,
        'cgst': invoice.cgst,
        'sgst': invoice.sgst,
        'igst': invoice.igst,
        'bank': invoice.bank,
        'ifsc': invoice.ifsc,
        'account_number': invoice.account_number,
        'supplier_data': create_entity_data(invoice.supplier),
        'buyer_data': create_entity_data(invoice.buyer),
        'text': invoice.text,
        'pdf_file': base64.b64encode(invoice.pdf_file).decode() if invoice.pdf_file else None,
        'image_file': base64.b64encode(invoice.image_file).decode() if invoice.image_file else None,
    } for invoice in invoices]

def get_invoices(user_id):
    invoices = Invoice.query.filter_by(user_id=user_id).all()
    return serializable_invoices(invoices)

def get_users():
    users = User.query.all()
    return [{'id': user.id, 'name': user.name, 'email': user.email, 'role': user.role.value} for user in users]

def save_time_other(invoice_id, time_other):
    invoice = Invoice.query.get(invoice_id)
    performance = invoice.performance
    if performance:
        performance.other_time = time_other
        db.session.commit()
        return True
    return False

def get_performance_data(invoice_id):
    invoice = Invoice.query.get(invoice_id)
    performance = invoice.performance
    if performance:
        return {
            'average_confidence': performance.average_confidence,
            'recognition_time': performance.recognition_time,
            'parsing_time': performance.parsing_time,
            'other_time': performance.other_time,
            'ocr_method': performance.ocr_method
        }
    return None
