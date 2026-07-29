import logging
import threading
import time
from datetime import datetime, timezone

from app.cancel_registry import (
    register, unregister, reset_cancel_all, JobCancelledError,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL = 2


def _cancel_key(job_id):
    """Namespace PSR job ids in the shared cancel registry so they never collide
    with MatchJob ids (both tables autoincrement independently)."""
    return f"psr-{job_id}"


def _reap_orphaned_jobs(app):
    """On startup, fail any job still 'running' — the previous process died
    mid-job and it can never resume (jobs run in-process)."""
    with app.app_context():
        from app.models import db, PsrJob

        orphaned = PsrJob.query.filter_by(status='running').all()
        if not orphaned:
            return
        for job in orphaned:
            job.status = 'failed'
            job.error_message = 'Worker restarted while job was in progress.'
            job.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        print(f"[PSR-WORKER] Reaped {len(orphaned)} orphaned 'running' job(s) on startup.")


def _process_one_job(app):
    """Claim the oldest pending PSR job, run it, store the result.
    Returns True if a job was processed, False if the queue was empty."""
    with app.app_context():
        from app.models import db, PsrJob
        from app.services.psr_service import run_psr_extract_and_match
        from app.ocr.engine import ExtractionError

        job = (
            PsrJob.query
            .filter_by(status='pending')
            .order_by(PsrJob.created_at.asc())
            .first()
        )
        if not job:
            return False

        reset_cancel_all()
        cancel_key = _cancel_key(job.id)
        register(cancel_key)

        job.status = 'running'
        job.started_at = datetime.now(timezone.utc)
        db.session.commit()
        print(f"[PSR-WORKER] Processing job #{job.id} ({job.original_filename})")

        try:
            with open(job.file_path, 'rb') as f:
                file_bytes = f.read()

            result = run_psr_extract_and_match(
                file_bytes,
                job.original_filename or job.file_path,
                override_name=job.override_name,
                job_id=cancel_key,
                records=job.input_records,
            )
            job.status = 'completed'
            job.result_json = result
            print(f"[PSR-WORKER] Job #{job.id} completed ({result.get('status')})")

        except JobCancelledError as e:
            job.status = 'cancelled'
            job.error_message = str(e)
            print(f"[PSR-WORKER] Job #{job.id} cancelled: {e}")

        except ExtractionError as e:
            job.status = 'failed'
            job.error_message = e.message
            print(f"[PSR-WORKER] Job #{job.id} failed: {e.message}")

        except Exception as e:
            job.status = 'failed'
            job.error_message = str(e)
            print(f"[PSR-WORKER] Job #{job.id} crashed: {e}")

        finally:
            unregister(cancel_key)

        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return True


def _worker_loop(app):
    print("[PSR-WORKER] PSR worker started.")
    try:
        _reap_orphaned_jobs(app)
    except Exception as e:
        # A startup hiccup (e.g. a schema change mid-deploy) must not kill the
        # worker thread — the poll loop below will recover.
        print(f"[PSR-WORKER] reap on startup failed (continuing): {e}")
    while True:
        try:
            had_work = _process_one_job(app)
            if not had_work:
                time.sleep(POLL_INTERVAL)
        except Exception as e:
            print(f"[PSR-WORKER] Unexpected error in worker loop: {e}")
            time.sleep(POLL_INTERVAL * 5)


def start_psr_worker(app):
    """Launch the PSR worker as a daemon thread. Called once at app startup."""
    thread = threading.Thread(
        target=_worker_loop,
        args=(app,),
        name="psr-worker",
        daemon=True,
    )
    thread.start()
    print("[PSR-WORKER] PSR worker thread launched.")
