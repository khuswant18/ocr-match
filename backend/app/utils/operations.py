import re
from datetime import datetime
from flask import session
from app.models import db, Invoice, InvoiceItem  # Assuming InvoiceItem is here too

def compute_confidence(data):
    total_confidence = 0
    num_confident_words = 0
    num_words = len(data.get('text', []))
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

def _safe_float(value, default=0.0):
    """Helper to safely convert messy OCR strings to floats."""
    if value is None or value == "":
        return default
    try:
        # Strip commas or currency symbols if the OCR caught them
        clean_val = str(value).replace(',', '').replace('$', '').replace('₱', '').strip()
        return float(clean_val)
    except (ValueError, TypeError):
        return default

def _clean_po_number(po_string):
    """Extracts only the digits from a messy PO string like 'VFI-4010510LLB'."""
    if not po_string:
        return ""
    # Looks for a sequence of 6 to 8 digits (adjust if your POs are longer)
    match = re.search(r'\d{6,10}', str(po_string))
    if match:
        return match.group(0)
    return str(po_string).strip()

def add_invoice_to_db(parsed_data, text, pdf_file, img_file, average_confidence, recognition_time, parsing_time, ocr_method):
    
    financials = parsed_data.get('financials', {})
    
    # 1. Map Financials (Safely)
    # The JSON had 'subtotal', but we store it as 'net_amount'
    net_amount = _safe_float(financials.get('net_amount', financials.get('subtotal')))
    total_amount = _safe_float(financials.get('total_amount'))
    
    # If tax isn't explicitly 'tax_amount', try to sum the GSTs from your JSON
    tax_amount = financials.get('tax_amount')
    if tax_amount is None:
        tax_amount = _safe_float(financials.get('cgst')) + _safe_float(financials.get('sgst')) + _safe_float(financials.get('igst'))
    else:
        tax_amount = _safe_float(tax_amount)

    discount_amount = _safe_float(financials.get('discount_amount'))
        
    # 2. Parse Date
    date_str = parsed_data.get('invoice_date', '')
    parsed_date = None
    if date_str:
        # Added %Y-%m-%d in case the LLM pre-formatted it
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                parsed_date = datetime.strptime(date_str.strip(), fmt).date()
                break
            except ValueError:
                continue

    # 3. Clean PO Number to ensure it joins correctly with po_headers
    raw_po = parsed_data.get('po_number', '')
    clean_po = _clean_po_number(raw_po)

    # 4. Create Invoice Header
    invoice = Invoice(
        po_number=clean_po,
        invoice_number=parsed_data.get('invoice_number', ''),
        invoice_date=parsed_date,
        supplier_name=parsed_data.get('supplier', {}).get('name', ''),
        store_code=parsed_data.get('store_code', ''),
        net_amount=net_amount,            # ADDED per new schema
        tax_amount=tax_amount,
        discount_amount=discount_amount,
        total_amount=total_amount,
        status='pending',
        raw_json=parsed_data,

        # --- NEW AUDIT TRAIL FIELDS --- 
        ocr_text=text,
        pdf_file_path=pdf_file,
        img_file_path=img_file,
        ocr_confidence=average_confidence,
        recognition_time=recognition_time,
        parsing_time=parsing_time,
        ocr_method=ocr_method
    )

    db.session.add(invoice)
    db.session.flush() # Flush to get invoice.id

    # 5. Handle Line Items
    # Fallback: check 'items' (from your JSON example) or 'line_items'
    line_items = parsed_data.get('items', parsed_data.get('line_items', []))
    
    for item in line_items:
        qty = _safe_float(item.get('quantity'))
        u_price = _safe_float(item.get('unit_price'))
        t_price = _safe_float(item.get('total_price', item.get('line_amount'))) # fallback for total
        
        # If your OCR manages to extract the unit of measure (e.g. 'case' vs 'kg')
        uom = str(item.get('uom', '')).strip()

        inv_item = InvoiceItem(
            invoice_id=invoice.id,
            product_name=item.get('description', ''),
            product_code=item.get('product_code', ''), # Will likely be empty initially
            quantity=qty,
            unit_price=u_price,
            total_price=t_price,
            uom=uom,
            normalized_qty=qty # Default to qty until your conversion logic runs
        )
        db.session.add(inv_item)

    db.session.commit()

    return invoice.id

def check_if_invoice(parsed_data):
    """Determine if it's an invoice if certain required fields are present."""
    required_fields = ['invoice_number', 'invoice_date']
    for field in required_fields:
        if parsed_data.get(field):
            return True
            
    supplier = parsed_data.get('supplier', {})
    if supplier.get('tin') or supplier.get('name'):
        return True
    
    financials = parsed_data.get('financials', {})
    # Updated to check for subtotal/net_amount as well
    if financials.get('total_amount') or financials.get('subtotal') or financials.get('net_amount'):
        return True

    return False