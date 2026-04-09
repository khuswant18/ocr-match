import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from mysql_db import get_connection
from app.services.vector_service import index_po_items, find_ranked_candidates, RELAXED_THRESHOLD


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
    Fetch invoice items for a PO, accumulating quantities across multiple invoices.
    A PO can have several partial invoices — we SUM their quantities per product_code,
    mirroring how the GRN query does SUM(vo_tot_qty) GROUP BY product_code.

    Also normalises product_code format to match po_items keys (strip whitespace,
    leading zeros, case differences) and validates codes exist on the PO.
    """
    cursor.execute(
        """
        SELECT ii.product_code,
               ii.normalized_qty,
               ii.unit_price,
               ii.id  AS invoice_item_id,
               i.id   AS invoice_id,
               ii.product_name
        FROM invoice_items ii
        JOIN invoices i ON i.id = ii.invoice_id
        WHERE i.po_number = %s
          AND i.id = (SELECT MAX(id) FROM invoices WHERE po_number = %s)
        """,
        (str(po_number), str(po_number)),
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

        qty   = float(r[1] or 0)
        price = float(r[2] or 0)

        if code in items:
            items[code]["qty"] += qty
        else:
            items[code] = {
                "qty": qty,
                "price": price,
                "invoice_item_id": int(r[3]),
                "invoice_id": int(r[4]),
                "desc": str(r[5] or "")
            }
    return items


def run_three_way_match(po_number):
    """
    Executes the 3-Way Match, saves exact variances to the database, 
    and returns a clean flat list for the UI.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        po_items = _fetch_po_items(cursor, po_number)
        grn_items = _fetch_grn_items(cursor, po_number)
        inv_items = _fetch_invoice_items(cursor, po_number, po_items)
        print("po_items", po_items)
        print("grn_items", grn_items)
        print("inv_items", inv_items) 

        if not po_items:
            return {"error": "No PO lines found for this PO number."}
        if not inv_items:
            return {"error": "No Extracted Invoice Items found for this PO."}

        # Build Qdrant vectors for current PO items once per matching run.
        # If Qdrant is unavailable, continue with legacy heuristics.
        vector_enabled = True
        try:
            index_po_items(po_items)
        except Exception as e:
            vector_enabled = False
            print(f"[matching_service] Vector index skipped: {e}")

        import difflib
        
        po_desc_to_code = {data.get("desc", "").lower(): code for code, data in po_items.items() if data.get("desc")}
        
        for inv_code, inv_data in list(inv_items.items()):
            if inv_code.startswith("unknown_"):
                inv_desc = inv_data.get("desc", "").lower()
                matched_po_code = None

                if vector_enabled and inv_desc:
                    try:
                        candidates = find_ranked_candidates(
                            inv_desc,
                            threshold=RELAXED_THRESHOLD,
                            top_k=10,
                        )
                        if candidates:
                            matched_po_code = candidates[0][0]
                    except Exception as e:
                        print(f"[matching_service] Vector search failed for '{inv_desc}': {e}")
                
                if not matched_po_code and inv_desc and po_desc_to_code:
                    matches = difflib.get_close_matches(inv_desc, po_desc_to_code.keys(), n=1, cutoff=0.4)
                    if matches:
                        matched_po_code = po_desc_to_code[matches[0]]
                
                if not matched_po_code:
                    prices_match = [c for c, p_data in po_items.items() if abs(p_data["price"] - inv_data["price"]) <= 0.05]
                    if len(prices_match) == 1:
                        matched_po_code = prices_match[0]
                
                if matched_po_code:
                    if matched_po_code in inv_items:
                        # Throw away the ghost OCR duplicate, DO NOT add the quantities
                        pass

                    else:
                        inv_items[matched_po_code] = inv_items.pop(inv_code)

        ui_results = []

        invoice_id = list(inv_items.values())[0]["invoice_id"]
        # Delete ALL previous results for this PO (not just one invoice_id),
        # because a PO can have multiple partial invoices.
        cursor.execute("DELETE FROM matching_results WHERE po_number = %s", (str(po_number),))

        all_codes = set(po_items.keys()) | set(grn_items.keys()) | set(inv_items.keys())

        for code in sorted(all_codes):
            po = po_items.get(code)
            grn = grn_items.get(code)
            inv = inv_items.get(code)

            # Skip items that are just on the PO but haven't been billed or delivered yet
            if po and not grn and not inv:
                continue

            po_qty = po["qty"] if po else 0.0
            po_price = po["price"] if po else 0.0
            # Grab the conversion factor (default to 1.0 if not found)
            conversion_factor = po["conversion_factor"] if po else 1.0 
            
            grn_qty = grn["qty"] if grn else 0.0
            grn_number = grn["grn_number"] if grn else None
            
            raw_inv_qty = inv["qty"] if inv else 0.0
            inv_price = inv["price"] if inv else 0.0
            inv_item_id = inv["invoice_item_id"] if inv else None

            # Normalize ONLY the quantity (Cases to Cans), leave the price alone!
            normalized_inv_qty = raw_inv_qty * conversion_factor

            qty_variance = round(normalized_inv_qty - grn_qty, 2)
            is_qty_match = True if qty_variance <= 0 else False

            # Price Variance: Compare direct invoice case price against PO case price
            price_variance = round(inv_price - po_price, 4)
            is_price_match = True if price_variance <= 0.05 else False
            
            if not po:
                if code.startswith("unknown_"):
                    status = "unmatched"
                    issue_summary = "Could not auto-match — assign product code manually via the dropdown."
                else:
                    status = "not_on_po"
                    issue_summary = "Item billed but never ordered on this PO."
            elif not inv:
                status = "not_billed"
                issue_summary = "Item delivered but not on vendor invoice."
            elif is_qty_match and is_price_match:
                status = "matched" 
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
                    issues.append(f"Overpriced by {price_variance} per unit")
                issue_summary = " | ".join(issues)

            result_row = {
                "invoice_id": invoice_id,
                "invoice_item_id": inv_item_id,
                "po_number": po_number,
                "grn_number": grn_number,
                "product_code": code,
                "po_qty": po_qty,
                "grn_qty": grn_qty,
                "invoice_qty_raw": raw_inv_qty,
                "conversion_factor": conversion_factor,
                "invoice_qty": normalized_inv_qty,
                "qty_variance": qty_variance,
                "is_qty_match": is_qty_match,
                "po_price": po_price,
                "invoice_price": inv_price, # Ensures raw inv_price is sent to the DB and UI
                "price_variance": price_variance,
                "is_price_match": is_price_match,
                "status": status,
                "issue_summary": issue_summary
            }
            ui_results.append(result_row)

            cursor.execute("""
                INSERT INTO matching_results (
                    invoice_id, invoice_item_id, po_number, grn_number, product_code,
                    po_qty, grn_qty, invoice_qty, qty_variance, is_qty_match,
                    po_price, invoice_price, price_variance, is_price_match,
                    status, issue_summary
                ) VALUES (
                    %(invoice_id)s, %(invoice_item_id)s, %(po_number)s, %(grn_number)s, %(product_code)s,
                    %(po_qty)s, %(grn_qty)s, %(invoice_qty)s, %(qty_variance)s, %(is_qty_match)s,
                    %(po_price)s, %(invoice_price)s, %(price_variance)s, %(is_price_match)s,
                    %(status)s, %(issue_summary)s
                )
            """, result_row)

        conn.commit()
        raw_po_list = [{"product_code": code, **data} for code, data in po_items.items()]
        raw_inv_list = [{"product_code": code, **data} for code, data in inv_items.items()]
        raw_grn_list = [{"product_code": code, **data} for code, data in grn_items.items()]
        return {"status": "success", "raw_po_items": raw_po_list, "raw_inv_items": raw_inv_list, "raw_grn_items": raw_grn_list, "matches": ui_results} 

    except Exception as e:
        conn.rollback()
        return {"error": str(e)}

    finally:
        cursor.close()
        conn.close()


def get_po_list():
    """Return list of available PO numbers from po_headers."""
    conn = get_connection() 
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT po_number, po_date, store_code, supplier_code FROM po_headers ORDER BY po_date DESC"
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