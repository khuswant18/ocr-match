# Batch Test Comparison Report: Before vs After Fixes

**100 PNG invoices** | OCR + LayoutLMv3 pipeline | No LLM

---

## Summary Comparison

| Metric | Before | After | Change |
|---|---|---|---|
| **Success Rate** | 99/100 | 99/100 | — |
| **Avg Time/Invoice** | 8.8s | 8.8s | — |
| **OCR Confidence** | 95.2% | 95.2% | — |

---

## Fix Results

### Fix 1: PO Number Cleaning ✅

**50 invoices cleaned** — every noisy PO number is now a clean 7-digit number.

| Before | After |
|---|---|
| `SHIPPING INSTRUCTIONS:PO:4387858MFL` | `4387858` |
| `PO:VFI-4019321FGL` | `4019321` |
| `SHIPPING INSTRUCTI@NS4018304MCL` | `4018304` |
| `4017883MCL` | `4017883` |
| `PO:4017756MCL` | `4017756` |
| `SHIPPING INSTRUCTIONSPO4400787MFL22` | `4400787` |

**Remaining noisy PO numbers: 0** ✅

---

### Fix 2: Supplier/Buyer Name Deduplication ✅

**44 supplier names deduped, 20 buyer names deduped** — all duplicates eliminated.

| Before | After |
|---|---|
| `VIRGINIA FOOD, INC. VIRGINIA FOOD,INC.` | `VIRGINIA FOOD, INC.` |
| `VIRGINIA FOOD, INC. VIRGINIAFOODINC.125465` | `VIRGINIA FOOD, INC.` |
| `PRINCEPAN CORPORATION PRINCEPAN CORPORATION-POTOTAN` | `PRINCEPAN CORPORATION-POTOTAN` |
| `PRINCEGATE CORPORATIONVAT REG. TIN:...` | `PRINCEGATE CORPORATION` |

**Remaining supplier duplicates: 0** ✅
**Remaining buyer duplicates: 0** ✅

---

### Fix 3: Financial Field Deduplication ✅

**47 financial fields cleaned** — duplicate/concatenated amounts resolved to single values.

| Field | Before | After |
|---|---|---|
| total_amount | `45,345.29 45,345.29` | `45,345.29` |
| total_amount | `14,736.00 13,719.21` | `13,719.21` (net after discount) |
| total_amount | `124.20 1,875.80` | `1,875.80` |
| discount | `701.75 133.66` | `133.66` |
| subtotal | `20,720.00 16,650.00` | `16,650.00` |

---

### Fix 4: Split-Row Item Merging ✅

**135 continuation rows merged** — items with description-only second rows are now combined with their parent.

| Metric | Before | After | Change |
|---|---|---|---|
| **Total Items** | 628 | 493 | -135 (merged) |
| **Items with Qty** | 477/628 (**76.0%**) | 477/493 (**96.8%**) | **+20.8pp** ⬆️ |
| **Items with Price** | 471/628 (**75.0%**) | 471/493 (**95.5%**) | **+20.5pp** ⬆️ |
| **Items with Desc** | 628/628 (100%) | 493/493 (100%) | — |

> [!NOTE]
> The 3857xxx MELAND TOYS series (25 invoices × 5 continuation rows each = 125 merges) was the biggest contributor. Items now correctly read:
> - Before: `F0195 KIDS SLING BAG` (qty=6, price=69) + `|12 OPP/HC80195 (1 X 480 pcs)` (qty=0, price=0)
> - After: `F0195 KIDS SLING BAG |12 OPP/HC80195 (1 X 480 pcs)` (qty=6, price=69) ← single merged item

---

### Fix 5: Invoice Number Barcode Filter ✅

**36 invoice numbers cleaned, 17 barcodes removed.**

| Type | Before | After |
|---|---|---|
| Real invoice | `No.78715` | `78715` (cleaned) |
| Real invoice | `No.1345892` | `1345892` (cleaned) |
| Barcode | `000092300924` | `` (removed) |
| Barcode | `0009460046006` | `` (removed) |
| Barcode | `037787878718` | `` (removed) |

> [!IMPORTANT]
> The invoice_number extraction rate dropped from 62.6% to 45.5% because 17 barcodes were correctly removed. The remaining 45 invoices with invoice numbers now have **clean, accurate values**.

---

## Field Extraction Rates (After Fixes)

| Field | Rate | Note |
|---|---|---|
| **Supplier Name** | 99/99 (100%) ✅ | Clean, no duplicates |
| **Buyer Name** | 97/99 (98%) ✅ | Clean, no duplicates |
| **Invoice Date** | 95/99 (96%) ✅ | |
| **PO Number** | 86/99 (87%) ✅ | All clean 7-digit numbers |
| **Subtotal** | 79/99 (80%) | No more duplicates |
| **Buyer TIN** | 74/99 (75%) | |
| **Supplier TIN** | 64/99 (65%) | |
| **SO Number** | 61/99 (62%) | |
| **Discount** | 53/99 (54%) | No more duplicates |
| **Terms** | 53/99 (54%) | |
| **Total Amount** | 52/99 (53%) | No more duplicates |
| **Invoice Number** | 45/99 (45%) | Clean values only (barcodes removed) |

---

## Remaining Issues (Require LayoutLMv3 Retraining)

These cannot be fixed with code and need labeling improvements:

| Issue | Invoices Affected | Fix |
|---|---|---|
| MELAND TOYS: no invoice_number extracted | 25 | Add MELAND layout to training data |
| MELAND TOYS: no total_amount extracted | 25 | Label total_amount position in training |
| ~16 items still missing qty | 16/493 (3.2%) | Improve QUANTITY label accuracy |
| ~22 items still missing price | 22/493 (4.5%) | Improve UNIT_PRICE/LINE_AMOUNT labels |
| Some invoices missing total_amount | 47/99 | Label TOTAL_AMOUNT more consistently |

---

> Raw reports: [before](file:///Users/khuswant/Desktop/ocr-match/test_report_before_fixes.json) | [after](file:///Users/khuswant/Desktop/ocr-match/test_report.json)
