from app.models import db, Invoice
import base64

def serializable_invoices(invoices):
    return [{
        'id': invoice.id,
        'invoice_number': invoice.invoice_number,
        'po_number': invoice.po_number,
        'invoice_date': invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        'total_amount': str(invoice.total_amount) if invoice.total_amount else None,
        'supplier_name': invoice.supplier_name,
        'status': invoice.status,
        'items': [{
            'product_name': item.product_name,
            'product_code': item.product_code,
            'quantity': str(item.quantity) if item.quantity else None,
            'unit_price': str(item.unit_price) if item.unit_price else None,
            'total_price': str(item.total_price) if item.total_price else None,
            'uom': item.uom
        } for item in invoice.items]
    } for invoice in invoices]

def get_invoices(user_id=None):
    invoices = Invoice.query.all()
    return serializable_invoices(invoices)

def save_time_other(invoice_id, time_other):
    return True

def get_performance_data(invoice_id):
    return {
        'average_confidence': 95.0,
        'recognition_time': 5.0,
        'parsing_time': 5.0,
        'other_time': 0.0,
        'ocr_method': 'API'
    }
