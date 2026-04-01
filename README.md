# OCR-Match — Intelligent Invoice Processing & Three-Way Match Engine

An end-to-end invoice automation platform that extracts structured data from PDF/image invoices using PaddleOCR, corrects OCR noise via Google Gemini, and reconciles every line item against Purchase Orders and Goods Receipt Notes with semantic vector matching.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [File Structure](#file-structure)
- [Database Schema](#database-schema)
- [API Reference](#api-reference)
- [Setup & Installation](#setup--installation)
- [Configuration](#configuration)
- [Workflow](#workflow)

---

## Overview

OCR-Match automates the accounts-payable verification workflow:

1. **Upload** a vendor invoice (PDF or image)
2. **Preprocess** the image (denoise, deskew, binarize, remove barcodes)
3. **Extract** raw text with PaddleOCR and an OCR confidence score
4. **Parse** the noisy OCR output into structured JSON via Google Gemini LLM
5. **Store** the invoice with a full audit trail (confidence, timing, raw text, file path)
6. **Match** every invoice line item three-ways against the corresponding PO and GRN
7. **Report** quantity and price variances with a clear matched / mismatch / not-on-po status

---

## Key Features

| Feature | Details |
|---|---|
| Multi-modal OCR | PaddleOCR v3 (detection + recognition + classification) |
| LLM-assisted parsing | Gemini 2.5 Pro corrects OCR errors and outputs strict JSON |
| Image preprocessing | Grayscale, binarization, NLMeans denoising, skew correction, barcode removal |
| Three-way match engine | PO qty/price × GRN received qty × Invoice billed qty/price |
| Semantic item matching | Qdrant vector DB + FastEmbed ONNX (`BAAI/bge-small-en-v1.5`) replaces fragile string diffing |
| Price-based fallback | If vector search score < threshold, falls back to price proximity matching |
| OCR audit trail | Confidence score, recognition time, parsing time, raw OCR text stored per invoice |
| Edit & reprocess | Manual product-code correction triggers a fresh three-way match |
| History | Full invoice history with edit/delete |
| Fully containerised | Docker Compose spins up all four services in one command |

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
│                   Flask Backend  :5000                      │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Preprocessing│  │  OCR Engine  │  │  Match Engine    │  │
│  │  (OpenCV)    │  │ (PaddleOCR)  │  │ (3-way + Qdrant) │  │
│  └──────────────┘  └──────┬───────┘  └────────┬─────────┘  │
│                           │                   │             │
│                    ┌──────▼───────┐   ┌───────▼──────────┐ │
│                    │ LLM Parser   │   │  Vector Service  │ │
│                    │ (Gemini API) │   │  (FastEmbed ONNX)│ │
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

### Request Flow — Invoice Scan

```
PDF/Image Upload
     │
     ▼
Image Preprocessing (OpenCV)
  grayscale → binarize → denoise → deskew → remove barcodes
     │
     ▼
PaddleOCR  (det + rec + cls models)
  → raw text string + confidence score
     │
     ▼
Google Gemini 2.5 Pro
  → corrects OCR noise, extracts structured JSON
  → { invoice_number, po_number, supplier, buyer, items[], financials{} }
     │
     ▼
MySQL  (invoices + invoice_items tables)
     │
     ▼
HTTP Response → React SummaryCard
```

### Request Flow — Three-Way Match

```
GET /api/match/<po_number>
     │
     ▼
Fetch PO lines   (po_lines table)      → product_code, qty, price, description
Fetch GRN items  (pol_grn table)       → product_code, received qty, GRN number
Fetch Inv items  (invoice_items table) → product_code, normalized qty, unit price
     │
     ▼
Index PO descriptions into Qdrant  (FastEmbed ONNX, cosine similarity)
     │
     ▼
For each unknown invoice item:
  1. Vector search  → best-matching product_code (score ≥ 0.55)
  2. Price fallback → exact price match (tolerance ±0.05)
     │
     ▼
For each product code:
  qty_variance   = (inv_qty × conversion_factor) − grn_qty
  price_variance = inv_unit_price − po_unit_price
  status         = matched | mismatch | not_on_po | not_billed
     │
     ▼
Save to matching_results table
Return flat JSON list → React MatchingPage
```

---

## Tech Stack

### Backend
| Package | Version | Role |
|---|---|---|
| Flask | 2.3.2 | API server |
| Flask-SQLAlchemy | 3.0.3 | ORM |
| PaddleOCR | 2.7.3 | OCR engine |
| PaddlePaddle | 2.6.2 | Deep learning runtime for PaddleOCR |
| google-generativeai | 0.8.3 | Gemini LLM parsing |
| qdrant-client | 1.9.1 | Vector database client |
| fastembed | 0.3.1 | ONNX embeddings (`BAAI/bge-small-en-v1.5`) |
| opencv-python-headless | 4.7.0.72 | Image preprocessing |
| pytesseract | 0.3.10 | Tesseract OCR (secondary engine) |
| mysql-connector-python | 8.2.0 | MySQL driver |
| Pillow | 10.4.0 | Image I/O |

### Frontend
| Package | Version | Role |
|---|---|---|
| React | 18.2.0 | UI framework |
| Material-UI | 5.x | Component library |
| MUI X DataGrid | 5.x | Invoice history table |
| Axios | 1.6.0 | HTTP client |
| Chart.js + react-chartjs-2 | 4.x / 5.x | Performance doughnut chart |
| pdfjs-dist | 3.3.122 | PDF rendering in browser |
| react-router-dom | 6.x | Client-side routing |

### Infrastructure
| Service | Image | Port |
|---|---|---|
| MySQL | mysql:8.0 | 3307 (host) → 3306 |
| Qdrant | qdrant/qdrant:latest | 6333 |
| Flask Backend | python:3.10-slim-bullseye | 5001 (host) → 5000 |
| React Frontend | node:latest | 3000 |

---

## File Structure

```
ocr-match/
│
├── docker-compose.yaml              # Orchestrates all 4 services
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── run.py                       # Flask app entry point
│   ├── mysql_db.py                  # Raw MySQL connector (for match engine)
│   │
│   ├── app/
│   │   ├── __init__.py              # App factory: registers all blueprints
│   │   ├── config.py                # Flask / SQLAlchemy config
│   │   ├── extensions.py            # db, bcrypt, session singletons
│   │   ├── models.py                # ORM models: Invoice, InvoiceItem, MatchingResult
│   │   │
│   │   ├── routes/
│   │   │   ├── main_routes.py       # DELETE /delete-invoice, POST /update-invoice
│   │   │   ├── data_routes.py       # GET /get-invoices, POST /get-performance-data
│   │   │   ├── matching_routes.py   # GET /api/match/<po_number>, POST /api/match/update-code
│   │   │   └── preprocessing.py    # POST /grayscale /binarization /noise_reduction ...
│   │   │
│   │   ├── services/
│   │   │   ├── main_service.py      # delete_invoice, update_invoice
│   │   │   ├── data_service.py      # get_invoices, serialization helpers
│   │   │   ├── preprocessing_service.py  # OpenCV transforms
│   │   │   ├── matching_service.py  # Three-way match engine (core logic)
│   │   │   └── vector_service.py    # Qdrant index_po_items + find_best_match
│   │   │
│   │   ├── ocr/
│   │   │   ├── paddleOCR.py         # PaddleOCR pipeline + Gemini parsing + DB save
│   │   │   └── tesseractOCR.py      # Tesseract fallback pipeline
│   │   │
│   │   ├── parsers/
│   │   │   ├── llm_parser.py        # parse_with_gemini(): raw text → structured JSON
│   │   │   ├── paddleParser.py      # Post-process PaddleOCR output
│   │   │   └── tesseractParser.py   # Post-process Tesseract output
│   │   │
│   │   ├── api/
│   │   │   └── companyAPI.py        # External company data lookup
│   │   │
│   │   └── utils/
│   │       ├── operations.py        # add_invoice_to_db, compute_confidence, clean_po_number
│   │       └── utils.py             # get_uuid, convert_to_base64, load_image
│   │
│   ├── db/
│   │   ├── schema.sql               # Table definitions (auto-run on first MySQL start)
│   │   ├── po-headers-insert-*.sql  # Seed: Purchase Order headers
│   │   ├── po-line-insert-*.sql     # Seed: Purchase Order line items
│   │   ├── poh_invs-insert-*.sql    # Seed: PO–Invoice linkage
│   │   └── pol_grn-insert-*.sql     # Seed: Goods Receipt Notes
│   │
│   ├── paddle_models/               # Pre-trained PaddleOCR model weights
│   │   ├── en_PP-OCRv3_det_infer/   # Text detection
│   │   ├── en_PP-OCRv3_rec_infer/   # Text recognition
│   │   └── ch_ppocr_mobile_v2.0_cls_infer/  # Text orientation classification
│   │
│   ├── tessdata/
│   │   └── slk.traineddata          # Slovak Tesseract language model
│   │
│   └── uploads/
│       └── invoices/                # Uploaded PDF/image files (runtime)
│
└── frontend/
    ├── Dockerfile
    ├── package.json
    │
    ├── public/
    │   ├── index.html
    │   ├── index.css
    │   ├── favicon.png
    │   └── opencv.js                # OpenCV WASM (client-side preview)
    │
    └── src/
        ├── index.js                 # React entry point
        ├── httpRequest.js           # Axios base config
        │
        ├── context/
        │   └── ocr-context.js       # Global state (activePage, image, OCR data, invoiceId)
        │
        ├── styles/
        │   ├── theme.js             # MUI theme (colors, typography)
        │   └── constants.js         # Shared style constants
        │
        ├── pages/
        │   ├── App/                 # Root with router + context provider
        │   ├── HomePage/            # Upload → Preprocess → OCR → Summary workflow
        │   ├── HistoryPage/         # Invoice history with DataGrid
        │   └── MatchingPage/        # Three-way match results table
        │
        └── components/
            ├── AppLayout/           # Page shell (sidebar + content area)
            ├── Navbar/              # Top bar
            ├── SideMenu/            # Navigation links
            │   └── LinkItem/
            ├── Tabbar/              # Step tabs: Upload / Preprocess / OCR / Summary
            ├── UploadCard/          # PDF/image drag-and-drop upload
            ├── PreprocessingCard/   # Image transform controls + preview
            ├── OCRCard/             # OCR trigger + raw text display
            ├── SummaryCard/         # Structured invoice data display
            │   ├── BuyerTable/
            │   ├── SellerTable/
            │   ├── InvoiceDataTable/
            │   └── ItemsTable.js
            ├── InvoiceTable/        # History page DataGrid
            ├── DoughnutChart/       # OCR performance chart
            ├── Card/                # Generic card wrapper
            └── StyledComponents/    # MUI button + input wrappers
```

---

## Database Schema

### `invoices`
Stores one row per processed invoice.

| Column | Type | Description |
|---|---|---|
| id | INT PK | Auto-increment |
| po_number | VARCHAR(50) | Extracted PO number |
| invoice_number | VARCHAR(50) | Vendor invoice number |
| invoice_date | DATE | Invoice date |
| supplier_name | VARCHAR(255) | Vendor name |
| store_code | VARCHAR(20) | Store / branch code |
| net_amount | DECIMAL(12,2) | Pre-tax subtotal |
| tax_amount | DECIMAL(12,2) | GST / VAT amount |
| discount_amount | DECIMAL(12,2) | Discount applied |
| total_amount | DECIMAL(12,2) | Final payable amount |
| status | VARCHAR(20) | `pending` / `matched` / `mismatch` |
| raw_json | JSON | Full Gemini-parsed invoice JSON |
| ocr_text | TEXT | Raw PaddleOCR text output |
| pdf_file_path | VARCHAR(500) | Stored PDF path |
| img_file_path | VARCHAR(500) | Stored image path |
| ocr_confidence | DECIMAL(5,2) | Average OCR confidence % |
| recognition_time | DECIMAL(8,4) | Seconds for OCR recognition |
| parsing_time | DECIMAL(8,4) | Seconds for Gemini parsing |
| ocr_method | VARCHAR(50) | `PaddleOCR` / `Tesseract` |
| created_at | TIMESTAMP | Auto-set on insert |

### `invoice_items`
One row per line item on an invoice.

| Column | Type | Description |
|---|---|---|
| id | INT PK | |
| invoice_id | INT FK | → invoices.id |
| product_name | TEXT | OCR-extracted description |
| product_code | VARCHAR(50) | Matched PO product code |
| quantity | DECIMAL(10,2) | Billed quantity (as-invoiced) |
| unit_price | DECIMAL(10,4) | Unit price (4 decimal precision) |
| total_price | DECIMAL(12,2) | Line total |
| uom | VARCHAR(20) | Unit of measure |
| normalized_qty | DECIMAL(12,2) | qty × buying_conversion_factor |

### `matching_results`
One row per product code per match run.

| Column | Type | Description |
|---|---|---|
| id | INT PK | |
| invoice_id | INT FK | → invoices.id |
| invoice_item_id | INT FK | → invoice_items.id |
| po_number | VARCHAR(50) | |
| grn_number | VARCHAR(50) | Voucher/GRN reference |
| product_code | VARCHAR(50) | |
| po_qty / grn_qty / invoice_qty | DECIMAL(12,2) | Three-way quantities |
| qty_variance | DECIMAL(12,2) | invoice_qty − grn_qty |
| is_qty_match | BOOLEAN | True if variance ≤ 0 |
| po_price / invoice_price | DECIMAL(12,4) | |
| price_variance | DECIMAL(12,4) | invoice_price − po_price |
| is_price_match | BOOLEAN | True if variance ≤ 0.05 |
| status | VARCHAR(20) | `matched` / `mismatch` / `not_on_po` / `not_billed` |
| issue_summary | TEXT | Human-readable mismatch description |
| created_at | TIMESTAMP | |

---

## API Reference

### Preprocessing

| Method | Endpoint | Description |
|---|---|---|
| POST | `/grayscale` | Convert image to grayscale |
| POST | `/binarization` | Otsu threshold binarization |
| POST | `/noise_reduction` | NLMeans denoising |
| POST | `/skew_correction` | Auto deskew via rotation |
| POST | `/remove_barcodes` | Detect and white-out barcodes |

All preprocessing endpoints accept `multipart/form-data` with an `image` field and return `{ image: "<base64 JPEG>" }`.

### OCR

| Method | Endpoint | Description |
|---|---|---|
| POST | `/paddleOCR` | Run full pipeline: OCR → Gemini parse → save to DB |
| POST | `/tesseractOCR` | Run Tesseract pipeline |

### Invoices

| Method | Endpoint | Description |
|---|---|---|
| GET | `/get-invoices` | List all invoices with line items |
| POST | `/update-invoice` | Edit invoice fields |
| DELETE | `/delete-invoice` | Delete invoice by ID |
| POST | `/get-performance-data` | Retrieve OCR timing metrics |

### Three-Way Match

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/match/po-list` | List all available PO numbers |
| GET | `/api/match/<po_number>` | Run three-way match for a PO |
| POST | `/api/match/update-code` | Manually assign a product code to an invoice item |

---

## Setup & Installation

### Prerequisites

| Requirement | Minimum version | Notes |
|---|---|---|
| [Docker Desktop](https://www.docker.com/get-started) | 24.x | Ensure the Docker daemon is running before you start |
| Docker Compose | v2 (bundled with Docker Desktop) | `docker compose` (v2) or `docker-compose` (v1) both work |
| Git | any | For cloning the repo |
| Google Gemini API key | — | Free tier works; [get one here](https://aistudio.google.com/app/apikey) |

> **Windows users:** run all commands in PowerShell or WSL2. Git Bash may have path issues with Docker volume mounts.

---

### Step 1 — Clone the repository

```bash
git clone https://github.com/khuswant18/ocr-match.git
cd ocr-match
```

---

### Step 2 — Configure environment variables

The backend needs a Gemini API key at runtime. The simplest approach is a `.env` file in the **project root** (the same directory as `docker-compose.yaml`). Docker Compose automatically reads this file.

```bash
# In the project root (ocr-match/)
cp .env.example .env        # if an example file exists, otherwise create it manually
```

Create / edit `.env` with the following content:

```env
# Required — your Google Gemini API key
GEMINI_API_KEY=your_gemini_api_key_here

# Optional overrides (defaults shown)
SECRET_KEY=change_me_to_a_random_string
MYSQL_ROOT_PASSWORD=root
MYSQL_DATABASE=invoice_db
```

Then expose `GEMINI_API_KEY` to the backend container by adding it under the `backend` service's `environment` block in `docker-compose.yaml`:

```yaml
backend:
  environment:
    - MYSQL_HOST=mysql
    - GEMINI_API_KEY=${GEMINI_API_KEY}   # reads from .env
```

Alternatively, pass it inline on the command line (no file changes needed):

```bash
GEMINI_API_KEY=your_key_here docker-compose up --build -d
```

> **Never commit your `.env` file.** It is already listed in `.gitignore`.

---

### Step 3 — (Optional) Verify PaddleOCR model weights

The pre-trained model weights must be present at `backend/paddle_models/` before building:

```
backend/paddle_models/
├── en_PP-OCRv3_det_infer/       # text detection
├── en_PP-OCRv3_rec_infer/       # text recognition
└── ch_ppocr_mobile_v2.0_cls_infer/   # orientation classification
```

These are large binary files tracked via Git LFS (or included in the repo). If the directories are empty or missing, pull them before building:

```bash
git lfs pull       # if the repo uses Git LFS
```

---

### Step 4 — Build and start all services

```bash
docker-compose up --build -d
```

What this does:

| Service | Action |
|---|---|
| `mysql` | Pulls MySQL 8.0, creates `invoice_db`, auto-runs all `.sql` files in `backend/db/` (schema + seed data) |
| `qdrant` | Pulls Qdrant vector DB and mounts a persistent volume |
| `backend` | Builds Python 3.10 image, installs all pip packages, pre-downloads the FastEmbed ONNX model (~130 MB), starts Flask on port 5000 |
| `frontend` | Builds Node image, installs npm packages, starts React dev server on port 3000 |

> **First build time:** 5–15 minutes depending on your internet speed. PaddlePaddle (~300 MB) and FastEmbed ONNX (~130 MB) are the large downloads. Subsequent builds are fast (cached layers).

Follow live build logs if you want to monitor progress:

```bash
docker-compose up --build        # without -d, logs stream to your terminal
```

---

### Step 5 — Confirm all containers are healthy

```bash
docker-compose ps
```

Expected output (all services `Up`):

```
NAME                   SERVICE    STATUS              PORTS
invoice-mysql          mysql      Up (healthy)        0.0.0.0:3307->3306/tcp
ocr-match-backend-1    backend    Up                  0.0.0.0:5001->5000/tcp
ocr-match-frontend-1   frontend   Up                  0.0.0.0:3000->3000/tcp
ocr-match-qdrant-1     qdrant     Up                  0.0.0.0:6333->6333/tcp
```

If `mysql` shows `Up (health: starting)`, wait 20–30 seconds and run `docker-compose ps` again — the backend waits for MySQL's healthcheck before starting.

Check backend logs for any startup errors:

```bash
docker-compose logs backend --tail=50
```

---

### Step 6 — Open the application

| Service | URL |
|---|---|
| React frontend | http://localhost:3000 |
| Flask API | http://localhost:5001 |
| Qdrant dashboard | http://localhost:6333/dashboard |
| MySQL (external client) | `localhost:3307`, user `root`, password `root`, database `invoice_db` |

---

### Stopping and cleaning up

```bash
# Stop all containers (data volumes are preserved)
docker-compose down

# Stop and delete all data volumes (full reset — loses all uploaded invoices and match results)
docker-compose down -v

# Rebuild a single service without restarting others
docker-compose up --build backend -d
```

---

### Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `backend` exits immediately | Missing `GEMINI_API_KEY` or MySQL not ready | Check `docker-compose logs backend`; ensure Step 2 is complete |
| `invoice-mysql` stuck at `health: starting` | Slow disk or first-time initialisation | Wait 60 s, re-run `docker-compose ps` |
| Port `3000` or `5001` already in use | Another process is using the port | Stop the conflicting process or change the host port in `docker-compose.yaml` (e.g. `"3001:3000"`) |
| OCR returns empty text | PaddleOCR model weights missing | Verify `backend/paddle_models/` is populated (see Step 3) |
| Vector match never fires | Qdrant container not reachable | Confirm `ocr-match-qdrant-1` is `Up` and `QDRANT_HOST=qdrant` is set in the backend environment |
| `No PO lines found` on match page | Seed SQL files not loaded | Run `docker-compose down -v && docker-compose up --build -d` to re-initialise MySQL from scratch |

---

## Configuration

| Variable | Location | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | `backend/.env` | — | Google Gemini API key (required) |
| `SECRET_KEY` | `backend/.env` | random string | Flask session secret |
| `SQLALCHEMY_DATABASE_URI` | `backend/.env` | mysql://root:root@mysql/invoice_db | SQLAlchemy DB URL |
| `QDRANT_HOST` | docker-compose env | `qdrant` | Qdrant service hostname |
| `QDRANT_PORT` | docker-compose env | `6333` | Qdrant service port |
| `REACT_APP_BACKEND_URL` | `frontend/.env` | `http://localhost:5001` | Backend URL used by React |
| `SIMILARITY_THRESHOLD` | `vector_service.py` | `0.55` | Minimum cosine score for a vector match |

---

## Workflow

### Invoice Processing

```
1. Go to Home page
2. Upload a vendor invoice PDF or image via the Upload tab
3. (Optional) Apply image preprocessing:
      Grayscale → Binarize → Denoise → Deskew → Remove Barcodes
4. Click "Run OCR" — PaddleOCR extracts text, Gemini structures it
5. Review extracted data in the Summary tab:
      Supplier info, Buyer info, Line items, Totals
6. Invoice is saved to the database with status: pending
```

### Three-Way Match

```
1. Go to the Matching page
2. Select a PO number from the dropdown
3. Click "Run Match" — the engine:
      a. Loads PO lines, GRN receipts, and invoice items from DB
      b. Indexes PO descriptions into Qdrant (semantic vectors)
      c. For each unmatched invoice item:
           - Searches Qdrant by description similarity
           - Falls back to price proximity if no vector match
      d. Computes qty_variance and price_variance per product code
      e. Assigns status: matched / mismatch / not_on_po / not_billed
4. Review the results table — mismatches are highlighted with issue details
5. Use "Edit Code" to manually assign a product code if needed, then re-run
```
