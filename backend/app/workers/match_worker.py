import logging
import threading
import time
import os
from datetime import datetime, timezone
from app.config import WORKER_JOB_MAX_RETRIES
from app.cancel_registry import (
    register, unregister, reset_cancel_all, check_cancelled,
    JobCancelledError,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL = 2


def _reap_orphaned_jobs(app):
    """
    On startup, mark any job still 'running' as failed. Jobs run in-process,
    so a 'running' row means the previous process died mid-job — it can never
    resume. This is the safety valve that replaced the old 300s HTTP timeout.
    """
    with app.app_context():
        from app.models import db, MatchJob

        orphaned = MatchJob.query.filter_by(status='running').all()
        if not orphaned:
            return
        for job in orphaned:
            job.status = 'failed'
            job.error_message = 'Worker restarted while job was in progress.'
            job.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        print(f"[WORKER] Reaped {len(orphaned)} orphaned 'running' job(s) on startup.")


def _process_one_job(app):
    """
    Claim the oldest pending job, execute it, and store the result.
    Returns True if a job was processed, False if the queue was empty.

    OCR runs in-process via `extract_and_parse` (serialized by the OCR lock),
    so there is no self-HTTP call and no artificial client timeout. Transient
    failures (LLM temporarily unavailable, network) are retried up to
    WORKER_JOB_MAX_RETRIES times; permanent failures are not.
    """
    with app.app_context():
        from app.models import db, MatchJob
        from app.services.matching_service import run_three_way_match, run_match_from_payload
        from app.ocr.paddleOCR import extract_and_parse, ExtractionError
        import requests as req

        job = (
            MatchJob.query
            .filter_by(status='pending')
            .order_by(MatchJob.created_at.asc())
            .first()
        )
        if not job:
            return False

        # Clear the global cancel-all flag so this new job can run
        reset_cancel_all()

        # Register a per-job cancel event
        register(job.id)

        job.status = 'running'
        job.started_at = datetime.now(timezone.utc)
        db.session.commit()
        print(f"[WORKER] Processing job #{job.id} (type={job.job_type}) for PO {job.po_number}")

        def _is_transient(exc):
            # LLM temporarily unavailable (502) or a network hiccup — worth a retry.
            if isinstance(exc, ExtractionError):
                return exc.status_code == 502
            return isinstance(exc, (req.exceptions.Timeout, req.exceptions.ConnectionError))

        max_attempts = 1 + max(0, WORKER_JOB_MAX_RETRIES)

        try:
            result = None
            for attempt in range(1, max_attempts + 1):
                try:
                    if job.job_type == 'extract_and_match' and job.file_path:
                        with open(job.file_path, 'rb') as f:
                            file_bytes = f.read()

                        invoice_id, parsed_data, _text, _meta = extract_and_parse(
                            file_bytes,
                            os.path.basename(job.file_path),
                            po_number=job.po_number,
                            job_id=job.id,
                            existing_path=job.file_path,
                        )
                        print(f"[WORKER] Extraction done for job #{job.id}, invoice_id={invoice_id}")

                        check_cancelled(job.id)

                        env = job.input_json or {}
                        result = run_match_from_payload(
                            job.po_number,
                            env.get("po_lines"),
                            env.get("pol_grn"),
                            parsed_data,
                            invoice_id,
                            job_id=job.id,
                        )
                    else:
                        result = run_three_way_match(job.po_number)
                    break  # success
                except JobCancelledError:
                    raise
                except Exception as e:
                    if attempt < max_attempts and _is_transient(e):
                        print(f"[WORKER] Job #{job.id} transient error "
                              f"(attempt {attempt}/{max_attempts}): {e}. Retrying.")
                        check_cancelled(job.id)  # bail out if cancelled between attempts
                        continue
                    raise

            if "error" in result:
                job.status = 'failed'
                job.error_message = result["error"]
                print(f"[WORKER] Job #{job.id} failed: {result['error']}")
            else:
                job.status = 'completed'
                job.result_json = result
                print(f"[WORKER] Job #{job.id} completed successfully")

        except JobCancelledError as e:
            job.status = 'cancelled'
            job.error_message = str(e)
            print(f"[WORKER] Job #{job.id} cancelled: {e}")

        except ExtractionError as e:
            job.status = 'failed'
            job.error_message = e.message
            print(f"[WORKER] Job #{job.id} failed: {e.message}")

        except Exception as e:
            job.status = 'failed'
            job.error_message = str(e)
            print(f"[WORKER] Job #{job.id} crashed: {e}")

        finally:
            unregister(job.id)

        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return True


def _worker_loop(app):
    print("[WORKER] Match worker started.")
    _reap_orphaned_jobs(app)
    while True:
        try:
            had_work = _process_one_job(app)
            if not had_work:
                time.sleep(POLL_INTERVAL)
        except Exception as e:
            print(f"[WORKER] Unexpected error in worker loop: {e}")
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
    print("[WORKER] Match worker thread launched.")
