CREATE TABLE invoices (
    id INT AUTO_INCREMENT PRIMARY KEY,

    po_number VARCHAR(50),              -- extracted PO
    invoice_number VARCHAR(50),         -- from PDF
    invoice_date DATE,

    supplier_name VARCHAR(255), 
    store_code VARCHAR(20),

    net_amount DECIMAL(12,2),           -- ADDED: Pre-tax amount (Vatable Sales)
    total_amount DECIMAL(12,2),
    tax_amount DECIMAL(12,2),
    discount_amount DECIMAL(12,2),

    status VARCHAR(20) DEFAULT 'pending',  -- pending / matched / mismatch

    raw_json JSON,                     -- full OCR output

    -- OCR Audit Trail
    ocr_text TEXT,
    pdf_file_path VARCHAR(500),
    img_file_path VARCHAR(500),
    ocr_confidence DECIMAL(5, 2),
    recognition_time DECIMAL(8, 4),
    parsing_time DECIMAL(8, 4),
    ocr_method VARCHAR(50),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
); 

CREATE TABLE invoice_items (
    id INT AUTO_INCREMENT PRIMARY KEY,

    invoice_id INT,
  
    product_name TEXT,                 -- Extracted description from PDF
    product_code VARCHAR(50),          -- mapped from PO

    quantity DECIMAL(10,2),           -- Extracted billed quantity
    unit_price DECIMAL(10,2),
    total_price DECIMAL(12,2),

    uom VARCHAR(20),
    normalized_qty DECIMAL(12,2),      -- after conversion

    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
);

CREATE TABLE matching_results (
    id INT AUTO_INCREMENT PRIMARY KEY,

    invoice_id INT,
    invoice_item_id INT,               -- ADDED: To pinpoint exactly which row failed
    po_number VARCHAR(50),
    grn_number VARCHAR(50),            -- ADDED: The specific Voucher/GRN used to verify delivery

    product_code VARCHAR(50),

    po_qty DECIMAL(12,2),
    grn_qty DECIMAL(12,2),
    invoice_qty DECIMAL(12,2),
    qty_variance DECIMAL(12,2),        -- ADDED: (invoice_qty - grn_qty). If > 0, overbilled.
    is_qty_match BOOLEAN,              -- ADDED: True if variance <= 0

    po_price DECIMAL(12,2),
    invoice_price DECIMAL(12,2),
    price_variance DECIMAL(12,4),      -- ADDED: (invoice_price - po_price). If > 0, overpriced.
    is_price_match BOOLEAN,            -- ADDED: True if variance <= 0

    status VARCHAR(20),   -- matched / mismatch
    issue_summary TEXT,   -- e.g., "Overbilled by 2 units and overpriced by $10/unit"

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
    FOREIGN KEY (invoice_item_id) REFERENCES invoice_items(id) ON DELETE CASCADE
); 