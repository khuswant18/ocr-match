import sys
import os
import json
import time
import difflib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from mysql_db import get_connection
from app.services.vector_service import index_po_items, find_ranked_candidates, delete_collection, RELAXED_THRESHOLD
import uuid

def _fetch_po_items(cursor, po_number):
    cursor.execute(
        """
        SELECT product_code,
               po_total_qty AS qty,
               purchase_price AS price,
               buying_conversion_factor,
               product_full_desc
        FROM po_lines
        WHERE po_number = %s
        """,
        (str(po_number),),
    ) 
    items = {}
    for r in cursor.fetchall():
        items[str(r[0]).strip()] = {
            "qty": float(r[1] or 0),
            "price": float(r[2] or 0),
            "conversion_factor": float(r[3] or 1.0),
            "desc": str(r[4] or "")
        }
    return items

def _fetch_grn_items(cursor, po_number):
    # pol_grn.po_trans_no is numeric — try int first, fall back to string match
    po_str = str(po_number).strip()
    try:
        grn_po_number = int(po_str)
    except ValueError:
        grn_po_number = None

    # Try both numeric and string match to be safe
    if grn_po_number is not None:
        cursor.execute(
            """
            SELECT product_code,
                   SUM(vo_tot_qty) AS qty,
                   MAX(vo_trans_no) AS grn_number
            FROM pol_grn
            WHERE po_trans_no = %s
            GROUP BY product_code
            """,
            (grn_po_number,),
        )
    else:
        cursor.execute(
            """
            SELECT product_code,
                   SUM(vo_tot_qty) AS qty,
                   MAX(vo_trans_no) AS grn_number
            FROM pol_grn
            WHERE CAST(po_trans_no AS CHAR) = %s
            GROUP BY product_code
            """,
            (po_str,),
        )

    items = {}
    for r in cursor.fetchall():
        items[str(r[0]).strip()] = {
            "qty": float(r[1] or 0),
            "grn_number": str(r[2] or "")
        }
    return items

def _fetch_invoice_items(cursor, po_number, po_items):
    """
    Fetch ALL invoice items across ALL invoices for a PO (multi-invoice support).
    A PO can have several partial invoices — quantities are accumulated per product_code.
    Each product_code entry also carries an `invoice_lines` list so the caller can
    save one matching_results row per invoice line for a full audit trail.
    """
    cursor.execute(
        """
        SELECT ii.product_code,
               ii.normalized_qty,
               ii.unit_price,
               ii.id          AS invoice_item_id,
               i.id           AS invoice_id,
               ii.product_name,
               i.invoice_number
        FROM invoice_items ii
        JOIN invoices i ON i.id = ii.invoice_id
        WHERE i.po_number = %s
        ORDER BY i.id ASC, ii.id ASC
        """,
        (str(po_number),),
    )

    # Build a lookup for product code normalisation:
    # Try the raw code, stripped code, code without leading zeros, etc.
    _po_code_lookup: dict[str, str] = {}
    for po_code in po_items:
        canonical = po_code.strip()
        _po_code_lookup[canonical] = canonical
        _po_code_lookup[canonical.lower()] = canonical
        _po_code_lookup[canonical.lstrip("0")] = canonical
        # With zero-padding up to 6 digits
        if canonical.isdigit():
            _po_code_lookup[canonical.zfill(6)] = canonical

    items = {}
    unknown_count = 0
    for r in cursor.fetchall():
        raw_code = str(r[0] or "").strip()

        # Try to resolve the invoice's product_code to a known PO code
        code = ""
        if raw_code:
            code = _po_code_lookup.get(raw_code,
                   _po_code_lookup.get(raw_code.lower(),
                   _po_code_lookup.get(raw_code.lstrip("0"), "")))
            if not code and raw_code.isdigit():
                code = _po_code_lookup.get(raw_code.zfill(6), "")
            if not code:
                # Code exists but doesn't match any PO line — keep it as-is
                # (will show as not_on_po later, which is informative)
                code = raw_code

        if not code:
            unknown_count += 1
            code = f"unknown_{unknown_count}"

        qty            = float(r[1] or 0)
        price          = float(r[2] or 0)
        invoice_item_id = int(r[3])
        invoice_id     = int(r[4])
        desc           = str(r[5] or "")
        invoice_number = str(r[6] or "")

        # Per-line record for audit trail (one row in matching_results per line)
        line_record = {
            "invoice_item_id": invoice_item_id,
            "invoice_id":      invoice_id,
            "invoice_number":  invoice_number,
            "qty":             qty,
            "price":           price,
        }

        if code in items:
            items[code]["qty"] += qty
            items[code]["invoice_lines"].append(line_record)
        else:
            items[code] = {
                "qty":             qty,
                "price":           price,
                "invoice_item_id": invoice_item_id,  # first line — kept for backward compat
                "invoice_id":      invoice_id,
                "desc":            desc,
                "invoice_lines":   [line_record],
            }
    return items


def _po_items_from_lines(po_lines):
    items = {}
    for r in po_lines or []:
        code = str(r.get("product_code", "")).strip()
        if not code:
            continue
        # External APIs may use 'description' or 'product_desc' instead of 'product_full_desc'
        desc = (
            r.get("product_full_desc")
            or r.get("description")
            or r.get("product_desc")
            or ""
        )
        items[code] = {
            "qty":               float(r.get("po_total_qty") or 0),
            "price":             float(r.get("purchase_price") or 0),
            "conversion_factor": float(r.get("buying_conversion_factor") or 1.0),
            "desc":              str(desc),
        }
    return items

def _grn_items_from_lines(pol_grn):
    """Replicates the old SQL: GROUP BY product_code, SUM(vo_tot_qty), MAX(vo_trans_no)."""
    items = {}
    for r in pol_grn or []:
        code = str(r.get("product_code", "")).strip()
        if not code:
            continue
        qty = float(r.get("vo_tot_qty") or 0)
        grn = str(r.get("vo_trans_no") or "")
        if code in items:
            items[code]["qty"] += qty
            items[code]["grn_number"] = max(items[code]["grn_number"], grn)
        else:
            items[code] = {"qty": qty, "grn_number": grn}
    return items

def _inv_items_from_ocr(parsed_data, invoice_id=None):
    """
    Same shape _fetch_invoice_items returned (qty/price/desc/invoice_lines), but
    sourced from the OCR result instead of the DB.  `quantity` here is RAW — the
    matcher applies the conversion_factor — and there are no per-line DB ids.
    """
    parsed_data = parsed_data or {}
    inv_number = str(parsed_data.get("invoice_number") or "")
    items = {}
    unknown = 0
    for it in parsed_data.get("items", []) or []:
        code = str(it.get("product_code") or "").strip()
        if not code:
            unknown += 1
            code = f"unknown_{unknown}"
        qty   = float(it.get("quantity") or 0)
        price = float(it.get("unit_price") or 0)
        desc  = str(it.get("description") or "")
        line  = {
            "invoice_item_id": None,
            "invoice_id":      invoice_id,
            "invoice_number":  inv_number,
            "qty":             qty,
            "price":           price,
        }
        if code in items:
            items[code]["qty"] += qty
            items[code]["invoice_lines"].append(line)
        else:
            items[code] = {
                "qty":             qty,
                "price":           price,
                "invoice_item_id": None,
                "invoice_id":      invoice_id,
                "desc":            desc,
                "invoice_lines":   [line],
            }
    return items

def _auto_match(po_items, inv_items, vector_enabled, collection_name=None):
    """
    Resolve invoice lines whose product_code didn't map to a PO line
    ("unknown_*") onto a PO code, in place. Uses vector search, fuzzy
    description match and price heuristics — no DB access.
    """
    po_desc_to_code = {data.get("desc", "").lower(): code
                       for code, data in po_items.items() if data.get("desc")}

    already_matched_po_codes = {c for c in inv_items if not c.startswith("unknown_")}

    for inv_code, inv_data in list(inv_items.items()):
        if not inv_code.startswith("unknown_"):
            continue
        inv_desc = inv_data.get("desc", "").lower()
        inv_price = inv_data.get("price", 0)
        matched_po_code = None

        # Pass 1: Vector (semantic) search
        if vector_enabled and inv_desc:
            try:
                candidates = find_ranked_candidates(
                    inv_desc,
                    threshold=RELAXED_THRESHOLD,
                    top_k=10,
                    collection_name=collection_name,
                )
                for code, score in candidates:
                    if code not in already_matched_po_codes:
                        matched_po_code = code
                        break
            except Exception as e:
                print(f"[matching_service] Vector search failed for '{inv_desc}': {e}")

        # Pass 2: Fuzzy string match on descriptions
        if not matched_po_code and inv_desc and po_desc_to_code:
            unmatched_descs = {d: c for d, c in po_desc_to_code.items()
                               if c not in already_matched_po_codes}
            if unmatched_descs:
                matches = difflib.get_close_matches(inv_desc, unmatched_descs.keys(), n=1, cutoff=0.35)
                if matches:
                    matched_po_code = unmatched_descs[matches[0]]

        # Pass 3: Price match (only if exactly one unmatched PO item has this price)
        if not matched_po_code:
            prices_match = [c for c, p_data in po_items.items()
                            if abs(p_data["price"] - inv_price) <= 0.05
                            and c not in already_matched_po_codes]
            if len(prices_match) == 1:
                matched_po_code = prices_match[0]

        # Pass 4: Combined price + partial description match
        if not matched_po_code and inv_desc:
            for po_code, po_data in po_items.items():
                if po_code in already_matched_po_codes:
                    continue
                po_desc = po_data.get("desc", "").lower()
                price_close = abs(po_data["price"] - inv_price) <= po_data["price"] * 0.1
                desc_tokens = set(inv_desc.split()) & set(po_desc.split())
                if price_close and len(desc_tokens) >= 2:
                    matched_po_code = po_code
                    break

        if matched_po_code:
            if matched_po_code in inv_items:
                pass  # duplicate — discard
            else:
                inv_items[matched_po_code] = inv_items.pop(inv_code)
                already_matched_po_codes.add(matched_po_code)


def _build_ui_results(po_items, grn_items, inv_items, po_number):
    """
    Compare PO / GRN / invoice per product_code and return the flat UI rows.
    Pure — no DB access. The legacy SQL path persists from these rows separately.
    """
    ui_results = []
    all_codes = set(po_items.keys()) | set(grn_items.keys()) | set(inv_items.keys())

    for code in sorted(all_codes):
        po  = po_items.get(code)
        grn = grn_items.get(code)
        inv = inv_items.get(code)

        # Skip items that are just on the PO but haven't been billed or delivered yet
        if po and not grn and not inv:
            continue

        po_qty            = po["qty"]  if po  else 0.0
        po_price          = po["price"] if po  else 0.0
        conversion_factor = po["conversion_factor"] if po else 1.0

        grn_qty    = grn["qty"]        if grn else 0.0
        grn_number = grn["grn_number"] if grn else None

        # Aggregate across all partial invoices for this product_code
        raw_inv_qty   = inv["qty"]   if inv else 0.0
        inv_price     = inv["price"] if inv else 0.0
        invoice_lines = inv["invoice_lines"] if inv else []

        # Normalize quantity (e.g. cases → cans), leave price as-is
        normalized_inv_qty = raw_inv_qty * conversion_factor

        qty_variance   = round(normalized_inv_qty - grn_qty, 2)
        is_qty_match   = qty_variance <= 0

        price_variance = round(inv_price - po_price, 4)
        is_price_match = abs(price_variance) <= 0.05

        if not po:
            if code.startswith("unknown_"):
                status        = "unmatched"
                issue_summary = "Could not auto-match — assign product code manually via the dropdown."
            else:
                status        = "not_on_po"
                issue_summary = "Item billed but never ordered on this PO."
        elif not inv:
            status        = "not_billed"
            issue_summary = "Item delivered but not on vendor invoice."
        elif is_qty_match and is_price_match:
            status        = "matched"
            issue_summary = "Perfect Match."
        else:
            status = "mismatch"
            issues = []
            if not is_qty_match:
                if conversion_factor != 1.0:
                    issues.append(
                        f"Overbilled by {qty_variance} units "
                        f"(invoice {raw_inv_qty} × CF {conversion_factor} = {normalized_inv_qty})"
                    )
                else:
                    issues.append(f"Overbilled by {qty_variance} units")
            if not is_price_match:
                if price_variance > 0:
                    issues.append(f"Overpriced by {price_variance} per unit")
                else:
                    issues.append(f"Underpriced by {abs(price_variance)} per unit")
            issue_summary = " | ".join(issues)

        # UI result — one row per product_code with per-invoice breakdown
        ui_row = {
            # Use the first invoice's ID for backward compat; full list is in invoice_lines
            "invoice_id":       invoice_lines[0]["invoice_id"]      if invoice_lines else None,
            "invoice_item_id":  invoice_lines[0]["invoice_item_id"] if invoice_lines else None,
            "po_number":        po_number,
            "grn_number":       grn_number,
            "product_code":     code,
            "po_qty":           po_qty,
            "grn_qty":          grn_qty,
            "invoice_qty_raw":  raw_inv_qty,
            "conversion_factor": conversion_factor,
            "invoice_qty":      normalized_inv_qty,
            "qty_variance":     qty_variance,
            "is_qty_match":     is_qty_match,
            "po_price":         po_price,
            "invoice_price":    inv_price,
            "price_variance":   price_variance,
            "is_price_match":   is_price_match,
            "status":           status,
            "issue_summary":    issue_summary,
            # Per-invoice breakdown so the UI can show each partial invoice
            "invoice_lines": [
                {
                    "invoice_id":      l["invoice_id"],
                    "invoice_number":  l["invoice_number"],
                    "invoice_item_id": l["invoice_item_id"],
                    "qty":             l["qty"],
                    "normalized_qty":  round(l["qty"] * conversion_factor, 4),
                    "price":           l["price"],
                }
                for l in invoice_lines
            ],
        }
        ui_results.append(ui_row)

    return ui_results


def _persist_matching_results(cursor, po_number, ui_results):
    """Persist UI rows to matching_results — one row per invoice line."""
    # Delete ALL previous results for this PO before re-inserting.
    cursor.execute("DELETE FROM matching_results WHERE po_number = %s", (str(po_number),))

    insert_sql = """
        INSERT INTO matching_results (
            invoice_id, invoice_item_id, po_number, grn_number, product_code,
            po_qty, grn_qty, invoice_qty, qty_variance, is_qty_match,
            po_price, invoice_price, price_variance, is_price_match,
            status, issue_summary
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s
        )
    """

    for row in ui_results:
        invoice_lines = row["invoice_lines"]
        if invoice_lines:
            for line in invoice_lines:
                cursor.execute(insert_sql, (
                    line["invoice_id"], line["invoice_item_id"], po_number,
                    row["grn_number"], row["product_code"],
                    row["po_qty"], row["grn_qty"], line["normalized_qty"],
                    row["qty_variance"], row["is_qty_match"],
                    row["po_price"], line["price"], row["price_variance"], row["is_price_match"],
                    row["status"], row["issue_summary"],
                ))
        else:
            # not_billed — no invoice lines, save one row with nulls
            cursor.execute(insert_sql, (
                None, None, po_number, row["grn_number"], row["product_code"],
                row["po_qty"], row["grn_qty"], 0, row["qty_variance"], row["is_qty_match"],
                row["po_price"], 0, row["price_variance"], row["is_price_match"],
                row["status"], row["issue_summary"],
            ))

def run_three_way_match(po_number):
    """
    Executes the 3-Way Match against the DB (legacy path used by /api/pipeline/match),
    saves exact variances to the database, and returns a clean flat list for the UI.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        po_items = _fetch_po_items(cursor, po_number)
        grn_items = _fetch_grn_items(cursor, po_number)
        inv_items = _fetch_invoice_items(cursor, po_number, po_items)

        if not po_items:
            return {"error": "No PO lines found for this PO number."}
        if not inv_items:
            return {"error": "No Extracted Invoice Items found for this PO."}

        # Build Qdrant vectors for current PO items once per matching run.
        # If Qdrant is unavailable, continue with legacy heuristics.
        vector_enabled = True
        vector_collection = f"po_{po_number}_{uuid.uuid4().hex}"
        try:
            index_po_items(po_items, collection_name=vector_collection)
        except Exception as e:
            vector_enabled = False
            print(f"[matching_service] Vector index skipped: {e}")

        _auto_match(po_items, inv_items, vector_enabled, collection_name=vector_collection)
        ui_results = _build_ui_results(po_items, grn_items, inv_items, po_number)
        _persist_matching_results(cursor, po_number, ui_results)

        conn.commit()
        raw_po_list = [{"product_code": code, **data} for code, data in po_items.items()]
        raw_inv_list = [{"product_code": code, **data} for code, data in inv_items.items()]
        raw_grn_list = [{"product_code": code, **data} for code, data in grn_items.items()]
        
        try:
            if vector_enabled:
                delete_collection(vector_collection)
        except Exception as e:
            print(f"[matching_service] Cleanup error: {e}")

        return {"status": "success", "raw_po_items": raw_po_list, "raw_inv_items": raw_inv_list, "raw_grn_items": raw_grn_list, "matches": ui_results}

    except Exception as e:
        conn.rollback()
        return {"error": str(e)}

    finally:
        cursor.close()
        conn.close()

def run_match_from_payload(po_number, po_lines, pol_grn, parsed_data, invoice_id=None):
    """
    3-Way Match with PO/GRN supplied as JSON (raw SQL-column rows) and the invoice
    sourced from the OCR result. Fully in memory — no DB reads or writes.
    """
    # Save raw incoming PO and GRN payloads to JSON files for debugging
    os.makedirs('uploads', exist_ok=True)
    ts = int(time.time())
    po_dump_path = f"uploads/{ts}_PO_{po_number}_po_lines.json"
    grn_dump_path = f"uploads/{ts}_PO_{po_number}_pol_grn.json"
    try:
        with open(po_dump_path, 'w') as f:
            json.dump(po_lines, f, indent=2, default=str)
        with open(grn_dump_path, 'w') as f:
            json.dump(pol_grn, f, indent=2, default=str)
        print(f"[DEBUG] Saved PO payload -> {po_dump_path}")
        print(f"[DEBUG] Saved GRN payload -> {grn_dump_path}")
    except Exception as e:
        print(f"[DEBUG] Failed to save PO/GRN payloads: {e}")

    po_items  = _po_items_from_lines(po_lines)
    grn_items = _grn_items_from_lines(pol_grn)
    inv_items = _inv_items_from_ocr(parsed_data, invoice_id)

    print(f"\n{'='*60}")
    print(f"[DEBUG] run_match_from_payload for PO: {po_number}")
    print(f"{'='*60}")
    print(f"\n--- RAW po_lines ({len(po_lines or [])}) ---")
    for i, r in enumerate(po_lines or []):
        print(f"  [{i}] code={r.get('product_code')} desc={r.get('product_full_desc')!r} | description={r.get('description')!r} | product_desc={r.get('product_desc')!r}")
    print(f"\n--- PARSED po_items ({len(po_items)}) ---")
    for code, data in po_items.items():
        print(f"  [{code}] desc={data.get('desc')!r} qty={data.get('qty')} price={data.get('price')}")
    print(f"\n--- PARSED grn_items ({len(grn_items)}) ---")
    for code, data in grn_items.items():
        print(f"  [{code}] qty={data.get('qty')} grn_number={data.get('grn_number')}")
    print(f"\n--- PARSED inv_items ({len(inv_items)}) ---")
    for code, data in inv_items.items():
        print(f"  [{code}] desc={data.get('desc')!r} qty={data.get('qty')} price={data.get('price')}")
    print(f"{'='*60}\n")

    if not po_items:
        return {"error": "No PO lines provided."}
    if not inv_items:
        return {"error": "No invoice items extracted from the PDF."}

    # Build Qdrant vectors for current PO items once per matching run.
    # If Qdrant is unavailable, continue with legacy heuristics.
    vector_enabled = True
    vector_collection = f"po_{po_number}_{uuid.uuid4().hex}"
    try:
        index_po_items(po_items, collection_name=vector_collection)
    except Exception as e:
        vector_enabled = False
        print(f"[matching_service] Vector index skipped: {e}")

    _auto_match(po_items, inv_items, vector_enabled, collection_name=vector_collection)
    ui_results = _build_ui_results(po_items, grn_items, inv_items, po_number)
    
    try:
        if vector_enabled:
            delete_collection(vector_collection)
    except Exception as e:
        print(f"[matching_service] Cleanup error: {e}")

    return {
        "status": "success",
        "raw_po_items":  [{"product_code": c, **d} for c, d in po_items.items()],
        "raw_inv_items": [{"product_code": c, **d} for c, d in inv_items.items()],
        "raw_grn_items": [{"product_code": c, **d} for c, d in grn_items.items()],
        "matches": ui_results,
    }

def get_po_list():
    """Return list of available PO numbers from po_headers UNION invoices."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT po_number, po_date, store_code, supplier_code FROM po_headers
            UNION
            SELECT DISTINCT pl.po_number, NULL, pl.store_code, NULL
            FROM po_lines pl
            WHERE NOT EXISTS (SELECT 1 FROM po_headers ph WHERE ph.po_number = pl.po_number)
            UNION
            SELECT i.po_number, i.invoice_date, NULL, NULL
            FROM invoices i
            WHERE i.po_number IS NOT NULL AND i.po_number != ''
              AND NOT EXISTS (SELECT 1 FROM po_headers ph2 WHERE ph2.po_number = i.po_number)
              AND NOT EXISTS (SELECT 1 FROM po_lines pl2 WHERE pl2.po_number = i.po_number)
            ORDER BY po_date DESC
            """
        )
        rows = cursor.fetchall()
        return [
            {
                "po_number": str(r[0]),
                "po_date": str(r[1]) if r[1] else None,
                "store_code": str(r[2]) if r[2] else None,
                "supplier_code": str(r[3]) if r[3] else None,
            }
            for r in rows
        ]
    finally:
        cursor.close()
        conn.close()


def get_po_items(po_number):
    """
    Returns the specific line items ordered for a given PO Number.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT po_number, 
                   product_code, 
                   product_full_desc, 
                   store_code, 
                   po_total_qty,
                   purchase_price
            FROM po_lines
            WHERE po_number = %s
            """,
            (str(po_number),)
        )
        rows = cursor.fetchall()
        return [
            {
                "po_number": str(r[0]),
                "product_code": str(r[1]),
                "product_full_desc": str(r[2]),
                "store_code": str(r[3]),
                "po_total_qty": float(r[4] or 0),
                "purchase_price": float(r[5] or 0)
            }
            for r in rows
        ]
    finally:
        cursor.close()
        conn.close()

def update_invoice_item_code(invoice_item_id, new_product_code):
    """
    Updates the product_code of an invoice item, effectively manual matching it.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE invoice_items 
            SET product_code = %s 
            WHERE id = %s
            """,
            (new_product_code, invoice_item_id)
        )
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}
    finally:
        cursor.close()
        conn.close()