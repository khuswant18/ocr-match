from flask import session
from app.models import db, Invoice, User, Performance, Supplier, Buyer

def compute_confidence(data):
    total_confidence = 0
    num_confident_words = 0
    num_words = len(data['text'])
    for i in range(num_words):
        if int(data['conf'][i]) > 0:
            total_confidence += int(data['conf'][i])
            num_confident_words += 1

    return total_confidence / num_confident_words if num_confident_words > 0 else 0


def process_paddleocr_text(result):
    total_score = 0
    num_words = 0
    text = ""
    for res in result:
        for line in res:
            text += line[1][0] + "\n"
            total_score += line[1][1]
            num_words += 1

    average_confidence = total_score / num_words if num_words > 0 else 0
    return average_confidence, text


def add_invoice_to_db(parsed_data, text, pdf_file, img_file, average_confidence, recognition_time, parsing_time, ocr_method):
    user_id = session.get("user_id")

    supplierDict = {}
    buyerDict = {}

    performance = Performance(
        average_confidence=average_confidence,
        recognition_time=recognition_time,
        parsing_time=parsing_time,
        other_time=None,
        ocr_method=ocr_method
    )

    db.session.add(performance)
    db.session.flush()

    supplier_data = parsed_data.get('supplier', {})
    supplier = Supplier(
        tin=supplier_data.get('tin'),
        name=supplier_data.get('name', ''),
        address=supplier_data.get('address', '')
    )
    db.session.add(supplier)
    db.session.flush()

    buyer_data = parsed_data.get('buyer', {})
    buyer = Buyer(
        tin=buyer_data.get('tin'),
        name=buyer_data.get('name', ''),
        address=buyer_data.get('address', '')
    )
    db.session.add(buyer)
    db.session.flush()

    bank_details = parsed_data.get('bank_details', {})
    financials = parsed_data.get('financials', {})

    invoice = Invoice(
        user_id=user_id,
        invoice_number=parsed_data.get('invoice_number', ''),
        po_number=parsed_data.get('po_number', ''),
        invoice_date=parsed_data.get('invoice_date', ''),
        due_date=parsed_data.get('due_date', ''),
        payment_method=parsed_data.get('payment_method', ''),
        total_amount=str(financials.get('total_amount', '')),
        cgst=str(financials.get('cgst', '')),
        sgst=str(financials.get('sgst', '')),
        igst=str(financials.get('igst', '')),
        bank=bank_details.get('bank_name', ''),
        ifsc=bank_details.get('ifsc', ''),
        account_number=bank_details.get('account_number', ''),
        supplier_id=supplier.id if supplier else None,
        buyer_id=buyer.id if buyer else None,
        text=text,
        performance_id=performance.id
    )

    if pdf_file:
        invoice.pdf_file = pdf_file

    if img_file:
        invoice.image_file = img_file

    db.session.add(invoice)
    db.session.commit()

    return invoice.id


def check_if_invoice(parsed_data):
    # Determine if it's an invoice if certain required fields are present
    required_fields = ['invoice_number', 'invoice_date']
    for field in required_fields:
        if parsed_data.get(field):
            return True
            
    supplier = parsed_data.get('supplier', {})
    if supplier.get('tin') or supplier.get('name'):
        return True
    
    financials = parsed_data.get('financials', {})
    if financials.get('total_amount'):
        return True

    return False
