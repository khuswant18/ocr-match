#!/usr/bin/env python3
"""
Batch test: send every PNG in all_invoices/ to the /paddleOCR endpoint
and collect the results into a JSON report.

Usage:  python test_all_invoices.py
Output: test_report.json  (in the same directory)
"""

import json
import os
import statistics
import sys
import time
from collections import Counter

import requests

API_URL = "http://localhost:4333/paddleOCR"
INVOICES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "all_invoices")
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_report.json")

# Set QUALITY_BYPASS_TOKEN to the same value as in backend/.env so the gate
# scores and logs every document but never parks one. This harness measures
# EXTRACTION quality; being blocked by the gate under test would turn a
# working gate into an apparent regression.
BYPASS_TOKEN = os.environ.get("QUALITY_BYPASS_TOKEN", "").strip()
HEADERS = {"X-Quality-Bypass": BYPASS_TOKEN} if BYPASS_TOKEN else {}


def _quality_fields(data):
    """Pull the quality report out of a response, flattened for analysis."""
    quality = data.get("quality") or {}
    metrics = quality.get("metrics") or {}
    return {
        "quality_score": quality.get("score"),
        "quality_tier": quality.get("tier"),
        "quality_status": data.get("status"),
        "quality_issues": [i.get("code") for i in quality.get("issues", [])],
        "quality_metrics": {k: v.get("score") for k, v in metrics.items()},
        "quality_raw": {k: v.get("raw") for k, v in metrics.items()},
    }


def test_one(filepath):
    fname = os.path.basename(filepath)
    print(f"  Testing: {fname} ... ", end="", flush=True)
    t0 = time.time()
    try:
        with open(filepath, "rb") as f:
            resp = requests.post(API_URL, files={"file": (fname, f, "image/png")},
                                 headers=HEADERS, timeout=300)
        elapsed = round(time.time() - t0, 2)

        if resp.status_code != 200:
            print(f"FAIL ({resp.status_code}) [{elapsed}s]")
            return {
                "file": fname,
                "status": "error",
                "http_status": resp.status_code,
                "error": resp.text[:500],
                "elapsed_s": elapsed,
            }

        data = resp.json()

        # A hold is a 200 with no parsed_data. Count it as its own bucket
        # rather than letting the field extraction below raise on None.
        if data.get("status") == "quality_hold":
            quality = data.get("quality") or {}
            print(f"HELD  score={quality.get('score')} "
                  f"issues={[i.get('code') for i in quality.get('issues', [])]} "
                  f"[{elapsed}s]")
            return {
                "file": fname,
                "status": "held",
                "elapsed_s": elapsed,
                **_quality_fields(data),
            }

        parsed = data.get("parsed_data") or {}
        items = parsed.get("items", [])

        has_invoice_num = bool(parsed.get("invoice_number", "").strip())
        has_po = bool(parsed.get("po_number", "").strip())
        has_date = bool(parsed.get("invoice_date", "").strip())
        has_supplier = bool((parsed.get("supplier") or {}).get("name", "").strip())
        has_buyer = bool((parsed.get("buyer") or {}).get("name", "").strip())
        has_total = bool((parsed.get("financials") or {}).get("total_amount", "").strip())
        has_subtotal = bool((parsed.get("financials") or {}).get("subtotal", "").strip())

        items_with_desc = sum(1 for it in items if it.get("description", "").strip())
        items_with_qty = sum(1 for it in items if it.get("quantity", 0) not in (0, 0.0))
        items_with_price = sum(1 for it in items if it.get("unit_price", 0) not in (0, 0.0))
        items_with_total = sum(1 for it in items if it.get("total_price", 0) not in (0, 0.0))

        fields_found = sum([has_invoice_num, has_po, has_date, has_supplier, has_buyer, has_total])

        print(f"OK  fields={fields_found}/6  items={len(items)} (desc={items_with_desc} qty={items_with_qty} price={items_with_price}) [{elapsed}s]")

        return {
            "file": fname,
            "status": "ok",
            "elapsed_s": elapsed,
            "ocr_confidence": data.get("average_confidence", 0),
            "recognition_time": data.get("time", {}).get("recognition", 0),
            "parsing_time": data.get("time", {}).get("parsing", 0),
            "fields": {
                "invoice_number": parsed.get("invoice_number", ""),
                "po_number": parsed.get("po_number", ""),
                "invoice_date": parsed.get("invoice_date", ""),
                "so_number": parsed.get("so_number", ""),
                "terms": parsed.get("terms", ""),
                "supplier_name": (parsed.get("supplier") or {}).get("name", ""),
                "supplier_tin": (parsed.get("supplier") or {}).get("tin", ""),
                "buyer_name": (parsed.get("buyer") or {}).get("name", ""),
                "buyer_tin": (parsed.get("buyer") or {}).get("tin", ""),
                "subtotal": (parsed.get("financials") or {}).get("subtotal", ""),
                "discount": (parsed.get("financials") or {}).get("discount", ""),
                "total_amount": (parsed.get("financials") or {}).get("total_amount", ""),
            },
            "header_fields_found": fields_found,
            "items_count": len(items),
            "items_with_description": items_with_desc,
            "items_with_qty": items_with_qty,
            "items_with_price": items_with_price,
            "items_with_total_price": items_with_total,
            "items": items,
            **_quality_fields(data),
        }

    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        print(f"EXCEPTION: {e} [{elapsed}s]")
        return {
            "file": fname,
            "status": "exception",
            "error": str(e),
            "elapsed_s": elapsed,
        }


def _percentiles(values):
    if not values:
        return {}
    vals = sorted(values)

    def at(p):
        return round(vals[min(len(vals) - 1, int(len(vals) * p / 100))], 2)

    return {"min": round(vals[0], 2), "p5": at(5), "p10": at(10), "p25": at(25),
            "median": at(50), "p75": at(75), "max": round(vals[-1], 2)}


def _quality_summary(results):
    """Distribution of quality scores across the corpus.

    This is the tuning instrument. These invoices are the KNOWN-GOOD
    population, so anything scoring 'low' here is a false positive and the
    anchors in backend/app/ocr/quality.py need loosening. `issue_frequency`
    names the culprit metric directly.
    """
    scored = [r for r in results if r.get("quality_score") is not None]
    if not scored:
        return {"assessed": 0,
                "note": "No quality data in responses - gate disabled?"}

    tiers = Counter(r.get("quality_tier") for r in scored)
    issues = Counter(c for r in scored for c in (r.get("quality_issues") or []))

    per_metric = {}
    for name in (scored[0].get("quality_metrics") or {}):
        vals = [r["quality_metrics"][name] for r in scored
                if (r.get("quality_metrics") or {}).get(name) is not None]
        per_metric[name] = _percentiles(vals)

    # The only real validation of the weights: a quality score that does not
    # track field-extraction success is measuring the wrong thing. Both halves
    # are already computed, so this is free.
    correlation = None
    paired = [(r["quality_score"], r["header_fields_found"]) for r in scored
              if r.get("header_fields_found") is not None]
    if len(paired) > 2:
        xs = [p[0] for p in paired]
        ys = [float(p[1]) for p in paired]
        try:
            correlation = round(statistics.correlation(xs, ys), 3)
        except (AttributeError, statistics.StatisticsError):
            correlation = None

    return {
        "assessed": len(scored),
        "tier_counts": dict(tiers),
        "score_percentiles": _percentiles([r["quality_score"] for r in scored]),
        "issue_frequency": dict(issues.most_common()),
        "per_metric_percentiles": per_metric,
        "score_vs_header_fields_correlation": correlation,
    }


def main():
    pngs = sorted([
        os.path.join(INVOICES_DIR, f)
        for f in os.listdir(INVOICES_DIR)
        if f.lower().endswith(".png")
    ])

    print(f"\nFound {len(pngs)} PNG invoices in {INVOICES_DIR}")
    print(f"API endpoint: {API_URL}\n")
    print("=" * 80)

    results = []
    for i, fpath in enumerate(pngs, 1):
        print(f"[{i}/{len(pngs)}]", end="")
        result = test_one(fpath)
        results.append(result)

    print("\n" + "=" * 80)

    ok = [r for r in results if r["status"] == "ok"]
    held = [r for r in results if r["status"] == "held"]
    errors = [r for r in results if r["status"] not in ("ok", "held")]
    total_time = sum(r["elapsed_s"] for r in results)
    avg_confidence = sum(r.get("ocr_confidence", 0) for r in ok) / len(ok) if ok else 0

    field_keys = ["invoice_number", "po_number", "invoice_date", "supplier_name", "buyer_name", "total_amount", "subtotal", "discount", "supplier_tin", "buyer_tin", "so_number", "terms"]
    field_rates = {}
    for key in field_keys:
        count = sum(1 for r in ok if r["fields"].get(key, "").strip())
        field_rates[key] = {"count": count, "total": len(ok), "rate": round(count / len(ok) * 100, 1) if ok else 0}

    total_items = sum(r.get("items_count", 0) for r in ok)
    items_with_desc = sum(r.get("items_with_description", 0) for r in ok)
    items_with_qty = sum(r.get("items_with_qty", 0) for r in ok)
    items_with_price = sum(r.get("items_with_price", 0) for r in ok)
    items_with_total_price = sum(r.get("items_with_total_price", 0) for r in ok)

    summary = {
        "total_invoices": len(pngs),
        "successful": len(ok),
        "held": len(held),
        "failed": len(errors),
        "total_time_s": round(total_time, 1),
        "avg_time_per_invoice_s": round(total_time / len(pngs), 1) if pngs else 0,
        "avg_ocr_confidence": round(avg_confidence, 1),
        "field_extraction_rates": field_rates,
        "item_stats": {
            "total_items_extracted": total_items,
            "items_with_description": items_with_desc,
            "items_with_quantity": items_with_qty,
            "items_with_unit_price": items_with_price,
            "items_with_total_price": items_with_total_price,
            "desc_rate": round(items_with_desc / total_items * 100, 1) if total_items else 0,
            "qty_rate": round(items_with_qty / total_items * 100, 1) if total_items else 0,
            "price_rate": round(items_with_price / total_items * 100, 1) if total_items else 0,
        },
    }

    summary["quality"] = _quality_summary(results)

    report = {
        "summary": summary,
        "results": results,
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\nSUMMARY")
    print(f"  Total: {len(pngs)} | OK: {len(ok)} | Held: {len(held)} | Failed: {len(errors)}")
    if not BYPASS_TOKEN:
        print("  NOTE: QUALITY_BYPASS_TOKEN is unset, so the gate can hold "
              "invoices and skew these rates.")
    print(f"  Total time: {total_time:.1f}s | Avg: {total_time/len(pngs):.1f}s per invoice")
    print(f"  Avg OCR confidence: {avg_confidence:.1f}%")
    print(f"\n  Field extraction rates:")
    for key, val in field_rates.items():
        print(f"    {key:20s}: {val['count']:3d}/{val['total']:3d} ({val['rate']:.1f}%)")
    print(f"\n  Item extraction:")
    print(f"    Total items:     {total_items}")
    print(f"    With description: {items_with_desc} ({summary['item_stats']['desc_rate']:.1f}%)")
    print(f"    With quantity:    {items_with_qty} ({summary['item_stats']['qty_rate']:.1f}%)")
    print(f"    With unit_price:  {items_with_price} ({summary['item_stats']['price_rate']:.1f}%)")

    q = summary.get("quality") or {}
    if q.get("assessed"):
        print(f"\n  Quality assessment ({q['assessed']} scored):")
        print(f"    Tiers: {q['tier_counts']}")
        pct = q["score_percentiles"]
        print(f"    Score: min={pct['min']} p5={pct['p5']} median={pct['median']} "
              f"max={pct['max']}")
        if q["issue_frequency"]:
            print(f"    Issues: {q['issue_frequency']}")
        if q.get("score_vs_header_fields_correlation") is not None:
            print(f"    Correlation with header fields found: "
                  f"{q['score_vs_header_fields_correlation']}")
        low = q["tier_counts"].get("low", 0)
        if low:
            print(f"    WARNING: {low} known-good invoice(s) scored 'low'. "
                  f"These are false positives - loosen the anchors in "
                  f"backend/app/ocr/quality.py before arming the gate.")

    if held:
        print(f"\n  HELD INVOICES:")
        for r in held:
            print(f"    {r['file']}: score={r.get('quality_score')} "
                  f"{r.get('quality_issues')}")

    if errors:
        print(f"\n  FAILED INVOICES:")
        for r in errors:
            print(f"    {r['file']}: {str(r.get('error', 'unknown'))[:100]}")

    print(f"\nFull report saved to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
