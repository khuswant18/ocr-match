"""
PSR (Payment Summary Report / handwritten Sales Invoice) extraction + amount match.

Self-contained, PaddleOCR-only (no LLM / Groq / vector). Given an uploaded PSR
scan (image or PDF), OCR it, link it to a record in the invoice data source by
its printed invoice number (falling back to file name), pull the
"TOTAL AMOUNT DUE", and report whether the extracted total matches that
record's `invoice_amount`.
"""
import os
import re
import csv
import json
import logging
from pathlib import Path

import cv2
import numpy as np
from collections import Counter

from app.utils.utils import _is_pdf, pdf_to_images
from app.utils.operations import process_paddleocr_text, _safe_float
# Reuse the shared PaddleOCR singleton + its lock + the route's error type.
# Importing these does NOT build a second (heavy) predictor.
from app.ocr.paddleOCR import ocr, _ocr_lock, ExtractionError

logger = logging.getLogger(__name__)

# --- Invoice data source (CSV now, JSON later) --------------------------
# The system's invoice records. Override with PSR_INVOICE_SOURCE (absolute path
# to a .csv or .json) — this is the single swap seam: when records arrive as
# JSON, point this at the .json file and nothing else changes.
#
# Without the env var we probe a few well-known locations so the same code works
# whether it runs from the repo (local dev) or inside the backend container
# (where the code lives at /app and the repo root maps to `/`). `psr/` must be
# reachable in the container — docker-compose mounts it to /psr.
_SOURCE_FILENAME = "cc-invoice-08-07-2026-v1.csv"
_SOURCE_CANDIDATES = [
    Path(__file__).resolve().parents[3] / "psr" / _SOURCE_FILENAME,  # local repo root
    Path("/psr") / _SOURCE_FILENAME,                                 # docker mount (./psr:/psr)
    Path(__file__).resolve().parents[2] / "psr" / _SOURCE_FILENAME,  # backend-local copy
]


def _resolve_source():
    env = os.environ.get("PSR_INVOICE_SOURCE")
    if env:
        return env
    for cand in _SOURCE_CANDIDATES:
        if cand.exists():
            return str(cand)
    # Nothing found — return the first candidate so the error message is useful.
    return str(_SOURCE_CANDIDATES[0])


INVOICE_SOURCE = _resolve_source()

# Absolute tolerance when comparing the OCR'd total to invoice_amount. Matches
# the repo's matching convention (abs diff <= 0.05); tune via env for handwriting.
try:
    MATCH_TOLERANCE = float(os.environ.get("PSR_MATCH_TOLERANCE", "0.05"))
except (TypeError, ValueError):
    MATCH_TOLERANCE = 0.05

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Label lines that precede/contain the document total, most-specific first.
_TOTAL_LABELS = ("total amount due", "amount due", "total")

# The printed invoice number ("No. 1666" / "N° 001495") stamped on the document.
# This is the reliable link to the CSV's `invoice_num`; filenames are not (a
# browser download of a second "Sales Invoice.pdf" becomes "Sales Invoice (1).pdf",
# and the CSV may map several rows to the same file_name).
_INVNO_RE = re.compile(r"N[o°Oº]?[.:_\-\s]*([0-9]{3,8})", re.I)

# Lines that carry printed boilerplate numbers (BIR permit, TIN, accreditation,
# booklet ranges, dates) — never the handwritten sales total. Excluded so the
# total extractor doesn't grab e.g. a "Print No. 2AU000 1847168" as the amount.
_BOILERPLATE_RE = re.compile(
    r"BIR|AUTHOR|PRINT|ACCREDIT|\bT1?N\b|\bREG\b|BK?LT?S|VALID|\bATP\b|"
    r"DOCUMENT|PRINTING|PROPRIETOR|OSCA|PWD\s*ID|SERIAL|PERMIT|ISSUED|CASHIER",
    re.I,
)

# Fields the matcher surfaces. All of these sit to the LEFT of the CSV's
# free-text `invoice_remarks` column, so they stay correctly aligned even when
# that column contains malformed embedded JSON (see _load_csv_records).
_NEEDED_COLUMNS = ("file_name", "invoice_amount", "reference_number", "invoice_num")

# A token that looks like a document filename.
_DOC_RE = re.compile(r".+\.(?:pdf|jpe?g|png|tiff?|bmp|webp)$", re.I)
# The CSV's `unique_document_name` is the stored copy: "<uuid>-<epoch_ms>.<ext>".
# We prefer the human-facing original `file_name` over it.
_UNIQUE_DOC_RE = re.compile(r"-\d{10,}\.[A-Za-z0-9]+$")


def _recover_file_name(tokens):
    """Pick the original document filename from a CSV row's tokens.

    The `file_name` column sits *after* `invoice_remarks`, whose malformed
    embedded JSON shifts later columns, so we can't trust its index. Instead we
    scan for a filename-shaped token, preferring the original over the
    `<uuid>-<epoch>.<ext>` stored name.
    """
    docs = [t.strip() for t in tokens if _DOC_RE.match(t.strip())]
    if not docs:
        return ""
    for tok in docs:
        if not _UNIQUE_DOC_RE.search(tok):
            return tok
    return docs[0]


def _load_csv_records(path):
    """Parse the invoice CSV into records exposing `_NEEDED_COLUMNS`.

    Robust to the fixture's malformed `invoice_remarks` (unescaped inner quotes
    in embedded JSON): the columns we need are all left of that field, read by
    fixed header index, and `file_name` is recovered from the row's tokens.
    """
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header:
            return []
        idx = {name: i for i, name in enumerate(header)}  # unique cols are left-aligned

        def col(tokens, name):
            i = idx.get(name)
            return tokens[i] if i is not None and i < len(tokens) else None

        records = []
        for tokens in reader:
            if not tokens:
                continue
            rec = {name: col(tokens, name) for name in _NEEDED_COLUMNS}
            rec["file_name"] = _recover_file_name(tokens)
            records.append(rec)
        return records


def load_invoice_records():
    """
    Return the invoice records as a list of dicts, each exposing at least
    `file_name` and `invoice_amount`.

    CSV -> JSON swap seam: reads .json (a list, or {"records": [...]}) or, by
    default, the CSV via the stdlib csv module (no pandas dependency).
    """
    path = INVOICE_SOURCE
    if not os.path.exists(path):
        raise ExtractionError(
            f"Invoice data source not found at {path}.",
            status_code=500,
        )

    if path.lower().endswith(".json"):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data = data.get("records", [])
        return [r for r in data if isinstance(r, dict)]

    return _load_csv_records(path)


def find_invoice_records(records, filename):
    """All records whose `file_name` matches `filename`'s basename (case-insensitive)."""
    if not filename:
        return []
    target = os.path.basename(str(filename)).strip().lower()
    matched = []
    for rec in records:
        rec_name = str(rec.get("file_name", "")).strip().lower()
        if rec_name and rec_name == target:
            matched.append(rec)
    return matched


def _norm_invnum(value):
    """Normalize an invoice number for comparison: digits only, no leading zeros.

    CSV stores "001495" / "0000235"; the OCR reads "N001495" / "No 1666". Compare
    as ints so leading-zero differences don't matter. Returns None if no digits.
    """
    digits = re.sub(r"\D", "", str(value or ""))
    return str(int(digits)) if digits else None


def extract_invoice_numbers(text):
    """Normalized invoice-number candidates read from the document's "No." stamp."""
    out = []
    seen = set()
    for m in _INVNO_RE.finditer(text or ""):
        norm = _norm_invnum(m.group(1))
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def find_by_invoice_number(records, text):
    """Link by the printed invoice number.

    Returns (matched_records, matched_norm). Only invoice numbers that actually
    exist in the data are accepted, so OCR noise (permit numbers, TINs) that
    happens to look like "N<digits>" is filtered out by set membership.
    """
    by_num = {}
    for rec in records:
        norm = _norm_invnum(rec.get("invoice_num"))
        if norm:
            by_num.setdefault(norm, []).append(rec)
    for norm in extract_invoice_numbers(text):
        if norm in by_num:
            return by_num[norm], norm
    return [], None


# A sales-invoice total realistically sits under this; anything larger is a
# permit/accreditation/serial number that leaked past the boilerplate filter.
_MAX_PLAUSIBLE_AMOUNT = 100_000_000


def collect_candidates(text):
    """Plausible (non-boilerplate) currency numbers in the document, descending — for display."""
    seen = set()
    candidates = []
    for line in (text or "").splitlines():
        if _BOILERPLATE_RE.search(line):
            continue
        for raw in _NUMBER_RE.findall(line):
            val = _safe_float(raw)
            if 0 < val < _MAX_PLAUSIBLE_AMOUNT and val not in seen:
                seen.add(val)
                candidates.append(val)
    candidates.sort(reverse=True)
    return candidates


# The numeric part of a total box after its label words. "Clean" means it is
# just a currency amount — no stray letters — which is our reliability signal
# (a garbled "63.b46.t" is NOT clean, so we won't report it as the total).
_AMOUNT_CORE_RE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)")
_CLEAN_AMOUNT_RE = re.compile(r"^[₱P$\s]*[0-9][0-9,]*(?:\.[0-9]+)?\.?[₱P\s]*$")
_TOTAL_CONF_MIN = 0.55


def _parse_amount(text):
    """(value, is_clean) from an OCR token, stripping a leading label if present."""
    core = re.sub(r"^[A-Za-z/\-.\s]+", "", text).strip()  # drop leading label words
    m = _AMOUNT_CORE_RE.search(core)
    if not m:
        return None, False
    val = _safe_float(m.group(1))
    if val <= 0:
        return None, False
    return val, bool(_CLEAN_AMOUNT_RE.match(core))


def _iter_boxes(results):
    for res in results or []:
        for line in res or []:
            box, (txt, conf) = line[0], line[1]
            ys = (box[0][1] + box[2][1]) / 2.0
            height = max(abs(box[2][1] - box[0][1]), 1.0)
            yield {
                "text": txt.strip(), "conf": conf,
                "y": ys, "x_left": box[0][0], "x_right": box[1][0], "h": height,
            }


def _parse_flexible_amount(text):
    """(value, has_separator) tolerant of OCR separator noise ("74118-90" → 74118.90).

    Treats a trailing 1–2 digit group after any separator as centavos, everything
    else as the integer part. Handles ",", ".", and OCR's "-"/space mis-reads.
    """
    s = re.sub(r"[^0-9.,\- ]", "", text)
    groups = [g for g in re.split(r"[.,\-\s]+", s) if g]
    if not groups:
        return None, False
    has_sep = len(groups) > 1
    if len(groups) == 1:
        return _safe_float(groups[0]), False
    if len(groups[-1]) in (1, 2):
        val = _safe_float("".join(groups[:-1]) + "." + groups[-1])
    else:
        val = _safe_float("".join(groups))
    return val, has_sep


def _find_total_label(boxes):
    def alnum(s):
        return "".join(c for c in s.lower() if c.isalnum())
    for key in ("totalamountdue", "amountdue"):
        hits = [b for b in boxes if key in alnum(b["text"])]
        if hits:
            return min(hits, key=lambda b: b["y"])  # topmost such label
    hits = [b for b in boxes if alnum(b["text"]) == "total"]
    if hits:
        return max(hits, key=lambda b: b["y"])  # the summary "Total" is lowest
    return None


def _band_amount(boxes, label):
    """Clean amount in the cell to the right of the label on the full-page pass."""
    band = [
        b for b in boxes
        if abs(b["y"] - label["y"]) <= max(label["h"], b["h"]) * 0.7
        and b["x_left"] >= label["x_left"]
        and not _BOILERPLATE_RE.search(b["text"])
    ]
    band.sort(key=lambda b: b["x_left"])
    for b in band:
        val, clean = _parse_amount(b["text"])
        if val is not None and clean and b["conf"] >= _TOTAL_CONF_MIN:
            return val, b["text"], round(b["conf"], 2)
    for b in band:  # nothing clean — keep the best raw token for the UI
        val, _ = _parse_amount(b["text"])
        if val is not None:
            return None, b["text"], round(b["conf"], 2)
    return None, None, None


_ROI_MIN_VOTES = 4  # of ~16 samples per document


def _reocr_total_cell(image, label):
    """Second pass over the cell right of the total label: consistency voting.

    The full-page recognizer drops digits on slanted handwritten totals
    ("74,118.90" → "4118-90"), and the read is very crop-sensitive. So we sweep a
    few crop offsets × scales × a sharpen variant and keep only a value the OCR
    reads the SAME way many times (a dominant plurality). Garbled totals scatter
    into many low-count reads and are correctly rejected.

    Returns (value, raw_token, confidence) or None.
    """
    H, W = image.shape[:2]
    y, h, xr = label["y"], label["h"], label["x_right"]
    y0, y1 = max(0, int(y - 1.7 * h)), min(H, int(y + 1.2 * h))

    votes = Counter()
    conf_of = {}
    for dx in (0.025, 0.02, 0.015, 0.01):
        x0 = max(0, int(xr - dx * W))
        cell = image[y0:y1, x0:W]
        if cell.shape[0] < 4 or cell.shape[1] < 4:
            continue
        gray = cv2.cvtColor(cell, cv2.COLOR_RGB2GRAY)
        sharp = cv2.cvtColor(
            cv2.addWeighted(gray, 1.5, cv2.GaussianBlur(gray, (0, 0), 3), -0.5, 0),
            cv2.COLOR_GRAY2RGB,
        )
        for variant in (cell, sharp):
            for scale in (4, 5):
                up = cv2.resize(variant, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                with _ocr_lock:
                    r = ocr.ocr(up, cls=True)
                for line in (r[0] or []):
                    txt, conf = line[1][0], line[1][1]
                    if _BOILERPLATE_RE.search(txt):
                        continue
                    val, has_sep = _parse_flexible_amount(txt)
                    # Require a separator: only then are the centavos anchored, so
                    # "74118-90" -> 74118.90 (not an ambiguous bare "7411890").
                    if val is None or not has_sep or not (0 < val < _MAX_PLAUSIBLE_AMOUNT):
                        continue
                    key = round(val, 2)
                    votes[key] += 1
                    conf_of[key] = max(conf_of.get(key, 0.0), conf)

    if not votes:
        return None
    ranked = votes.most_common(2)
    top_val, top_n = ranked[0]
    runner_n = ranked[1][1] if len(ranked) > 1 else 0
    if top_n >= _ROI_MIN_VOTES and top_n >= 2 * runner_n:
        return top_val, f"{top_val:.2f}", round(conf_of[top_val], 2)
    return None


def extract_total(page_results, images):
    """
    Read the document total: locate the "TOTAL AMOUNT DUE" label, prefer a clean
    full-page read, and fall back to an upscaled ROI re-OCR of the cell to its
    right (which recovers digits the full-page pass drops on slanted handwriting).

    Returns (total_or_None, raw_token, confidence). `total` is None when the cell
    is blank or the number stays garbled/low-confidence — we deliberately do not
    guess, because a wrong total is worse than an honest "unreadable".
    """
    for res, image in zip(page_results, images):
        boxes = list(_iter_boxes([res]))
        if not boxes:
            continue
        label = _find_total_label(boxes)
        if label is None:
            continue

        # 1) Trust a clean full-page read (reliable when the recognizer nails it).
        band_val, band_raw, band_conf = _band_amount(boxes, label)
        if band_val is not None:
            return band_val, band_raw, band_conf

        # 2) Full page couldn't read it cleanly — retry the cell with the voting
        #    sweep, which recovers digits the full-page pass drops.
        roi = _reocr_total_cell(image, label)
        if roi is not None:
            return roi  # (value, raw_token, confidence)

        return None, band_raw, band_conf
    return None, None, None


def _load_psr_images(file_bytes):
    """Load PSR pages as RGB WITHOUT the main pipeline's CLAHE contrast step.

    These are handwritten receipts; the invoice pipeline's `preprocess_for_ocr`
    (deskew + CLAHE) reliably mangles the handwritten TOTAL — e.g. "773.52" reads
    as "3." and glues to the label. On the raw render PaddleOCR reads it cleanly
    (verified). We keep this PSR-specific so the main invoice OCR is unaffected.
    """
    if not file_bytes:
        return None
    if _is_pdf(file_bytes):
        pages = pdf_to_images(file_bytes, dpi=300)  # raw RGB, one per page
        return pages or None
    img = cv2.imdecode(np.frombuffer(file_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    return [np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))]


def _run_ocr(file_bytes):
    """OCR raw file bytes -> (average_confidence_0to1, reconstructed_text, images, page_results)."""
    images = _load_psr_images(file_bytes)
    if not images:
        raise ExtractionError("No valid image or PDF found in request.", status_code=400)

    # Serialize predictor access; the singleton is not thread-safe.
    with _ocr_lock:
        page_results = []
        for page_img in images:
            page_result = ocr.ocr(page_img, cls=True)
            page_results.append(page_result[0] if (page_result and page_result[0]) else [])

    results = [pr for pr in page_results if pr]
    if not results:
        raise ExtractionError("OCR failed to extract any text from the document.", status_code=400)

    avg_conf, text = process_paddleocr_text(results)
    return avg_conf, text, images, page_results


def run_psr_extract_and_match(file_bytes, filename, override_name=None):
    """
    Full PSR pipeline: OCR the document, read its printed invoice number and
    total, link it to an invoice record, and compare the total against that
    record's `invoice_amount`. Returns a JSON-serializable dict.

    Linking precedence (most to least reliable):
      1. invoice number — the printed "No." stamp matched to CSV `invoice_num`.
      2. file name — basename matched to CSV `file_name` (fallback; filenames
         are unreliable because of browser-renamed duplicates and shared names).
    """
    avg_conf, text, images, page_results = _run_ocr(file_bytes)
    total, total_raw, total_conf = extract_total(page_results, images)
    candidates = collect_candidates(text)
    extracted_numbers = extract_invoice_numbers(text)

    link_name = override_name or filename
    records = load_invoice_records()

    matched_records, matched_num = find_by_invoice_number(records, text)
    match_method = "invoice_num" if matched_records else None
    if not matched_records:
        matched_records = find_invoice_records(records, link_name)
        match_method = "file_name" if matched_records else None

    linked = []
    matched = False
    for rec in matched_records:
        # A blank/invalid invoice_amount is unknown, not 0.0 — otherwise a
        # missing expected amount would produce a bogus difference/match.
        expected = _safe_float(rec.get("invoice_amount"), None)
        within = (
            expected is not None
            and total is not None
            and abs(total - expected) <= MATCH_TOLERANCE
        )
        if within:
            matched = True
        linked.append({
            "file_name": rec.get("file_name"),
            "invoice_amount": expected,
            "reference_number": rec.get("reference_number"),
            "invoice_num": rec.get("invoice_num"),
            "difference": None if (total is None or expected is None) else round(total - expected, 4),
            "within_tolerance": within,
        })

    if not matched_records:
        status = "no_record"
    elif total is None:
        status = "no_total_found"
    elif matched:
        status = "matched"
    else:
        status = "mismatch"

    return {
        "file_name": os.path.basename(str(link_name)) if link_name else None,
        "extracted_invoice_number": matched_num or (extracted_numbers[0] if extracted_numbers else None),
        "extracted_invoice_candidates": extracted_numbers,
        "match_method": match_method,
        "extracted_total": total,
        "total_raw": total_raw,
        "total_confidence": total_conf,
        "candidates": candidates,
        "average_confidence": round(avg_conf * 100, 2),
        "linked": linked,
        "matched": matched,
        "status": status,
        "tolerance": MATCH_TOLERANCE,
        "ocr_text": text,
    }
