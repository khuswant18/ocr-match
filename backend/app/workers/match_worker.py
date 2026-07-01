import logging
import threading
import time
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

POLL_INTERVAL = 2

def _run_extraction_via_http(file_path, po_number):
    """
    Trigger OCR extraction by calling the /paddleOCR endpoint internally.
    PaddleOCR is NOT thread-safe, so we must call it via HTTP on the main
    Flask thread rather than invoking it directly from the worker thread.
    """
    import requests as req

    backend_port = os.environ.get("FLASK_PORT", "4333")
    url = f"http://127.0.0.1:{backend_port}/paddleOCR"

    with open(file_path, 'rb') as f:
        files = {'file': (os.path.basename(file_path), f)}
        data = {'po_number': po_number}
        resp = req.post(url, files=files, data=data, timeout=120)

    if resp.status_code != 200:
        error_detail = resp.json().get('error', resp.text) if resp.headers.get('content-type', '').startswith('application/json') else resp.text
        raise ValueError(f"OCR extraction failed (HTTP {resp.status_code}): {error_detail}")

    result = resp.json()
    if 'error' in result:
        raise ValueError(f"OCR extraction error: {result['error']}")

    return result.get('invoice_id'), result.get('parsed_data')

def _process_one_job(app):
    """
    Claim the oldest pending job, execute it, and store the result.
    Returns True if a job was processed, False if the queue was empty.
    """
    with app.app_context():
        from app.models import db, MatchJob
        from app.services.matching_service import run_three_way_match, run_match_from_payload

        job = (
            MatchJob.query
            .filter_by(status='pending')
            .order_by(MatchJob.created_at.asc())
            .first()
        )
        if not job:
            return False

        job.status = 'running'
        job.started_at = datetime.now(timezone.utc)
        db.session.commit()
        logger.info(f"[WORKER] Processing job #{job.id} (type={job.job_type}) for PO {job.po_number}")

        try:
            if job.job_type == 'extract_and_match' and job.file_path:
                invoice_id, parsed_data = _run_extraction_via_http(job.file_path, job.po_number)
                logger.info(f"[WORKER] Extraction done for job #{job.id}, invoice_id={invoice_id}")

                env = job.input_json or {}
                result = run_match_from_payload(
                    job.po_number,
                    env.get("po_lines"),
                    env.get("pol_grn"),
                    parsed_data,
                    invoice_id,
                )
            else:
                result = run_three_way_match(job.po_number)

            if "error" in result:
                job.status = 'failed'
                job.error_message = result["error"]
                logger.warning(f"[WORKER] Job #{job.id} failed: {result['error']}")
            else:
                job.status = 'completed'
                job.result_json = result
                logger.info(f"[WORKER] Job #{job.id} completed successfully")

        except Exception as e:
            job.status = 'failed'
            job.error_message = str(e)
            logger.error(f"[WORKER] Job #{job.id} crashed: {e}")

        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return True

def _worker_loop(app):
    logger.info("[WORKER] Match worker started.")
    while True:
        try:
            had_work = _process_one_job(app)
            if not had_work:
                time.sleep(POLL_INTERVAL)
        except Exception as e:
            logger.error(f"[WORKER] Unexpected error in worker loop: {e}")
            time.sleep(POLL_INTERVAL * 5)

def start_match_worker(app):
    """
    Launch the worker as a daemon thread.
    Called once during Flask app initialization.
    """
    thread = threading.Thread(
        target=_worker_loop,
        args=(app,),
        name="match-worker",
        daemon=True,
    )
    thread.start()
    logger.info("[WORKER] Match worker thread launched.")
