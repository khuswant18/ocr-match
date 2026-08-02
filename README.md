# OCR-Match — Invoice Processing & Three-Way Match Engine

End-to-end invoice automation: extracts structured data from scanned PDF/image invoices using PaddleOCR + LLM parsing (Groq), then reconciles every line item against Purchase Orders and Goods Receipt Notes with semantic vector matching.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [How Product Code Matching Works](#how-product-code-matching-works)
- [Tech Stack](#tech-stack)
- [Database Schema](#database-schema)
- [API Reference](#api-reference)
- [Setup & Installation](#setup--installation)
- [Configuration](#configuration)
- [Workflow](#workflow)

---

## Overview

OCR-Match automates the accounts-payable verification workflow:

1. **Upload** a vendor invoice (PDF or image)
2. **Extract** text with dual-pass PaddleOCR (light + aggressive preprocessing)
3. **Parse** the noisy OCR output into structured JSON via Groq LLM (llama-3.3-70b)
4. **Verify** extracted data: qty×price math check, missing-price inference, PO auto-correction
5. **Store** the invoice with full audit trail (confidence, timing, raw text, file path)
6. **Match** every invoice line item three-ways against the corresponding PO and GRN
7. **Report** quantity and price variances with clear matched / mismatch / unmatched status

---

## Key Features

| Feature | Details |
|---|---|
| PaddleOCR v4 | Dual-pass OCR (light + aggressive preprocessing), IoU-based merge, layout-preserving text reconstruction |
| PDF support | PyMuPDF converts PDFs to 300 DPI images server-side, handles multi-page |
| LLM parsing (Groq) | llama-3.3-70b-versatile with JSON mode, retry + OpenRouter fallback |
| Self-verification | Rule-based post-processing fixes qty/price math errors, infers missing prices from subtotal |
| PO auto-correction | Validates extracted PO against `po_headers` DB table, auto-corrects OCR digit misreads (edit distance ≤2) |
| Filename PO fallback | If filename contains a PO number, it overrides OCR errors |
| Duplicate detection | Prevents the same invoice_number from being saved twice |
| Invoice quality assessment | Scores every upload 0-100 on resolution, blur, skew, cropping, lighting, contrast, noise, readability, completeness and OCR confidence. ≥85 proceeds, 70-84 proceeds with a caution flag, <70 pauses and asks the vendor to re-upload or proceed anyway |
| Three-way match engine | PO qty/price × GRN received qty × Invoice billed qty/price |
| 4-pass product matching | Qdrant vector search → fuzzy string → unique price → price+description combo |
| Conversion factor support | Handles case↔unit conversion (e.g. 5 cases × CF 10 = 50 cans) |
| Structured logging | Timestamped logs for every OCR run, LLM call, and PO correction |
| Fully containerised | Docker Compose: MySQL + Qdrant + Flask + React in one command |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser                              │
│                  React 18 + Material-UI                     │
│                                                             │
│  Upload  →  Preprocess  →  OCR  →  Summary  →  Matching    │
└───────────────────────┬─────────────────────────────────────┘
                        │ HTTP (port 3000)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                   Flask Backend  :4333                      │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Preprocessing│  │  OCR Engine  │  │  Match Engine    │  │
│  │  (OpenCV)    │  │ (PaddleOCR)  │  │ (3-way + Qdrant) │  │
│  └──────────────┘  └──────┬───────┘  └────────┬─────────┘  │
│                           │                   │             │
│                    ┌──────▼───────┐   ┌───────▼──────────┐ │
│                    │ LLM Parser   │   │  Vector Service  │ │
│                    │ (Groq API)   │   │  (FastEmbed ONNX)│ │
│                    └──────┬───────┘   └───────┬──────────┘ │
└───────────────────────────┼───────────────────┼────────────┘
                            │                   │
              ┌─────────────▼──────┐   ┌────────▼───────────┐
              │   MySQL  :3306     │   │  Qdrant  :6333     │
              │                    │   │                     │
              │  invoices          │   │  po_descriptions    │
              │  invoice_items     │   │  (384-dim vectors)  │
              │  matching_results  │   │                     │
              │  po_headers        │   └─────────────────────┘
              │  po_lines          │
              │  pol_grn           │
              └────────────────────┘
```

### Request Flow — Invoice Extraction

```
PDF/Image Upload
     │
     ├─ If PDF → PyMuPDF renders pages at 300 DPI
     │
     ▼
Dual-Pass Image Preprocessing (OpenCV)
  Pass 1: Light CLAHE (for clean/digital PDFs)
  Pass 2: Aggressive CLAHE + sharpen + denoise (for faded scans)
     │
     ▼
PaddleOCR × 2 passes
  → IoU-based merge keeps highest-confidence detection per region
  → Layout reconstruction: group by Y-coordinate, sort by X, tab-separate
     │
     ▼
Invoice Quality Assessment (app/ocr/quality.py) → score 0-100
  → ≥85 proceed · 70-84 proceed with caution flag
  → <70 pause: cache the OCR result and return status "quality_hold"
       so the vendor can "Upload a Better Invoice" or "Proceed Anyway"
       (proceeding resumes from the cache — no second OCR pass)
     │
     ▼
Groq LLM (llama-3.3-70b-versatile, JSON mode)
  → Handles merged lines, orphan rows, OCR noise
  → Returns { invoice_number, po_number, items[], financials{} }
     │
     ▼
verify_and_fix() — rule-based post-processing
  → Fix qty×price math errors
  → Infer missing prices from subtotal gap
  → Clean PO number
     │
     ▼
Filename PO override (if filename has a PO number)
     │
     ▼
PO auto-correction against po_headers DB (edit distance ≤2)
     │
     ▼
Duplicate detection (skip if invoice_number already exists)
     │
     ▼
Save to MySQL (invoices + invoice_items)
```

### Request Flow — Three-Way Match

```
GET /api/match/<po_number>
     │
     ▼
Fetch PO lines   (po_lines table)      → product_code, qty, price, conversion_factor, description
Fetch GRN items  (pol_grn table)       → product_code, received qty, GRN number
Fetch Inv items  (invoice_items table) → product_code (often empty), qty, price, description
     │
     ▼
Product Code Resolution:
  If invoice item has a code → normalize (strip zeros, case) → match to PO
  If no code → label as "unknown_1", "unknown_2", etc.
     │
     ▼
Index PO descriptions into Qdrant (FastEmbed ONNX, cosine similarity)
     │
     ▼
4-Pass Auto-Match for each unknown invoice item:
  Pass 1: Semantic vector search (Qdrant, threshold ≥ 0.40)
  Pass 2: Fuzzy string match (difflib, cutoff 0.35)
  Pass 3: Unique price match (±0.05 tolerance, only if exactly one PO item matches)
  Pass 4: Combined price (±10%) + partial description (≥2 shared words)
     │
     ▼
For each product code present in any source:
  normalized_inv_qty = inv_qty × conversion_factor
  qty_variance   = normalized_inv_qty − grn_qty
  price_variance = inv_price − po_price
  status = matched | mismatch | not_on_po | not_billed | unmatched
     │
     ▼
Save to matching_results table → return JSON to frontend
```

---

## How Product Code Matching Works

Most invoices do NOT print product codes — only product descriptions. The matching engine needs to figure out which invoice item corresponds to which PO line item.

### The Problem

```
Invoice says:  "CHAMPION Hotdog Jumbo 4" 2k/5"    qty=2   price=1520.00
PO database:   code="2738"  desc="CHMPN HDOG JMB 2K/5"  price=1520.00
```

The invoice has no code "2738" — just a description that's spelled differently than the PO.

### The Solution: 4-Pass Auto-Match

| Pass | Method | When it works |
|------|--------|---------------|
| 1 | **Qdrant semantic search** — embeds both descriptions into 384-dim vectors and finds the closest match | Handles abbreviations: "CHMPN HDOG" ↔ "CHAMPION Hotdog" |
| 2 | **Fuzzy string match** (difflib) — character-level similarity | Handles minor OCR typos: "Vianns" ↔ "Vienna" |
| 3 | **Unique price match** — if exactly ONE unmatched PO item has the same price | Works when descriptions are too garbled for text matching |
| 4 | **Price + description combo** — price within 10% AND ≥2 shared words | Last resort before giving up |

Each pass only considers PO items that haven't been matched yet, preventing double-assignment.

### If All 4 Passes Fail

The item stays as `unknown_X` with status `"unmatched"`. The UI shows a dropdown letting the user manually assign a product code:

```
POST /api/match/update-code
{ "invoice_item_id": 42, "product_code": "2738" }
```

Re-running the match then uses the manually assigned code.

---

## Tech Stack

### Backend
| Package | Version | Role |
|---|---|---|
| Flask | 2.3.2 | API server |
| Flask-SQLAlchemy | 3.0.3 | ORM |
| PaddleOCR | 2.7.3 | OCR engine (dual-pass with IoU merge) |
| PaddlePaddle | 2.6.2 | Deep learning runtime for PaddleOCR |
| PyMuPDF | 1.24.4 | PDF → high-res image conversion |
| requests | 2.31.0 | Groq / OpenRouter API calls |
| qdrant-client | 1.9.1 | Vector database client |
| fastembed | 0.3.1 | ONNX embeddings (`BAAI/bge-small-en-v1.5`) |
| opencv-python-headless | 4.7.0.72 | Image preprocessing (CLAHE, denoise, deskew) |
| mysql-connector-python | 8.2.0 | MySQL driver |

### Frontend
| Package | Version | Role |
|---|---|---|
| React | 18.2.0 | UI framework |
| Material-UI | 5.x | Component library |
| Axios | 1.6.0 | HTTP client |
| Chart.js | 4.x | Performance doughnut chart |
| pdfjs-dist | 3.3.122 | PDF rendering in browser |

### Infrastructure
| Service | Image | Port |
|---|---|---|
| MySQL | mysql:8.0 | 3307 (host) → 3306 |
| Qdrant | qdrant/qdrant:latest | 6333 |
| Flask Backend | python:3.10-slim-bullseye | 4333 (host) → 4333 |
| React Frontend | node:latest | 3000 |

---

## Database Schema

### `invoices`
| Column | Type | Description |
|---|---|---|
| id | INT PK | Auto-increment |
| po_number | VARCHAR(50) | Extracted PO number (auto-corrected against DB) |
| invoice_number | VARCHAR(50) | Vendor invoice number |
| invoice_date | DATE | Invoice date |
| supplier_name | VARCHAR(255) | Vendor name |
| store_code | VARCHAR(20) | Store / branch code |
| net_amount | DECIMAL(12,2) | Pre-tax subtotal |
| tax_amount | DECIMAL(12,2) | VAT amount |
| discount_amount | DECIMAL(12,2) | Discount applied |
| total_amount | DECIMAL(12,2) | Final payable amount |
| status | VARCHAR(20) | `pending` / `matched` / `mismatch` |
| raw_json | JSON | Full LLM-parsed invoice JSON |
| ocr_text | TEXT | Raw PaddleOCR text output |
| pdf_file_path | VARCHAR(500) | Stored PDF path |
| img_file_path | VARCHAR(500) | Stored image path |
| ocr_confidence | DECIMAL(5,2) | Average OCR confidence % |
| recognition_time | DECIMAL(8,4) | Seconds for OCR |
| parsing_time | DECIMAL(8,4) | Seconds for LLM parsing |
| ocr_method | VARCHAR(50) | `PaddleOCR` |
| created_at | TIMESTAMP | Auto-set on insert |

### `invoice_items`
| Column | Type | Description |
|---|---|---|
| id | INT PK | |
| invoice_id | INT FK | → invoices.id |
| product_name | TEXT | OCR-extracted description |
| product_code | VARCHAR(50) | Initially empty; assigned during matching |
| quantity | DECIMAL(10,2) | Billed quantity |
| unit_price | DECIMAL(10,4) | Unit price |
| total_price | DECIMAL(12,2) | Line total |
| uom | VARCHAR(20) | Unit of measure (case, pc, kg) |
| normalized_qty | DECIMAL(12,2) | qty × buying_conversion_factor |

### `matching_results`
| Column | Type | Description |
|---|---|---|
| id | INT PK | |
| invoice_id | INT FK | → invoices.id |
| invoice_item_id | INT FK | → invoice_items.id |
| po_number | VARCHAR(50) | |
| grn_number | VARCHAR(50) | GRN reference |
| product_code | VARCHAR(50) | |
| po_qty / grn_qty / invoice_qty | DECIMAL(12,2) | Three-way quantities |
| qty_variance | DECIMAL(12,2) | invoice_qty − grn_qty |
| is_qty_match | BOOLEAN | True if variance ≤ 0 |
| po_price / invoice_price | DECIMAL(12,4) | |
| price_variance | DECIMAL(12,4) | invoice_price − po_price |
| is_price_match | BOOLEAN | True if variance ≤ 0.05 |
| status | VARCHAR(20) | `matched` / `mismatch` / `not_on_po` / `not_billed` / `unmatched` |
| issue_summary | TEXT | Human-readable mismatch description |

---

## API Reference

### OCR

| Method | Endpoint | Description |
|---|---|---|
| POST | `/paddleOCR` | Full pipeline: PDF→OCR→LLM→verify→save. Accepts `file` (image/PDF) + optional `pdf`/`image` for archiving |

### Preprocessing

| Method | Endpoint | Description |
|---|---|---|
| POST | `/grayscale` | Convert image to grayscale |
| POST | `/binarization` | Otsu threshold binarization |
| POST | `/noise_reduction` | NLMeans denoising |
| POST | `/skew_correction` | Auto deskew |
| POST | `/remove_barcodes` | Detect and white-out barcodes |

### Invoices

| Method | Endpoint | Description |
|---|---|---|
| GET | `/get-invoices` | List all invoices with line items |
| POST | `/update-invoice` | Edit invoice fields |
| DELETE | `/delete-invoice` | Delete invoice by ID |
| POST | `/get-performance-data` | Retrieve real OCR timing metrics from DB |

### Three-Way Match

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/match/po-list` | List all available PO numbers |
| GET | `/api/match/<po_number>` | Run three-way match for a PO |
| POST | `/api/match/update-code` | Manually assign a product code to an invoice item |

---

## Setup & Installation

### Prerequisites

| Requirement | Minimum version |
|---|---|
| [Docker Desktop](https://www.docker.com/get-started) | 24.x |
| Docker Compose | v2 (bundled with Docker Desktop) |
| Groq API key | [console.groq.com](https://console.groq.com) |

### Step 1 — Clone

```bash
git clone https://github.com/khuswant18/ocr-match.git
cd ocr-match
```

### Step 2 — Configure API key

Edit `backend/.env`:

```env
SECRET_KEY=change_me_to_a_random_string
SQLALCHEMY_DATABASE_URI=mysql+mysqlconnector://root:root@mysql:3306/invoice_db
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
# Optional fallback
OPENROUTER_API_KEY=your_openrouter_key_here
OPENROUTER_MODEL=qwen/qwen3-next-80b-a3-b-instruct:free
```

### Step 3 — Build and start

```bash
docker compose build --no-cache && docker compose up -d
```

First start downloads PaddleOCR models (~15MB) — subsequent starts are instant.

### Step 4 — Verify

```bash
docker compose ps
```

All 4 services should show `Up`:

| Service | URL |
|---|---|
| React frontend | http://localhost:3000 |
| Flask API | http://localhost:4333 |
| Qdrant dashboard | http://localhost:6333/dashboard |
| MySQL | localhost:3307 (user: root, pass: root) |

### Stopping

```bash
docker compose down          # stop (data preserved)
docker compose down -v       # stop + delete all data
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | **Required.** Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model for invoice parsing |
| `OPENROUTER_API_KEY` | — | Optional fallback LLM provider |
| `OPENROUTER_MODEL` | `qwen/qwen3-next-80b-a3-b-instruct:free` | OpenRouter model |
| `SECRET_KEY` | — | Flask session secret |
| `SQLALCHEMY_DATABASE_URI` | `mysql://root:root@mysql/invoice_db` | Database URL |
| `MYSQL_HOST` | `mysql` | MySQL hostname (set by Docker) |
| `QDRANT_HOST` | `qdrant` | Qdrant hostname |

---

## Workflow

### Invoice Processing

1. Go to **Home** page → **Upload** tab
2. Upload a vendor invoice PDF or image
3. (Optional) Apply preprocessing: Grayscale → Binarize → Denoise → Deskew
4. Click **Run PaddleOCR** — dual-pass OCR + Groq LLM extraction
5. Review extracted data in the **Summary** tab: supplier, buyer, items, totals
6. Invoice is saved to database with status `pending`

### Three-Way Match

1. Go to the **Matching** page
2. Select a PO number from the dropdown
3. Click **Run Match** — the engine:
   - Loads PO lines, GRN receipts, and invoice items from the DB
   - Indexes PO descriptions into Qdrant (semantic vectors)
   - Runs 4-pass auto-matching for items without product codes
   - Computes qty and price variances per product code
   - Assigns status: matched / mismatch / not_on_po / not_billed / unmatched
4. Review results — mismatches are highlighted with issue details
5. Use **Edit Code** dropdown to manually assign product codes if needed, then re-run
