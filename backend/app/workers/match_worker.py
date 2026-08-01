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


def _resume_or_reprocess(resume_extraction, extract_and_parse, ExtractionError,
                         log_event, hold_record, job, file_bytes):
    """Honour a "Proceed Anyway" decision.

    Normally replays the cached OCR result. The cache is in-process, so if the
    worker restarted while the job was held the entry is gone - in that case
    fall back to a full re-extraction with the gate bypassed. The vendor's
    decision is honoured either way; it just costs another OCR pass.
    """
    assessment_id = hold_record.get('assessment_id')
    if assessment_id:
        try:
            return resume_extraction(assessment_id, job_id=job.id)
        except ExtractionError as exc:
            if getattr(exc, 'status_code', None) != 410:
                raise
            log_event("resume_reocr_fallback", job_id=job.id,
                      assessment_id=assessment_id, source="pipeline",
                      reason="hold cache entry gone (worker restart or TTL)")
            print(f"[WORKER] Job #{job.id}: hold cache miss, re-running OCR.")

    return extract_and_parse(
        file_bytes,
        os.path.basename(job.file_path),
        po_number=job.po_number,
        job_id=job.id,
        existing_path=job.file_path,
        quality_decision='proceed',
        source='pipeline',
    )


def _expire_stale_holds(app):
    """Fail jobs whose quality hold lapsed without a vendor decision.

    The orphan reaper only looks at status='running', so held jobs correctly
    survive a restart - but their cached OCR result does not live forever.
    """
    with app.app_context():
        from app.models import db, MatchJob
        from app.ocr import quality_cache

        held = MatchJob.query.filter_by(status='quality_hold').all()
        if not held:
            return

        now = datetime.now(timezone.utc)
        expired = 0
        for job in held:
            record = (job.result_json or {}).get('_hold') or {}
            raw = record.get('expires_at')
            if not raw:
                continue
            try:
                deadline = datetime.fromisoformat(raw)
            except (TypeError, ValueError):
                continue
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if now < deadline:
                continue

            quality_cache.discard(record.get('assessment_id'))
            job.status = 'failed'
            job.error_message = (
                'Quality hold expired without a decision. '
                'Please re-upload the invoice.'
            )
            job.completed_at = now
            expired += 1

        if expired:
            db.session.commit()
            print(f"[WORKER] Expired {expired} stale quality hold(s).")


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
        from app.ocr.engine import (
            extract_and_parse, resume_extraction, ExtractionError, QualityHold,
        )
        from app.ocr.quality_log import log_event
        from app.config import QUALITY_GATE_PIPELINE_ENABLED
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

        # A job resumed after "Proceed Anyway" carries the vendor's decision
        # in its _hold record; a held job that never got one is not here at all
        # (its status is 'quality_hold', not 'pending').
        hold_record = (job.result_json or {}).get('_hold') or {}
        vendor_decision = hold_record.get('decision')

        terminal = True

        try:
            result = None
            for attempt in range(1, max_attempts + 1):
                try:
                    if job.job_type == 'extract_and_match' and job.file_path:
                        with open(job.file_path, 'rb') as f:
                            file_bytes = f.read()

                        if vendor_decision == 'proceed':
                            invoice_id, parsed_data, _text, _meta = \
                                _resume_or_reprocess(
                                    resume_extraction, extract_and_parse,
                                    ExtractionError, log_event,
                                    hold_record, job, file_bytes,
                                )
                        else:
                            invoice_id, parsed_data, _text, _meta = extract_and_parse(
                                file_bytes,
                                os.path.basename(job.file_path),
                                po_number=job.po_number,
                                job_id=job.id,
                                existing_path=job.file_path,
                                quality_decision=(
                                    None if QUALITY_GATE_PIPELINE_ENABLED else 'proceed'
                                ),
                                source='pipeline',
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

        except QualityHold as e:
            # Park the job for a vendor decision. This is NOT a failure, so it
            # must be caught above the generic handler below and must not stamp
            # completed_at. The worker does not wait: the row simply leaves
            # 'pending', and the decision endpoint flips it back so the next
            # poll (<=2s) picks it up.
            job.status = 'quality_hold'
            job.error_message = None
            job.result_json = {
                "_hold": {
                    "assessment_id": e.assessment_id,
                    "quality": e.report,
                    "warning": e.warning,
                    "held_at": datetime.now(timezone.utc).isoformat(),
                    "expires_at": (
                        datetime.fromtimestamp(e.expires_at, tz=timezone.utc).isoformat()
                        if e.expires_at else None
                    ),
                    "decision": None,
                }
            }
            terminal = False
            score = (e.report or {}).get('score')
            print(f"[WORKER] Job #{job.id} held for a quality decision "
                  f"(score {score}).")

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

        # A held job has not completed; leaving completed_at NULL is what keeps
        # duration_seconds correctly None in the job-status endpoint.
        if terminal:
            job.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return True


def _worker_loop(app):
    print("[WORKER] Match worker started.")
    _reap_orphaned_jobs(app)
    _expire_stale_holds(app)
    ticks = 0
    while True:
        try:
            had_work = _process_one_job(app)
            if not had_work:
                time.sleep(POLL_INTERVAL)
            ticks += 1
            # Roughly every 5 minutes at the default 2s poll interval.
            if ticks % 150 == 0:
                _expire_stale_holds(app)
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
