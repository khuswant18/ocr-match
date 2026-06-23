from datetime import datetime
from app.models import db, Invoice, InvoiceItem


def process_paddleocr_text(result):
    """
    Reconstruct text from PaddleOCR preserving spatial (table) layout.

    Groups text blocks into lines by comparing against the line's MEAN
    y_center (not the last block), preventing chain-drift where adjacent
    invoice rows get merged.
    """
    all_blocks = []
    total_score = 0
    num_words = 0

    for res in result:
        if not res:
            continue
        for line in res:
            bbox = line[0]
            text = line[1][0]
            confidence = line[1][1]

            y_center = (bbox[0][1] + bbox[2][1]) / 2.0
            x_left = bbox[0][0]
            height = abs(bbox[2][1] - bbox[0][1])

            all_blocks.append({
                'text': text.strip(),
                'confidence': confidence,
                'y_center': y_center,
                'x_left': x_left,
                'height': max(height, 1),
            })
            total_score += confidence
            num_words += 1

    if not all_blocks:
        return 0.0, ""

    average_confidence = total_score / num_words

    all_blocks.sort(key=lambda b: b['y_center'])

    avg_height = sum(b['height'] for b in all_blocks) / len(all_blocks)
    line_threshold = avg_height * 0.6

    lines: list[list[dict]] = []
    current_line = [all_blocks[0]]
    current_line_y_sum = all_blocks[0]['y_center']

    for block in all_blocks[1:]:
        line_mean_y = current_line_y_sum / len(current_line)
        if abs(block['y_center'] - line_mean_y) <= line_threshold:
            current_line.append(block)
            current_line_y_sum += block['y_center']
        else:
            lines.append(current_line)
            current_line = [block]
            current_line_y_sum = block['y_center']
    lines.append(current_line)

    text_lines = []
    for line_blocks in lines:
        line_blocks.sort(key=lambda b: b['x_left'])
        line_text = "\t".join(b['text'] for b in line_blocks)
        text_lines.append(line_text)

    text = "\n".join(text_lines)
    print("average_confidence, text",average_confidence, text) 
    return average_confidence, text


def _safe_float(value, default=0.0):
    if value is None or value == "":
        return default
    try:
        clean_val = str(value).replace(',', '').replace('$', '').replace('₱', '').replace('P', '').strip()
        # Handle parenthetical negatives like "(100.00)"
        if clean_val.startswith('(') and clean_val.endswith(')'):
            clean_val = '-' + clean_val[1:-1]
        return float(clean_val)
    except (ValueError, TypeError):
        return default


def add_invoice_to_db(parsed_data, text, pdf_file, img_file, average_confidence, recognition_time, parsing_time, ocr_method):

    financials = parsed_data.get('financials', {})

    net_amount = _safe_float(financials.get('net_amount', financials.get('subtotal')))
    total_amount = _safe_float(financials.get('total_amount'))

    tax_amount = financials.get('tax_amount')
    if tax_amount is None:
        tax_amount = (
            _safe_float(financials.get('cgst'))
            + _safe_float(financials.get('sgst'))
            + _safe_float(financials.get('igst'))
            + _safe_float(financials.get('vat'))
        )
    else:
        tax_amount = _safe_float(tax_amount)

    discount_amount = _safe_float(financials.get('discount_amount', financials.get('discount')))

    # Parse date — support many formats the LLM might return
    date_str = parsed_data.get('invoice_date', '')
    parsed_date = None
    if date_str:
        for fmt in (
            "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y",
            "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
            "%m-%d-%Y", "%Y/%m/%d",
        ):
            try:
                parsed_date = datetime.strptime(date_str.strip(), fmt).date()
                break
            except ValueError:
                continue

    # PO number is used as-is from the parsed data — the corresponding PO
    # and receipt already exist in the system, so no autocorrection is needed.
    po_number = str(parsed_data.get('po_number', '')).strip()

    invoice = Invoice(
        po_number=po_number,
        invoice_number=parsed_data.get('invoice_number', ''),
        invoice_date=parsed_date,
        supplier_name=parsed_data.get('supplier', {}).get('name', ''),
        store_code=parsed_data.get('store_code', ''),
        net_amount=net_amount,
        tax_amount=tax_amount,
        discount_amount=discount_amount,
        total_amount=total_amount,
        status='pending',
        raw_json=parsed_data,
        ocr_text=text,
        pdf_file_path=pdf_file,
        img_file_path=img_file,
        ocr_confidence=average_confidence,
        recognition_time=recognition_time,
        parsing_time=parsing_time,
        ocr_method=ocr_method
    )

    db.session.add(invoice)
    db.session.flush()

    line_items = parsed_data.get('items', parsed_data.get('line_items', []))

    for item in line_items:
        qty = _safe_float(item.get('quantity'))
        u_price = _safe_float(item.get('unit_price'))
        t_price = _safe_float(item.get('total_price', item.get('line_amount')))

        uom = str(item.get('uom', '')).strip()
        product_code = str(item.get('product_code', '')).strip()
        description = str(item.get('description', '')).strip()

        if qty == 0 and u_price == 0 and t_price == 0:
            continue

        inv_item = InvoiceItem(
            invoice_id=invoice.id,
            product_name=description,
            product_code=product_code,
            quantity=qty,
            unit_price=u_price,
            total_price=t_price,
            uom=uom,
            normalized_qty=qty,
        )
        db.session.add(inv_item)

    db.session.commit()
    return invoice.id


def check_if_invoice(parsed_data):
    """Determine if parsed data represents a valid invoice."""
    if not isinstance(parsed_data, dict):
        return False

    if parsed_data.get('invoice_number'):
        return True
    if parsed_data.get('invoice_date'):
        return True

    supplier = parsed_data.get('supplier', {})
    if isinstance(supplier, dict) and (supplier.get('tin') or supplier.get('name')):
        return True

    financials = parsed_data.get('financials', {})
    if isinstance(financials, dict):
        if financials.get('total_amount') or financials.get('subtotal') or financials.get('net_amount'):
            return True

    items = parsed_data.get('items', [])
    if isinstance(items, list) and len(items) > 0:
        return True

    return False
