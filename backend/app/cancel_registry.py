"""
Shared cancel registry for pipeline jobs.

Every running job registers a threading.Event here. Cancel endpoints
set() the event; long-running stages (OCR, LLM, vector matching)
check it periodically and raise JobCancelledError to abort.
"""

import threading
import logging

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_events: dict[int, threading.Event] = {}
_cancel_all = threading.Event()


class JobCancelledError(Exception):
    """Raised when a job is cancelled mid-flight."""
    pass


def register(job_id: int) -> threading.Event:
    """Create and store a cancel event for a job. Returns the event."""
    event = threading.Event()
    with _lock:
        _events[job_id] = event
    return event


def unregister(job_id: int) -> None:
    """Remove a job's cancel event (call after job finishes)."""
    with _lock:
        _events.pop(job_id, None)


def cancel_job(job_id: int) -> bool:
    """Cancel a specific job. Returns True if the job was found."""
    with _lock:
        event = _events.get(job_id)
    if event:
        event.set()
        logger.info(f"[CANCEL] Job #{job_id} cancel signal sent.")
        return True
    return False


def cancel_all() -> int:
    """
    Cancel every running job AND set the global kill switch.
    Returns the number of jobs signalled.
    """
    _cancel_all.set()
    with _lock:
        count = 0
        for job_id, event in _events.items():
            event.set()
            count += 1
    logger.info(f"[CANCEL] Cancel-all signal sent to {count} job(s).")
    return count


def reset_cancel_all() -> None:
    """Clear the global kill switch (called when the worker picks up the next job)."""
    _cancel_all.clear()


def check_cancelled(job_id: int | None = None) -> None:
    """
    Call this at checkpoints inside long-running code.
    Raises JobCancelledError if this job (or all jobs) should stop.
    """
    if _cancel_all.is_set():
        raise JobCancelledError("All jobs cancelled by user.")
    if job_id is not None:
        with _lock:
            event = _events.get(job_id)
        if event and event.is_set():
            raise JobCancelledError(f"Job #{job_id} cancelled by user.")


def active_job_ids() -> list[int]:
    """Return list of currently registered (running) job IDs."""
    with _lock:
        return list(_events.keys())
