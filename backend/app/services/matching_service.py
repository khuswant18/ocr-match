"""
Three-Way Match Validation Engine
Compares PO (ordered) vs GRN (delivered) vs Invoice (billed) items.
"""
import sys
import os

# Add backend root so we can import the standalone mysql connector
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from mysql_db import get_connection


def _fetch_po_items(cursor, po_number):
    """Fetch PO line items for a given PO number."""
    cursor.execute(
        """
        SELECT product_code,
               po_total_qty   AS qty,
               purchase_price AS price
        FROM po_lines
        WHERE po_number = %s
        """,
        (str(po_number),),
    )
    rows = cursor.fetchall()
    # Return dict keyed by product_code
    items = {}
    for r in rows:
        code = str(r[0]).strip()
        items[code] = {
            "qty": float(r[1] or 0),
            "price": float(r[2] or 0),
        }
    return items


def _fetch_grn_items(cursor, po_number):
    """Fetch GRN (pol_grn) items linked to a PO number via po_trans_no."""
    
    # Safely convert strictly numeric PO to int for GRN table (bigint).
    # If the user typed non-numeric, it might just be 0 or -1 safely.
    try:
        grn_po_number = int(str(po_number).strip())
    except ValueError:
        grn_po_number = -1

    cursor.execute(
        """
        SELECT product_code,
               SUM(vo_tot_qty) AS qty,
               SUM(vo_net_val) AS net_val
        FROM pol_grn
        WHERE po_trans_no = %s
        GROUP BY product_code
        """,
        (grn_po_number,),
    )
    rows = cursor.fetchall()
    items = {}
    for r in rows:
        code = str(r[0]).strip()
        items[code] = {
            "qty": float(r[1] or 0),
            "net_val": float(r[2] or 0),
        }
    return items


def _fetch_invoice_items(cursor, po_number):
    """Fetch invoice items linked to a PO number (via invoices table)."""
    cursor.execute(
        """
        SELECT ii.product_code,
               ii.quantity,
               ii.unit_price,
               ii.total_price
        FROM invoice_items ii
        JOIN invoices i ON i.id = ii.invoice_id
        WHERE i.po_number = %s
        """,
        (str(po_number),),
    )
    rows = cursor.fetchall()
    items = {}
    for r in rows:
        code = str(r[0] or "").strip()
        if not code:
            continue
        items[code] = {
            "qty": float(r[1] or 0),
            "price": float(r[2] or 0),
            "total": float(r[3] or 0),
        }
    return items


def _item_result(product_code, po_item, grn_item, inv_item, issue):
    """Build a standard result dict for one product."""
    return {
        "product_code": product_code,
        "po_qty": po_item.get("qty", 0) if po_item else 0,
        "grn_qty": grn_item.get("qty", 0) if grn_item else 0,
        "invoice_qty": inv_item.get("qty", 0) if inv_item else 0,
        "po_price": po_item.get("price", 0) if po_item else 0,
        "invoice_price": inv_item.get("price", 0) if inv_item else 0,
        "issue": issue,
    }


def run_three_way_match(po_number):
    """
    Execute the three-way match for a given PO number.
    Returns strict JSON result or an error dict.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        po_items = _fetch_po_items(cursor, po_number)
        grn_items = _fetch_grn_items(cursor, po_number)
        inv_items = _fetch_invoice_items(cursor, po_number)

        # Check if we have enough data
        if not po_items:
            return {"error": "Not enough fields — no PO lines found for this PO number"}

        result = {
            "missing": [],
            "extra": [],
            "invoice_mismatch": [],
            "delivery_mismatch": [],
            "quantity_mismatch": [],
            "price_mismatch": [],
        }

        all_codes = set(po_items.keys()) | set(grn_items.keys()) | set(inv_items.keys())

        for code in sorted(all_codes):
            po = po_items.get(code)
            grn = grn_items.get(code)
            inv = inv_items.get(code)

            # 1. Missing item — in PO but not in GRN or Invoice
            if po and (not grn and not inv):
                result["missing"].append(
                    _item_result(code, po, grn, inv, "Item in PO but missing from GRN and Invoice")
                )
                continue
            if po and not grn:
                result["missing"].append(
                    _item_result(code, po, grn, inv, "Item in PO but missing from GRN")
                )
            if po and not inv:
                result["missing"].append(
                    _item_result(code, po, grn, inv, "Item in PO but missing from Invoice")
                )

            # 2. Extra item — in GRN or Invoice but not in PO
            if not po and (grn or inv):
                result["extra"].append(
                    _item_result(code, po, grn, inv, "Item in GRN/Invoice but not in PO")
                )
                continue

            # For the remaining checks we need PO to exist
            if not po:
                continue

            po_qty = po["qty"]
            grn_qty = grn["qty"] if grn else 0
            inv_qty = inv["qty"] if inv else 0
            po_price = po["price"]
            inv_price = inv["price"] if inv else 0

            # 3. Delivery mismatch — PO qty != GRN qty
            if grn and po_qty != grn_qty:
                result["delivery_mismatch"].append(
                    _item_result(code, po, grn, inv, f"PO qty ({po_qty}) != GRN qty ({grn_qty})")
                )

            # 4. Invoice mismatch — GRN qty != Invoice qty
            if grn and inv and grn_qty != inv_qty:
                result["invoice_mismatch"].append(
                    _item_result(code, po, grn, inv, f"GRN qty ({grn_qty}) != Invoice qty ({inv_qty})")
                )

            # 5. Quantity mismatch — all three differ
            if grn and inv and not (po_qty == grn_qty == inv_qty):
                # Avoid duplicating if already captured above
                entry = _item_result(
                    code, po, grn, inv,
                    f"PO({po_qty}) / GRN({grn_qty}) / INV({inv_qty}) quantities not equal"
                )
                if entry not in result["quantity_mismatch"]:
                    result["quantity_mismatch"].append(entry)

            # 6. Price mismatch — PO price != Invoice price
            if inv and po_price != inv_price:
                result["price_mismatch"].append(
                    _item_result(code, po, grn, inv, f"PO price ({po_price}) != Invoice price ({inv_price})")
                )

        return result

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
