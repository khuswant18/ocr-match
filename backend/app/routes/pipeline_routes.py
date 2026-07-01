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

@pipeline_bp.route('/api/pipeline/job/<int:job_id>', methods=['GET'])
def get_job_status(job_id):
    job = MatchJob.query.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    response = {
        "job_id": job.id,
        "po_number": job.po_number,
        "status": job.status,
        "triggered_by": job.triggered_by,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }

    if job.status == 'completed':
        response["result"] = job.result_json
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
