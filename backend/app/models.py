import string
import random
from app.extensions import db

class Invoice(db.Model):
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    po_number = db.Column(db.String(50))
    invoice_number = db.Column(db.String(50))
    invoice_date = db.Column(db.Date)
    supplier_name = db.Column(db.String(255))
    store_code = db.Column(db.String(20))
    
    net_amount = db.Column(db.Numeric(12, 2)) 
    tax_amount = db.Column(db.Numeric(12, 2))
    discount_amount = db.Column(db.Numeric(12, 2))
    total_amount = db.Column(db.Numeric(12, 2))
    
    status = db.Column(db.String(20), default='pending')
    raw_json = db.Column(db.JSON)

    ocr_text = db.Column(db.Text)
    pdf_file_path = db.Column(db.String(500))
    img_file_path = db.Column(db.String(500))
    ocr_confidence = db.Column(db.Numeric(5, 2))
    recognition_time = db.Column(db.Numeric(8, 4))
    parsing_time = db.Column(db.Numeric(8, 4))
    ocr_method = db.Column(db.String(50))

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    items = db.relationship("InvoiceItem", backref="invoice", cascade="all, delete-orphan")

class InvoiceItem(db.Model):
    __tablename__ = "invoice_items"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id', ondelete="CASCADE"))
    product_name = db.Column(db.Text)
    product_code = db.Column(db.String(50))
    quantity = db.Column(db.Numeric(10, 2))
    
    unit_price = db.Column(db.Numeric(10, 4)) 
    total_price = db.Column(db.Numeric(12, 2))
    
    uom = db.Column(db.String(20))
    normalized_qty = db.Column(db.Numeric(12, 2))

class CorrectionLog(db.Model):
    """
    Stores every manual correction a user makes. Used to build
    few-shot examples so the LLM improves over time per supplier.
    """
    __tablename__ = "correction_log"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id', ondelete="CASCADE"), nullable=True)
    supplier_name = db.Column(db.String(255))

    correction_type = db.Column(db.String(50))

    field_name = db.Column(db.String(100))
    original_value = db.Column(db.Text)

    corrected_value = db.Column(db.Text)

    item_description = db.Column(db.Text)

    created_at = db.Column(db.DateTime, server_default=db.func.now())


class MatchingResult(db.Model):
    __tablename__ = "matching_results"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id', ondelete="CASCADE"))
    invoice_item_id = db.Column(db.Integer, db.ForeignKey('invoice_items.id', ondelete="CASCADE"))
    
    po_number = db.Column(db.String(50))
    grn_number = db.Column(db.String(50))
    product_code = db.Column(db.String(50))
    
    po_qty = db.Column(db.Numeric(12, 2))
    grn_qty = db.Column(db.Numeric(12, 2))
    invoice_qty = db.Column(db.Numeric(12, 2))
    qty_variance = db.Column(db.Numeric(12, 2))
    is_qty_match = db.Column(db.Boolean)
    
    po_price = db.Column(db.Numeric(12, 4))
    invoice_price = db.Column(db.Numeric(12, 4))
    price_variance = db.Column(db.Numeric(12, 4))
    is_price_match = db.Column(db.Boolean)
    
    status = db.Column(db.String(20))
    issue_summary = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class MatchJob(db.Model):
    """
    Async match job queue.  Octa (or the UI) enqueues a job via the pipeline API;
    a background worker picks it up, runs the 3-way match, and stores the result.
    """
    __tablename__ = "match_jobs"
    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    po_number     = db.Column(db.String(50), nullable=False, index=True)
    status        = db.Column(db.String(20), default='pending', index=True)
    created_at    = db.Column(db.DateTime, server_default=db.func.now())
    started_at    = db.Column(db.DateTime, nullable=True)
    completed_at  = db.Column(db.DateTime, nullable=True)
    result_json   = db.Column(db.JSON, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    triggered_by  = db.Column(db.String(50), default='api')
    job_type      = db.Column(db.String(30), default='match')  # 'match' or 'extract_and_match'
    file_path     = db.Column(db.String(500), nullable=True)   # invoice file for extract_and_match
    input_json    = db.Column(db.JSON, nullable=True)          # the full PO/GRN envelope (extract_and_match)