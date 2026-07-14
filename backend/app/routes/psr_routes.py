"""
API routes for PSR (handwritten Sales Invoice) extraction + amount matching.
Async job queue, PaddleOCR-only — no LLM. Mirrors the pipeline job API:
enqueue via POST (202 + job_id), poll via GET, cancel via POST.
"""
import os
import time
import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

from app.models import db, PsrJob
from app.config import MAX_UPLOAD_BYTES
from app.workers.psr_worker import _cancel_key

logger = logging.getLogger(__name__)

psr_bp = Blueprint('psr', __name__)

PSR_UPLOAD_FOLDER = 'uploads/psr/'
os.makedirs(PSR_UPLOAD_FOLDER, exist_ok=True)

# Magic-byte signatures for the document types OCR can actually read.
_IMAGE_MAGIC = (
    b"\xff\xd8\xff",            # JPEG
    b"\x89PNG\r\n\x1a\n",      # PNG
    b"GIF87a", b"GIF89a",      # GIF
    b"II*\x00", b"MM\x00*",    # TIFF
    b"BM",                      # BMP
)


def _looks_like_pdf_or_image(head: bytes) -> bool:
    """Cheap content sniff so we reject non-PDF/non-image uploads at the door."""
    if head[:5] == b"%PDF-":
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":   # WEBP
        return True
    return any(head.startswith(sig) for sig in _IMAGE_MAGIC)


@psr_bp.route('/api/psr/extract-and-match', methods=['POST'])
def psr_extract_and_match():
    """Enqueue a PSR extraction+match job. Returns 202 with a job_id to poll."""
    file = request.files.get('file') or request.files.get('image') or request.files.get('pdf')
    if not file or not file.filename:
        return jsonify({'error': "A PSR file is required (form-data key: 'file', 'image' or 'pdf')"}), 400

    # Guard size + type before saving/queuing.
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size == 0:
        return jsonify({'error': 'Uploaded file is empty'}), 400
    if size > MAX_UPLOAD_BYTES:
        return jsonify({'error': f'File too large ({size} bytes); max is {MAX_UPLOAD_BYTES} bytes'}), 400
    head = file.read(16)
    file.seek(0)
    if not _looks_like_pdf_or_image(head):
        return jsonify({'error': 'Unsupported file type; expected a PDF or image (PDF/JPEG/PNG/GIF/TIFF/BMP/WEBP)'}), 400

    original_filename = file.filename
    safe_name = secure_filename(original_filename)
    save_path = os.path.join(PSR_UPLOAD_FOLDER, f"{int(time.time())}_{safe_name}")
    file.save(save_path)

    # Optional: link a renamed upload back to its record by a supplied name.
    override_name = request.form.get('file_name') or None
    triggered_by = request.form.get('triggered_by', 'api')

    job = PsrJob(
        status='pending',
        triggered_by=triggered_by,
        file_path=save_path,
        original_filename=original_filename,
        override_name=override_name,
    )
    db.session.add(job)
    db.session.commit()

    logger.info(f"[PSR] Enqueued job #{job.id} (file={original_filename}, by {triggered_by})")

    return jsonify({
        'job_id': job.id,
        'status': job.status,
    }), 202


@psr_bp.route('/api/psr/job/<int:job_id>', methods=['GET'])
def get_psr_job(job_id):
    """Poll a PSR job's status; includes the reconciliation result when completed."""
    job = PsrJob.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    duration = None
    if job.started_at and job.completed_at:
        duration = round((job.completed_at - job.started_at).total_seconds(), 2)

    response = {
        'job_id': job.id,
        'status': job.status,
        'file_name': job.original_filename,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'completed_at': job.completed_at.isoformat() if job.completed_at else None,
        'duration_seconds': duration,
    }

    if job.status == 'completed':
        response['result'] = job.result_json or {}
    elif job.status in ('failed', 'cancelled'):
        response['error'] = job.error_message

    return jsonify(response), 200


@psr_bp.route('/api/psr/jobs', methods=['GET'])
def list_psr_jobs():
    """List recent PSR jobs (optionally filtered by status)."""
    status_filter = request.args.get('status')
    limit = min(int(request.args.get('limit', 50)), 200)

    query = PsrJob.query.order_by(PsrJob.created_at.desc())
    if status_filter:
        query = query.filter_by(status=status_filter)
    jobs = query.limit(limit).all()

    return jsonify([
        {
            'job_id': j.id,
            'status': j.status,
            'file_name': j.original_filename,
            'triggered_by': j.triggered_by,
            'created_at': j.created_at.isoformat() if j.created_at else None,
            'completed_at': j.completed_at.isoformat() if j.completed_at else None,
            'error': j.error_message if j.status in ('failed', 'cancelled') else None,
        }
        for j in jobs
    ]), 200


@psr_bp.route('/api/psr/job/<int:job_id>/cancel', methods=['POST'])
def cancel_psr_job(job_id):
    """Cancel a pending or running PSR job."""
    from app.cancel_registry import cancel_job as do_cancel

    job = PsrJob.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    if job.status not in ('pending', 'running'):
        return jsonify({
            'message': f'Job #{job_id} is already {job.status}, nothing to cancel.',
            'job_id': job_id,
            'status': job.status,
        }), 200

    if job.status == 'pending':
        job.status = 'cancelled'
        job.error_message = 'Cancelled by user before processing started.'
        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({
            'message': f'Job #{job_id} cancelled (was pending).',
            'job_id': job_id,
            'status': 'cancelled',
        }), 200

    found = do_cancel(_cancel_key(job_id))
    return jsonify({
        'message': (f'Cancel signal sent to job #{job_id}.' if found
                    else f"Job #{job_id} is 'running' but not in the active registry; it may have just finished."),
        'job_id': job_id,
        'status': 'cancelling' if found else job.status,
    }), 200
