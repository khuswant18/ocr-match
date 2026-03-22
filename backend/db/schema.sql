CREATE TABLE invoices (
    id INT AUTO_INCREMENT PRIMARY KEY,

    po_number VARCHAR(50),              -- extracted PO
    invoice_number VARCHAR(50),         -- from PDF
    invoice_date DATE,

    supplier_name VARCHAR(255), 
    store_code VARCHAR(20),

    total_amount DECIMAL(12,2),
    tax_amount DECIMAL(12,2),
    discount_amount DECIMAL(12,2),

    status VARCHAR(20) DEFAULT 'pending',  -- pending / matched / mismatch

    raw_json JSON,                     -- full OCR output

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

    FOREIGN KEY (invoice_id) REFERENCES invoices(id)
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

    po_price DECIMAL(12,2),
    invoice_price DECIMAL(12,2),

    status VARCHAR(20),   -- matched / mismatch

    issue TEXT,           -- -- reason (e.g., "Price too high", "Quantity exceeds GRN")

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
    FOREIGN KEY (invoice_item_id) REFERENCES invoice_items(id) ON DELETE CASCADE
); 