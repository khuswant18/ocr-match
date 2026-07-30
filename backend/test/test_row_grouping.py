"""Tests for _group_item_words_into_rows() — monotonic DP alignment.

Case 1: Misaligned boxes (original EL RANCHO / VIRGINIA bug).
Case 2: Missing token in one column (Apple/Banana/Orange).
Case 3: Arithmetic-disambiguated alignment (equidistant quantities).

Also tests helper functions: _arithmetic_check, _monotonic_assign,
and the _dp_row marker that prevents false continuation merges.
"""

import sys
import os

# Allow importing from the backend app without installing it
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "app")
)

from parsers.layoutlm_parser import (
    _group_item_words_into_rows,
    _arithmetic_check,
    _monotonic_assign,
)


# ────────────────────────────────────────────────────────────────
# Case 1 — EL RANCHO / VIRGINIA  (misaligned boxes, no missing tokens)
#
# Layout: two items on an invoice.  The numeric boxes for row 1 are
# OCR'd slightly LOW (closer in y to row 2's description), which
# used to cause the nearest-neighbour approach to assign them to
# the wrong row.
#
# Row 1:  EL RANCHO MEATS  qty=5   unit_price=481.00  total=2405.00
# Row 2:  VIRGINIA CHINESE  qty=10  unit_price=600.00  total=6000.00
#
# Description y_centers:  row1 ≈ 400, row2 ≈ 500
# Row 1's numeric boxes are shifted down to y ≈ 460 (closer to
# row 2 desc at 500 than row 1 desc at 400 — only 40 vs 60 apart)
# Row 2's numeric boxes sit at y ≈ 510 (close to their own desc).
# ────────────────────────────────────────────────────────────────
CASE1_ITEM_WORDS = [
    # Descriptions
    {"word": "EL RANCHO MEATS",    "label": "ITEM_DESCRIPTION", "box": [50, 380, 300, 420]},
    {"word": "VIRGINIA CHINESE",   "label": "ITEM_DESCRIPTION", "box": [50, 480, 300, 520]},
    # Row 1 numerics — shifted DOWN to y_center ≈ 460 (misaligned)
    {"word": "5",       "label": "QUANTITY",    "box": [400, 445, 430, 475]},
    {"word": "481.00",  "label": "UNIT_PRICE",  "box": [500, 445, 570, 475]},
    {"word": "2,405.00","label": "LINE_AMOUNT", "box": [650, 445, 750, 475]},
    # Row 2 numerics — at y_center ≈ 510 (aligned with their own desc)
    {"word": "10",      "label": "QUANTITY",    "box": [400, 495, 430, 525]},
    {"word": "600.00",  "label": "UNIT_PRICE",  "box": [500, 495, 570, 525]},
    {"word": "6,000.00","label": "LINE_AMOUNT", "box": [650, 495, 750, 525]},
]


def test_case1_misaligned_boxes():
    """Misaligned OCR boxes must still be assigned to the correct row
    by monotonic ordering, not nearest-neighbour y-distance."""
    items = _group_item_words_into_rows(CASE1_ITEM_WORDS)

    assert len(items) == 2, f"Expected 2 items, got {len(items)}"

    # Items should be sorted by y — EL RANCHO first, VIRGINIA second
    el_rancho = items[0]
    virginia  = items[1]

    assert "EL RANCHO" in el_rancho["description"]
    assert "VIRGINIA"  in virginia["description"]

    # EL RANCHO: qty=5, unit_price=481, total=2405
    assert el_rancho["quantity"]    == 5
    assert el_rancho["unit_price"]  == 481.0
    assert el_rancho["total_price"] == 2405.0

    # VIRGINIA: qty=10, unit_price=600, total=6000
    assert virginia["quantity"]    == 10
    assert virginia["unit_price"]  == 600.0
    assert virginia["total_price"] == 6000.0

    # Sum check from the user's spec
    total_sum = sum(it["total_price"] for it in items)
    assert total_sum == 8405.0, f"Expected total sum 8405.00, got {total_sum}"

    # Neither should be low confidence (arithmetic is consistent)
    assert "_low_confidence" not in el_rancho
    assert "_low_confidence" not in virginia


# ────────────────────────────────────────────────────────────────
# Case 2 — Apple / Banana / Orange  (missing QUANTITY in middle column)
#
# 3 descriptions, LINE_AMOUNT values [10, 30] with the middle one
# (Banana's 20) missing from OCR entirely.
# DP should assign 10 → Apple (slot 0) and 30 → Orange (slot 2),
# leaving Banana's slot empty — NOT shifting 30 up to Banana.
# ────────────────────────────────────────────────────────────────
CASE2_ITEM_WORDS = [
    # Descriptions at y = 100, 200, 300
    {"word": "Apple",  "label": "ITEM_DESCRIPTION", "box": [50, 90, 200, 110]},
    {"word": "Banana", "label": "ITEM_DESCRIPTION", "box": [50, 190, 200, 210]},
    {"word": "Orange", "label": "ITEM_DESCRIPTION", "box": [50, 290, 200, 310]},
    # LINE_AMOUNT: only 2 values — 10 near y=100 and 30 near y=300
    # (Banana's 20 at y≈200 is missing from OCR)
    {"word": "10",  "label": "LINE_AMOUNT", "box": [600, 92, 680, 108]},
    {"word": "30",  "label": "LINE_AMOUNT", "box": [600, 292, 680, 308]},
]


def test_case2_missing_token_no_cascade():
    """A missing token in one column must NOT cascade values downward.
    Banana should get 0 (empty), not 30."""
    items = _group_item_words_into_rows(CASE2_ITEM_WORDS)

    assert len(items) == 3, f"Expected 3 items, got {len(items)}"

    apple  = items[0]
    banana = items[1]
    orange = items[2]

    assert "Apple"  in apple["description"]
    assert "Banana" in banana["description"]
    assert "Orange" in orange["description"]

    assert apple["total_price"]  == 10.0, f"Apple total_price: {apple['total_price']}"
    assert orange["total_price"] == 30.0, f"Orange total_price: {orange['total_price']}"
    # Banana's LINE_AMOUNT was missing from OCR → should be 0, not 30
    assert banana["total_price"] == 0.0, (
        f"Banana total_price should be 0 (missing), got {banana['total_price']}"
    )


# ────────────────────────────────────────────────────────────────
# Case 3 — Arithmetic-disambiguated alignment
#
# Two adjacent rows where each row's QUANTITY box sits almost
# exactly equidistant between the two descriptions, but only one
# ordering of qty→row satisfies qty×price=amount for both rows.
#
# Row 1 (Widget):  qty=3,  unit_price=100,  total=300
# Row 2 (Gadget):  qty=5,  unit_price=200,  total=1000
#
# The QTY boxes are placed at y-centers 250 and 252 — both nearly
# equidistant between desc y=200 and desc y=300.  The DP alone
# could assign either way (similar cost).  The arithmetic swap
# correction picks the ordering where 3×100=300 and 5×200=1000.
# ────────────────────────────────────────────────────────────────
CASE3_ITEM_WORDS = [
    # Descriptions
    {"word": "Widget", "label": "ITEM_DESCRIPTION", "box": [50, 185, 200, 215]},   # y_center=200
    {"word": "Gadget", "label": "ITEM_DESCRIPTION", "box": [50, 285, 200, 315]},   # y_center=300
    # QTY boxes — both near the midpoint y≈250 (equidistant from both descs)
    {"word": "3",  "label": "QUANTITY", "box": [400, 240, 430, 260]},   # y_center=250
    {"word": "5",  "label": "QUANTITY", "box": [400, 242, 430, 262]},   # y_center=252
    # UNIT_PRICE — clearly placed near their own description
    {"word": "100.00",  "label": "UNIT_PRICE", "box": [500, 192, 570, 218]},  # y_center=205
    {"word": "200.00",  "label": "UNIT_PRICE", "box": [500, 292, 570, 318]},  # y_center=305
    # LINE_AMOUNT — clearly placed near their own description
    {"word": "300.00",  "label": "LINE_AMOUNT", "box": [650, 192, 740, 218]},  # y_center=205
    {"word": "1,000.00","label": "LINE_AMOUNT", "box": [650, 292, 740, 318]},  # y_center=305
]


def test_case3_arithmetic_disambiguation():
    """When distance alone is ambiguous, arithmetic consistency (qty × price = amount)
    must resolve the correct assignment."""
    items = _group_item_words_into_rows(CASE3_ITEM_WORDS)

    assert len(items) == 2, f"Expected 2 items, got {len(items)}"

    widget = items[0]
    gadget = items[1]

    assert "Widget" in widget["description"]
    assert "Gadget" in gadget["description"]

    # Only one ordering satisfies arithmetic for BOTH rows:
    #   Widget: 3 × 100 = 300  ✓
    #   Gadget: 5 × 200 = 1000 ✓
    assert widget["quantity"]    == 3,      f"Widget qty: {widget['quantity']}"
    assert widget["unit_price"]  == 100.0,  f"Widget unit_price: {widget['unit_price']}"
    assert widget["total_price"] == 300.0,  f"Widget total_price: {widget['total_price']}"

    assert gadget["quantity"]    == 5,      f"Gadget qty: {gadget['quantity']}"
    assert gadget["unit_price"]  == 200.0,  f"Gadget unit_price: {gadget['unit_price']}"
    assert gadget["total_price"] == 1000.0, f"Gadget total_price: {gadget['total_price']}"

    # Both rows should pass arithmetic — no low_confidence flags
    assert "_low_confidence" not in widget
    assert "_low_confidence" not in gadget


# ────────────────────────────────────────────────────────────────
# Extra unit tests for helpers
# ────────────────────────────────────────────────────────────────

def test_arithmetic_check_basic():
    """Sanity checks for _arithmetic_check."""
    assert _arithmetic_check(5, 100, 500) is True       # exact match
    assert _arithmetic_check(5, 100, 500.005) is True    # within 1%
    assert _arithmetic_check(5, 100, 600) is False       # way off
    assert _arithmetic_check(0, 100, 500) is True        # missing qty → pass
    assert _arithmetic_check(5, 0, 500) is True          # missing price → pass
    assert _arithmetic_check(5, 100, 0) is True          # missing amount → pass


def test_monotonic_assign_fewer_values_than_slots():
    """DP should leave the middle slot empty when the value is missing."""
    values = [
        {"_y_center": 100},
        {"_y_center": 300},
    ]
    slots_y = [100, 200, 300]
    result = _monotonic_assign(values, slots_y)
    # value 0 → slot 0, value 1 → slot 2, slot 1 is None
    assert result == [0, None, 1], f"Got {result}"


def test_monotonic_assign_equal_count():
    """When M == N, every slot should get a value."""
    values = [
        {"_y_center": 105},
        {"_y_center": 205},
        {"_y_center": 295},
    ]
    slots_y = [100, 200, 300]
    result = _monotonic_assign(values, slots_y)
    assert result == [0, 1, 2], f"Got {result}"


def test_low_confidence_flag():
    """Rows with all three values present but inconsistent arithmetic
    should be tagged with _low_confidence."""
    words = [
        {"word": "Item A",  "label": "ITEM_DESCRIPTION", "box": [50, 90, 200, 110]},
        {"word": "7",       "label": "QUANTITY",          "box": [400, 92, 430, 108]},
        {"word": "100.00",  "label": "UNIT_PRICE",        "box": [500, 92, 570, 108]},
        # LINE_AMOUNT is 999 — obviously wrong: 7 × 100 ≠ 999
        {"word": "999.00",  "label": "LINE_AMOUNT",       "box": [650, 92, 740, 108]},
    ]
    items = _group_item_words_into_rows(words)
    assert len(items) == 1
    assert items[0].get("_low_confidence") is True


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
