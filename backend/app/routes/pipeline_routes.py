import os
import json
import time
import logging
from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename
from app.models import db, MatchJob

logger = logging.getLogger(__name__)

pipeline_bp = Blueprint('pipeline', __name__)

PIPELINE_UPLOAD_FOLDER = 'uploads/'
os.makedirs(PIPELINE_UPLOAD_FOLDER, exist_ok=True)

@pipeline_bp.route('/api/pipeline/extract-and-match', methods=['POST'])
def extract_and_match():
    file = request.files.get('file') or request.files.get('image')
    if not file or not file.filename:
        return jsonify({"error": "An invoice file is required (form-data key: 'file' or 'image')"}), 400

    raw_data = request.form.get('data')
    if not raw_data:
        return jsonify({"error": "A 'data' form field with the PO/GRN JSON envelope is required"}), 400
    try:
        envelope = json.loads(raw_data)
    except (ValueError, TypeError):
        return jsonify({"error": "The 'data' field is not valid JSON"}), 400
    if not isinstance(envelope, dict):
        return jsonify({"error": "The 'data' envelope must be a JSON object"}), 400

    po_number = (envelope.get('po_header') or {}).get('po_number')
    if po_number is None or str(po_number).strip() == '':
        return jsonify({"error": "po_header.po_number is required in the 'data' envelope"}), 400
    po_number = str(po_number).strip()

    po_lines = envelope.get('po_lines')
    if not isinstance(po_lines, list) or not po_lines:
        return jsonify({"error": "po_lines must be a non-empty list in the 'data' envelope"}), 400

    filename = secure_filename(file.filename)
    save_path = os.path.join(PIPELINE_UPLOAD_FOLDER, f"{int(time.time())}_{filename}")
    file.save(save_path)

    triggered_by = request.form.get('triggered_by', 'api')


    job = MatchJob(
        po_number=po_number,
        status='pending',
        triggered_by=triggered_by,
        job_type='extract_and_match',
        file_path=save_path,
        input_json=envelope,
    )
    db.session.add(job)
    db.session.commit()

    logger.info(
        f"[PIPELINE] Enqueued extract+match job #{job.id} for PO {po_number} "
        f"(file={filename}, by {triggered_by})"
    )

    return jsonify({
        "job_id": job.id,
        "po_number": job.po_number,
        "status": job.status,
        "job_type": job.job_type,
    }), 202

def _clean_raw_invoice(items):
    """As-extracted invoice lines, trimmed to the readable fields."""
    return [
        {
            "product_code": it.get("product_code"),
            "description":  it.get("desc"),
            "qty":          it.get("qty"),
            "price":        it.get("price"),
        }
        for it in items or []
    ]


def _clean_raw_po(items):
    return [
        {
            "product_code":      it.get("product_code"),
            "description":       it.get("desc"),
            "qty":               it.get("qty"),
            "price":             it.get("price"),
            "conversion_factor": it.get("conversion_factor"),
        }
        for it in items or []
    ]


def _clean_raw_grn(items):
    return [
        {
            "product_code": it.get("product_code"),
            "qty":          it.get("qty"),
            "grn_number":   it.get("grn_number"),
        }
        for it in items or []
    ]


def _build_desc_lookup(result):
    """Map product_code -> description, preferring the invoice's own wording
    (PO description is only a fallback for lines with no invoice, e.g. not_billed)."""
    lookup = {}
    for it in result.get("raw_po_items", []) or []:
        if it.get("desc"):
            lookup[it["product_code"]] = it["desc"]
    for it in result.get("raw_inv_items", []) or []:
        if it.get("desc"):
            lookup[it["product_code"]] = it["desc"]
    return lookup


def _format_match_result(result):
    """
    Turn the raw matcher output into a clean, grouped structure:
    a `summary` (status counts + total variances) and a list of `items`
    with quantity/price grouped per product. Returns {"summary", "items"}.
    """
    matches = result.get("matches", []) or []
    desc_lookup = _build_desc_lookup(result)

    # Order value totals, in billing units so PO and invoice are comparable:
    #   invoice line value  = billed qty (cases) x unit price
    #   PO line value       = (ordered qty / conversion_factor) x unit price
    total_invoice_amount = sum(
        float(it.get("qty") or 0) * float(it.get("price") or 0)
        for it in result.get("raw_inv_items", []) or []
    )
    total_po_amount = sum(
        (float(it.get("qty") or 0) / (float(it.get("conversion_factor") or 1) or 1))
        * float(it.get("price") or 0)
        for it in result.get("raw_po_items", []) or []
    )

    counts = {"matched": 0, "mismatch": 0, "not_billed": 0, "not_on_po": 0, "unmatched": 0}
    total_price_variance = 0.0
    total_qty_variance = 0.0
    items = []

    for m in matches:
        st = m.get("status")
        counts[st] = counts.get(st, 0) + 1
        total_price_variance += float(m.get("price_variance") or 0)
        total_qty_variance += float(m.get("qty_variance") or 0)

        # matched flags only mean anything when both sides exist (matched/mismatch)
        comparable = st in ("matched", "mismatch")
        qty_matched   = bool(m.get("is_qty_match"))   if comparable else False
        price_matched = bool(m.get("is_price_match")) if comparable else False

        item = {
            "product_code": m.get("product_code"),
            "description":  desc_lookup.get(m.get("product_code"), ""),
            "status":       st,
            "issue":        m.get("issue_summary"),
            "grn_number":   m.get("grn_number"),
            # Ordered to read left-to-right: ordered -> received -> billed -> derived
            "quantity": {
                "po_ordered":         m.get("po_qty"),
                "grn_received":       m.get("grn_qty"),
                "invoice":            m.get("invoice_qty_raw"),
                "conversion_factor":  m.get("conversion_factor"),
                "invoice_normalized": m.get("invoice_qty"),
                "variance":           m.get("qty_variance"),
                "matched":            qty_matched,
            },
            "price": {
                "po":       m.get("po_price"),
                "invoice":  m.get("invoice_price"),
                "variance": m.get("price_variance"),
                "matched":  price_matched,
            },
        }

        # Only surface the per-invoice breakdown when a PO was billed across
        # multiple partial invoices (otherwise it just duplicates the summary).
        lines = m.get("invoice_lines") or []
        if len(lines) > 1:
            item["invoice_breakdown"] = [
                {
                    "invoice_number": l.get("invoice_number"),
                    "qty":            l.get("qty"),
                    "normalized_qty": l.get("normalized_qty"),
                    "price":          l.get("price"),
                }
                for l in lines
            ]

        items.append(item)

    summary = {
        "total_items":          len(items),
        "matched":              counts["matched"],
        "mismatched":           counts["mismatch"],
        "not_billed":           counts["not_billed"],
        "not_on_po":            counts["not_on_po"],
        "unmatched":            counts["unmatched"],
        "all_clear":            bool(matches) and counts["mismatch"] == 0
                                and counts["not_on_po"] == 0 and counts["unmatched"] == 0,
        "total_po_amount":      round(total_po_amount, 2),
        "total_invoice_amount": round(total_invoice_amount, 2),
        "total_qty_variance":   round(total_qty_variance, 2),
        "total_price_variance": round(total_price_variance, 2),
    }
    return {"summary": summary, "matches": items}


@pipeline_bp.route('/api/pipeline/job/<int:job_id>', methods=['GET'])
def get_job_status(job_id):
    job = MatchJob.query.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    duration = None
    if job.started_at and job.completed_at:
        duration = round((job.completed_at - job.started_at).total_seconds(), 2)

    response = {
        "job_id": job.id,
        "po_number": job.po_number,
        "status": job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "duration_seconds": duration,
    }

    if job.status == 'completed':
        result = job.result_json or {}
        if result.get("status") == "success":
            formatted = _format_match_result(result)
            # Ordered for readability: summary -> matches -> raw invoice/po/grn
            response["summary"]     = formatted["summary"]
            response["matches"]     = formatted["matches"]
            response["raw_invoice"] = _clean_raw_invoice(result.get("raw_inv_items"))
            response["raw_po"]      = _clean_raw_po(result.get("raw_po_items"))
            response["raw_grn"]     = _clean_raw_grn(result.get("raw_grn_items"))
        else:
            # Matcher returned an error payload under a 'completed' job — surface it.
            response["error"] = result.get("error", "Unknown matching error")
    elif job.status == 'failed':
        response["error"] = job.error_message

    return jsonify(response), 200

@pipeline_bp.route('/api/pipeline/jobs', methods=['GET'])
def list_jobs():
    status_filter = request.args.get('status')
    po_filter = request.args.get('po_number')
    limit = min(int(request.args.get('limit', 50)), 200)

    query = MatchJob.query.order_by(MatchJob.created_at.desc())

    if status_filter:
        query = query.filter_by(status=status_filter)
    if po_filter:
        query = query.filter_by(po_number=str(po_filter).strip())

    jobs = query.limit(limit).all()

    return jsonify([
        {
            "job_id": j.id,
            "po_number": j.po_number,
            "status": j.status,
            "triggered_by": j.triggered_by,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "error": j.error_message if j.status == 'failed' else None,
        }
        for j in jobs
    ]), 200


@pipeline_bp.route('/api/pipeline/job/<int:job_id>/cancel', methods=['POST'])
def cancel_job(job_id):
    """Cancel a specific running job by ID."""
    from app.cancel_registry import cancel_job as do_cancel, active_job_ids

    job = MatchJob.query.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job.status not in ('pending', 'running'):
        return jsonify({
            "message": f"Job #{job_id} is already {job.status}, nothing to cancel.",
            "job_id": job_id,
            "status": job.status,
        }), 200

    # If pending (not yet picked up by worker), mark cancelled directly
    if job.status == 'pending':
        job.status = 'cancelled'
        job.error_message = 'Cancelled by user before processing started.'
        from datetime import datetime, timezone
        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({
            "message": f"Job #{job_id} cancelled (was pending).",
            "job_id": job_id,
            "status": "cancelled",
        }), 200

    # Running — signal the cancel event
    found = do_cancel(job_id)
    if found:
        return jsonify({
            "message": f"Cancel signal sent to job #{job_id}. It will stop at the next checkpoint.",
            "job_id": job_id,
            "status": "cancelling",
            "active_jobs": active_job_ids(),
        }), 200
    else:
        return jsonify({
            "message": f"Job #{job_id} is marked 'running' but not found in the active registry. It may have just finished.",
            "job_id": job_id,
        }), 200


@pipeline_bp.route('/api/pipeline/cancel-all', methods=['POST'])
def cancel_all_jobs():
    """Cancel ALL running and pending jobs immediately."""
    from app.cancel_registry import cancel_all as do_cancel_all, active_job_ids
    from datetime import datetime, timezone

    # Cancel pending jobs in the DB directly
    pending_jobs = MatchJob.query.filter_by(status='pending').all()
    for j in pending_jobs:
        j.status = 'cancelled'
        j.error_message = 'Cancelled by user (cancel-all).'
        j.completed_at = datetime.now(timezone.utc)
    db.session.commit()

    # Signal all running jobs to stop
    signalled = do_cancel_all()

    return jsonify({
        "message": f"Cancel-all signal sent. {len(pending_jobs)} pending job(s) cancelled, {signalled} running job(s) signalled.",
        "pending_cancelled": len(pending_jobs),
        "running_signalled": signalled,
        "active_jobs": active_job_ids(),
    }), 200

