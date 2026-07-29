# Detailed Analysis of Every Function

This document provides an analysis of every function in the backend application, based on their docstrings and comments.

## File: `config.py`

### Function: `_env_int`

**Description / Analysis:**
Read an int from the environment, falling back to `default` if unset/invalid.

---

## File: `__init__.py`

### Function: `_setup_logging`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `create_app`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `register_blueprints`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

## File: `cancel_registry.py`

### Function: `register`

**Description / Analysis:**
Create and store a cancel event for a job. Returns the event.

### Function: `unregister`

**Description / Analysis:**
Remove a job's cancel event (call after job finishes).

### Function: `cancel_job`

**Description / Analysis:**
Cancel a specific job. Returns True if the job was found.

### Function: `cancel_all`

**Description / Analysis:**
Cancel every running job AND set the global kill switch.
Returns the number of jobs signalled.

### Function: `reset_cancel_all`

**Description / Analysis:**
Clear the global kill switch (called when the worker picks up the next job).

### Function: `check_cancelled`

**Description / Analysis:**
Call this at checkpoints inside long-running code.
Raises JobCancelledError if this job (or all jobs) should stop.

### Function: `active_job_ids`

**Description / Analysis:**
Return list of currently registered (running) job IDs.

---

## File: `parsers/llm_parser.py`

### Function: `_groq_api_key`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_groq_model`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_openrouter_api_key`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_openrouter_model`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_extract_json_payload`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `verify_and_fix`

**Description / Analysis:**
Rule-based fixes using only arithmetic — no domain assumptions.

### Function: `_to_float`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_extract_tins_with_context`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_tin_digits`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_is_same_tin`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_prefer_richer_tin`

**Description / Analysis:**
Return the TIN variant with more digits when both represent the same TIN.

### Function: `_pick_best_po_from_ocr`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_repair_missing_po_leading_digit`

**Description / Analysis:**
Some OCR outputs drop the leading digit in shipping-instructions PO values,
e.g. "017736" instead of "4017736".

### Function: `_apply_ocr_field_fallbacks`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_extract_item_section`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_extract_price_candidates_from_item_section`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_rebalance_item_prices_from_ocr`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_desc_tokens`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_line_match_score`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_find_best_item_line_index`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_extract_qty_tokens`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_fix_cross_line_item_bundle_swap`

**Description / Analysis:**
Fix common OCR row-merge pattern where one item's description appears on
a previous line, while two numeric bundles appear on the next line,
causing adjacent items to get swapped qty/price/total bundles.

### Function: `_call_groq`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_call_openrouter`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `parse_with_gemini`

**Description / Analysis:**
Extract structured invoice data from OCR text using an LLM.
Injects few-shot examples from past corrections for the same supplier.

### Function: `_dfs`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

## File: `parsers/layoutlm_parser.py`

### Function: `_ensure_loaded`

**Description / Analysis:**
Load the model + processor exactly once (thread-safe).

### Function: `predict_labels`

**Description / Analysis:**
Run LayoutLMv3 inference on a single page.

Args:
    image:  PIL RGB image of the page.
    words:  List of OCR word strings.
    boxes:  List of [x0, y0, x1, y1] normalised to 0–1000.

Returns:
    List of (word, label) tuples — one per input word.

### Function: `_set_nested`

**Description / Analysis:**
Set a value in a nested dict using a path tuple, appending if already set.

### Function: `extract_fields`

**Description / Analysis:**
Run LayoutLMv3 and return a structured dict matching the LLM parser schema.

Returns a dict like:
{
    "invoice_number": "...",
    "po_number": "...",
    "invoice_date": "...",
    "supplier": {"name": "...", "address": "...", "tin": "..."},
    "buyer": {"name": "...", "address": "...", "tin": "..."},
    "financials": {"subtotal": ..., "total_amount": ..., "discount": ...},
    "_layoutlm_used": True,
    "_item_words": [{"word": "...", "label": "...", "box": [...]}],
}

The `_item_words` key contains raw per-word item labels for downstream
grouping or for the LLM to use as hints.

### Function: `extract_fields_multi_page`

**Description / Analysis:**
Run LayoutLMv3 across multiple pages and merge results.

Each argument is a list (one element per page).

---

## File: `ocr/engine.py`

### Function: `_build_ocr`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_extract_words_and_boxes`

**Description / Analysis:**
page_words:  list of list[str]         — one list of words per page
page_boxes:  list of list[[x0,y0,x1,y1]] — normalised to 0-1000
page_images: list of PIL.Image.Image   — RGB images per page

### Function: `_merge_layoutlm_and_llm`

**Description / Analysis:**
Merge LayoutLMv3 header fields with LLM parsed data.
LayoutLMv3 wins for header/footer fields it confidently extracted.
LLM wins for line items and any fields LayoutLMv3 missed.

### Function: `_run_document_ocr`

**Description / Analysis:**
Run OCR over every page image while holding the predictor lock.
A single "Tensor holds no memory" failure leaves the shared predictor
corrupted, so on a RuntimeError we rebuild it once and retry the whole
document — otherwise every later request would fail until a manual restart.

### Function: `extract_and_parse`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `__init__`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

## File: `utils/operations.py`

### Function: `process_paddleocr_text`

**Description / Analysis:**
Process PaddleOCR result to extract text and calculate statistics.

### Function: `_safe_float`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `add_invoice_to_db`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `check_if_invoice`

**Description / Analysis:**
Determine if parsed data represents a valid invoice.

---

## File: `utils/utils.py`

### Function: `convert_to_base64`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_is_pdf`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `pdf_to_images`

**Description / Analysis:**
Convert every page of a PDF to a high-resolution RGB numpy array.

### Function: `preprocess_for_ocr`

**Description / Analysis:**
Return a single enhanced image for OCR (light CLAHE).

### Function: `load_images_from_bytes`

**Description / Analysis:**
Turn raw uploaded file bytes (PDF or image) into a flat list of
preprocessed images (one per page), ready for OCR. Returns None if the
bytes are empty or cannot be decoded.

### Function: `load_images_from_request`

**Description / Analysis:**
Read the uploaded file from the Flask request and return a flat list
of preprocessed images (one per page), ready for OCR.

### Function: `load_image`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

## File: `workers/psr_worker.py`

### Function: `_cancel_key`

**Description / Analysis:**
Namespace PSR job ids in the shared cancel registry so they never collide
with MatchJob ids (both tables autoincrement independently).

### Function: `_reap_orphaned_jobs`

**Description / Analysis:**
On startup, fail any job still 'running' — the previous process died
mid-job and it can never resume (jobs run in-process).

### Function: `_process_one_job`

**Description / Analysis:**
Claim the oldest pending PSR job, run it, store the result.
Returns True if a job was processed, False if the queue was empty.

### Function: `_worker_loop`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `start_psr_worker`

**Description / Analysis:**
Launch the PSR worker as a daemon thread. Called once at app startup.

---

## File: `workers/match_worker.py`

### Function: `_reap_orphaned_jobs`

**Description / Analysis:**
On startup, mark any job still 'running' as failed. Jobs run in-process,
so a 'running' row means the previous process died mid-job — it can never
resume. This is the safety valve that replaced the old 300s HTTP timeout.

### Function: `_process_one_job`

**Description / Analysis:**
Claim the oldest pending job, execute it, and store the result.
Returns True if a job was processed, False if the queue was empty.

OCR runs in-process via `extract_and_parse` (serialized by the OCR lock),
so there is no self-HTTP call and no artificial client timeout. Transient
failures (LLM temporarily unavailable, network) are retried up to
WORKER_JOB_MAX_RETRIES times; permanent failures are not.

### Function: `_worker_loop`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `start_match_worker`

**Description / Analysis:**
Launch the worker as a daemon thread.
Called once during Flask app initialization.

### Function: `_is_transient`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

## File: `routes/data_routes.py`

### Function: `get_invoices_route`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `get_performance_data_route`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

## File: `routes/matching_routes.py`

### Function: `update_item_code`

**Description / Analysis:**
Manual match: update an invoice item's product code and log the correction.

### Function: `get_po_list`

**Description / Analysis:**
Return list of available PO numbers.

### Function: `run_match`

**Description / Analysis:**
Run three-way match for a PO number.

---

## File: `routes/ocr_routes.py`

### Function: `process_paddleocr`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

## File: `routes/pipeline_routes.py`

### Function: `_is_number`

**Description / Analysis:**
True if val is (or coerces to) a number — tolerates '1,234.5'.

### Function: `_looks_like_pdf_or_image`

**Description / Analysis:**
Cheap content sniff so we reject non-PDF/non-image uploads at the door.

### Function: `extract_and_match`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_clean_raw_invoice`

**Description / Analysis:**
As-extracted invoice lines, trimmed to the readable fields.

### Function: `_clean_raw_po`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_clean_raw_grn`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_build_desc_lookup`

**Description / Analysis:**
Map product_code -> description, preferring the invoice's own wording
(PO description is only a fallback for lines with no invoice, e.g. not_billed).

### Function: `_format_match_result`

**Description / Analysis:**
Turn the raw matcher output into a clean, grouped structure:
a `summary` (status counts + total variances) and a list of `items`
with quantity/price grouped per product. Returns {"summary", "items"}.

### Function: `get_job_status`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `list_jobs`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `cancel_job`

**Description / Analysis:**
Cancel a specific running job by ID.

### Function: `cancel_all_jobs`

**Description / Analysis:**
Cancel ALL running and pending jobs immediately.

---

## File: `routes/preprocessing_routes.py`

### Function: `process_image`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `grayscale`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `binarization`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `noise_reduction`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `skew_correction`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `remove_barcodes`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

## File: `routes/psr_routes.py`

### Function: `_looks_like_pdf_or_image`

**Description / Analysis:**
Cheap content sniff so we reject non-PDF/non-image uploads at the door.

### Function: `psr_extract_and_match`

**Description / Analysis:**
Enqueue a PSR extraction+match job. Returns 202 with a job_id to poll.

### Function: `_format_psr_result`

**Description / Analysis:**
Shape the worker's raw result into a clean, grouped API response.

- `ocr_data`     : what was read from the uploaded document (OCR side).
- `raw_data`     : the matched invoice record it reconciles against, or null.
- `match_summary`: the field-by-field comparison + outcome.

### Function: `get_psr_job`

**Description / Analysis:**
Poll a PSR job's status; includes the reconciliation result when completed.

Pass ?debug=1 to also include diagnostics (raw OCR text + candidate lists).

### Function: `list_psr_jobs`

**Description / Analysis:**
List recent PSR jobs (optionally filtered by status).

### Function: `cancel_psr_job`

**Description / Analysis:**
Cancel a pending or running PSR job.

---

## File: `routes/main_routes.py`

### Function: `delete_invoice`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `update_invoice`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

## File: `services/vector_service.py`

### Function: `_get_client`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_normalize`

**Description / Analysis:**
Normalise a product description before embedding or token comparison.

Steps:
  1. Lowercase
  2. Extract parenthetical hints like "(Premium Hotdog)" and prepend them
  3. Replace hyphens/slashes/quotes with spaces
  4. Strip weight/packaging patterns: "1kg", "2k/5", "4.52k", "6s", etc.
  5. Strip all remaining non-alpha characters
  6. Expand brand aliases ("Happy Booster" → inject "virginia premium")
  7. Expand known abbreviations (HDOG → hotdog, PRM → premium, etc.)
  8. Remove packaging noise words (LDLD, LADLAD)
  9. Deduplicate tokens while preserving order
 10. Collapse whitespace

### Function: `_token_overlap`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_combined_score`

**Description / Analysis:**
Weighted combination of semantic vector score and token overlap.

### Function: `index_po_items`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `delete_collection`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `find_best_match`

**Description / Analysis:**
Convenience wrapper — returns the single best match or None.

### Function: `find_ranked_candidates`

**Description / Analysis:**
Return a ranked list of (product_code, combined_score) whose score >= threshold.

Steps:
  1. Normalise inv_desc.
  2. Query Qdrant for top-K candidates by pure vector similarity.
  3. Rerank each candidate using combined (vector + token) score.
  4. Return all candidates above threshold, sorted best-first.

---

## File: `services/data_service.py`

### Function: `serializable_invoices`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `get_invoices`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `get_performance_data`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

## File: `services/matching_service.py`

### Function: `_to_num`

**Description / Analysis:**
Best-effort float coercion from external/JSON input — never raises.
Tolerates thousands separators (e.g. '1,234.50') and returns `default`
for None/blank/garbage.

### Function: `_fetch_po_items`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_fetch_grn_items`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_fetch_invoice_items`

**Description / Analysis:**
Fetch ALL invoice items across ALL invoices for a PO (multi-invoice support).
A PO can have several partial invoices — quantities are accumulated per product_code.
Each product_code entry also carries an `invoice_lines` list so the caller can
save one matching_results row per invoice line for a full audit trail.

### Function: `_po_items_from_lines`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_grn_items_from_lines`

**Description / Analysis:**
Replicates the old SQL: GROUP BY product_code, SUM(vo_tot_qty), MAX(vo_trans_no).

### Function: `_inv_items_from_ocr`

**Description / Analysis:**
Same shape _fetch_invoice_items returned (qty/price/desc/invoice_lines), but
sourced from the OCR result instead of the DB.  `quantity` here is RAW — the
matcher applies the conversion_factor — and there are no per-line DB ids.

### Function: `_auto_match`

**Description / Analysis:**
Resolve invoice lines whose product_code didn't map to a PO line
("unknown_*") onto a PO code, in place. Uses vector search, fuzzy
description match and price heuristics — no DB access.

### Function: `_build_ui_results`

**Description / Analysis:**
Compare PO / GRN / invoice per product_code and return the flat UI rows.
Pure — no DB access. The legacy SQL path persists from these rows separately.

### Function: `_persist_matching_results`

**Description / Analysis:**
Persist UI rows to matching_results — one row per invoice line.

### Function: `run_three_way_match`

**Description / Analysis:**
Executes the 3-Way Match against the DB (legacy path used by /api/pipeline/match),
saves exact variances to the database, and returns a clean flat list for the UI.

### Function: `run_match_from_payload`

**Description / Analysis:**
3-Way Match with PO/GRN supplied as JSON (raw SQL-column rows) and the invoice
sourced from the OCR result. Fully in memory — no DB reads or writes.

`job_id` (optional) enables cancellation: checkpoints raise JobCancelledError
if the user cancels while matching is in progress.

### Function: `get_po_list`

**Description / Analysis:**
Return list of available PO numbers from po_headers UNION invoices.

### Function: `get_po_items`

**Description / Analysis:**
Returns the specific line items ordered for a given PO Number.

### Function: `update_invoice_item_code`

**Description / Analysis:**
Updates the product_code of an invoice item, effectively manual matching it.

---

## File: `services/preprocessing_service.py`

### Function: `apply_grayscale`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `apply_binarization`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `apply_noise_reduction`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `apply_skew_correction`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `apply_remove_barcodes`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

## File: `services/feedback_service.py`

### Function: `get_few_shot_context`

**Description / Analysis:**
Query the correction_log for past corrections relevant to this invoice.
Returns a formatted string to inject into the LLM prompt, or "" if
no relevant corrections exist.

### Function: `_resolve_supplier`

**Description / Analysis:**
Try to identify the supplier. First from the explicit name,
then by scanning the OCR text for known supplier names from
past corrections.

### Function: `_format_corrections`

**Description / Analysis:**
Format corrections into a human-readable block for the LLM prompt.

---

## File: `services/main_service.py`

### Function: `delete_invoice_service`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_parse_date`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_parse_decimal`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_log_correction`

**Description / Analysis:**
Record a single field correction to the learning database.

### Function: `update_invoice_service`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

## File: `services/psr_service.py`

### Function: `_resolve_source`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_recover_file_name`

**Description / Analysis:**
Pick the original document filename from a CSV row's tokens.

The `file_name` column sits *after* `invoice_remarks`, whose malformed
embedded JSON shifts later columns, so we can't trust its index. Instead we
scan for a filename-shaped token, preferring the original over the
`<uuid>-<epoch>.<ext>` stored name.

### Function: `_load_csv_records`

**Description / Analysis:**
Parse the invoice CSV into records exposing `_NEEDED_COLUMNS`.

Robust to the fixture's malformed `invoice_remarks` (unescaped inner quotes
in embedded JSON): the columns we need are all left of that field, read by
fixed header index, and `file_name` is recovered from the row's tokens.

### Function: `load_invoice_records`

**Description / Analysis:**
Return the invoice records as a list of dicts, each exposing at least
`file_name` and `invoice_amount`.

CSV -> JSON swap seam: reads .json (a list, or {"records": [...]}) or, by
default, the CSV via the stdlib csv module (no pandas dependency).

### Function: `normalize_inline_records`

**Description / Analysis:**
Map record(s) sent in the request to the canonical schema used by matching.

Accepts a single object or a list, and tolerant key names
(filename/pdf_name -> file_name, amount -> invoice_amount, etc.). Returns a
list (possibly empty), or None if nothing usable was provided.

### Function: `find_invoice_records`

**Description / Analysis:**
All records whose `file_name` matches `filename`'s basename (case-insensitive).

### Function: `_norm_invnum`

**Description / Analysis:**
Normalize an invoice number for comparison: digits only, no leading zeros.

CSV stores "001495" / "0000235"; the OCR reads "N001495" / "No 1666". Compare
as ints so leading-zero differences don't matter. Returns None if no digits.

### Function: `extract_invoice_numbers`

**Description / Analysis:**
Normalized invoice-number candidates read from the document's "No." stamp.

### Function: `extract_invoice_date`

**Description / Analysis:**
Best-effort document date from OCR text; None if none is readable.

Prefers a date on a line mentioning "date" (skipping printed boilerplate like
permit "Date Issued" lines), else the first plausible date on the page.

### Function: `find_by_invoice_number`

**Description / Analysis:**
Link by the printed invoice number.

Returns (matched_records, matched_norm). Only invoice numbers that actually
exist in the data are accepted, so OCR noise (permit numbers, TINs) that
happens to look like "N<digits>" is filtered out by set membership.

### Function: `collect_candidates`

**Description / Analysis:**
Plausible (non-boilerplate) currency numbers in the document, descending — for display.

### Function: `_parse_amount`

**Description / Analysis:**
(value, is_clean) from an OCR token, stripping a leading label if present.

### Function: `_iter_boxes`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_parse_flexible_amount`

**Description / Analysis:**
(value, has_separator) tolerant of OCR separator noise ("74118-90" → 74118.90).

Treats a trailing 1–2 digit group after any separator as centavos, everything
else as the integer part. Handles ",", ".", and OCR's "-"/space mis-reads.

Also detects a dropped decimal point: when the last group after a comma has
exactly 4 digits (invalid thousands grouping), the last digit is treated as
a single decimal digit. E.g. "48,5782" → 48578.2 (not 485782).

### Function: `_find_total_label`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `_band_amount`

**Description / Analysis:**
Clean amount in the cell to the right of the label on the full-page pass.

### Function: `_reocr_total_cell`

**Description / Analysis:**
Second pass over the cell right of the total label: consistency voting.

The full-page recognizer drops digits on slanted handwritten totals
("74,118.90" → "4118-90"), and the read is very crop-sensitive. So we sweep a
few crop offsets × scales × a sharpen variant and keep only a value the OCR
reads the SAME way many times (a dominant plurality). Garbled totals scatter
into many low-count reads and are correctly rejected.

Returns (value, raw_token, confidence) or None.

### Function: `_fallback_table_total`

**Description / Analysis:**
Search the table body for a total amount when the footer extraction fails.

Two strategies, tried in order:
  1. Find a row labelled "total" in the table body and read its amount.
  2. If no "total" label is detected (common with handwriting), find the
     nearest non-boilerplate amount in the right column just ABOVE the
     footer "TOTAL AMOUNT DUE" label — on sales invoices the total is
     always the last amount before the footer.

Returns (value, raw_token, confidence) or (None, None, None).

### Function: `extract_total`

**Description / Analysis:**
Read the document total: locate the "TOTAL AMOUNT DUE" label, prefer a clean
full-page read, and fall back to an upscaled ROI re-OCR of the cell to its
right (which recovers digits the full-page pass drops on slanted handwriting).
Final fallback: search the table body for a "total" row whose amount was read.

Returns (total_or_None, raw_token, confidence). `total` is None when the cell
is blank or the number stays garbled/low-confidence — we deliberately do not
guess, because a wrong total is worse than an honest "unreadable".

### Function: `_load_psr_images`

**Description / Analysis:**
Load PSR pages as RGB WITHOUT the main pipeline's CLAHE contrast step.

These are handwritten receipts; the invoice pipeline's `preprocess_for_ocr`
(deskew + CLAHE) reliably mangles the handwritten TOTAL — e.g. "773.52" reads
as "3." and glues to the label. On the raw render PaddleOCR reads it cleanly
(verified). We keep this PSR-specific so the main invoice OCR is unaffected.

### Function: `_run_ocr`

**Description / Analysis:**
OCR raw file bytes -> (average_confidence_0to1, reconstructed_text, images, page_results).

### Function: `run_psr_extract_and_match`

**Description / Analysis:**
Full PSR pipeline: OCR the document, read its printed invoice number and
total, link it to an invoice record, and compare the total against that
record's `invoice_amount`. Returns a JSON-serializable dict.

Linking precedence (most to least reliable):
  1. invoice number — the printed "No." stamp matched to CSV `invoice_num`.
  2. file name — basename matched to CSV `file_name` (fallback; filenames
     are unreliable because of browser-renamed duplicates and shared names).

### Function: `alnum`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `alnum`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

### Function: `col`

**Description / Analysis:**
*No comments or docstrings provided for this function.*

---

