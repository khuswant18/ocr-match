from app.models import db, User, UserRole, Invoice, Supplier, Buyer

def get_current_user_service(user_id):
    user = User.query.get(user_id)
    return {
        "name": user.name,
        "email": user.email,
        "role": user.role.value
    } if user else None

def edit_role_service(user_id, role):
    user = User.query.get(user_id)
    user.role = UserRole[role]
    db.session.commit()

def update_user_service(user_id, name, email):
    user = User.query.get(user_id)
    user.name = name
    user.email = email
    db.session.commit()

def delete_invoice_service(invoice_id):
    invoice = Invoice.query.get(invoice_id)
    if not invoice:
        return None

    if invoice.supplier_id:
        supplier = Supplier.query.get(invoice.supplier_id)
        if supplier:
            db.session.delete(supplier)

    if invoice.buyer_id:
        buyer = Buyer.query.get(invoice.buyer_id)
        if buyer:
            db.session.delete(buyer)

    performance = invoice.performance
    if performance:
        db.session.delete(performance)

    db.session.delete(invoice)
    db.session.commit()

    return invoice_id

def update_invoice_service(new_data):
    invoice_id = new_data["id"]
    invoice = Invoice.query.get(invoice_id)
    if not invoice:
        return None

    invoice.invoice_number = new_data.get("invoice_number", invoice.invoice_number)
    invoice.po_number = new_data.get("po_number", invoice.po_number)
    invoice.invoice_date = new_data.get("invoice_date", invoice.invoice_date)
    invoice.due_date = new_data.get("due_date", invoice.due_date)
    invoice.payment_method = new_data.get("payment_method", invoice.payment_method)
    invoice.total_amount = new_data.get("total_amount", invoice.total_amount)
    invoice.cgst = new_data.get("cgst", invoice.cgst)
    invoice.sgst = new_data.get("sgst", invoice.sgst)
    invoice.igst = new_data.get("igst", invoice.igst)
    invoice.bank = new_data.get("bank", invoice.bank)
    invoice.ifsc = new_data.get("ifsc", invoice.ifsc)
    invoice.account_number = new_data.get("account_number", invoice.account_number)

    supplier_data = new_data.get("supplier_data", {})
    if invoice.supplier:
        invoice.supplier.tin = supplier_data.get("TIN", invoice.supplier.tin)
        invoice.supplier.name = supplier_data.get("Name", invoice.supplier.name)
        invoice.supplier.address = supplier_data.get("Address", invoice.supplier.address)
        invoice.supplier.pincode = supplier_data.get("Pincode", invoice.supplier.pincode)
        invoice.supplier.city = supplier_data.get("City", invoice.supplier.city)
        invoice.supplier.state = supplier_data.get("State", invoice.supplier.state)

    buyer_data = new_data.get("buyer_data", {})
    if invoice.buyer:
        invoice.buyer.tin = buyer_data.get("TIN", invoice.buyer.tin)
        invoice.buyer.name = buyer_data.get("Name", invoice.buyer.name)
        invoice.buyer.address = buyer_data.get("Address", invoice.buyer.address)
        invoice.buyer.pincode = buyer_data.get("Pincode", invoice.buyer.pincode)
        invoice.buyer.city = buyer_data.get("City", invoice.buyer.city)
        invoice.buyer.state = buyer_data.get("State", invoice.buyer.state)

    db.session.commit()

    return invoice_id
