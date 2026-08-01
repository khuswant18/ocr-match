"""
Hold/resume cache for documents paused by the quality gate.

When a document scores below the low threshold the pipeline stops and waits
for the vendor to choose "Upload a Better Invoice" or "Proceed Anyway". The
expensive part (6-7s of PaddleOCR) has already run by then, so it is parked
here and replayed on resume instead of being recomputed.

Modelled on app/cancel_registry.py: module-level lock, module-level dict, a
small function surface, no class instantiation, no Flask.

WHAT IS STORED, AND WHY IT IS THE FILE BYTES
    Page images are large: a 1275x1651 RGB page is 6.3 MB, and a 300-DPI PDF
    page is ~26 MB. Twenty held 3-page PDFs would be ~1.5 GB, in a container
    already holding PaddleOCR, LayoutLMv3 and torch.

    So we keep the ORIGINAL upload bytes and re-derive the images on resume.
    That is ~10 ms for a PNG or ~0.3 s/page for a PDF - still 20-30x cheaper
    than the OCR pass being avoided - and, crucially, it is deterministic:
    load_images_from_bytes returns byte-identical images, which matters
    because _extract_words_and_boxes normalises LayoutLM boxes against
    img.shape. Caching a re-encoded image instead would risk drifting boxes.

    If PDF re-render latency ever becomes the bottleneck, switch to storing
    JPEG-encoded pages without touching any call site.
"""

import logging
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_entries: "OrderedDict[str, HoldEntry]" = OrderedDict()

# Defaults; overridden once at import time by the engine via configure().
_ttl_seconds: float = 1800.0
_max_entries: int = 20
_max_bytes: int = 256 * 1024 * 1024


@dataclass
class HoldEntry:
    token: str
    created_at: float
    expires_at: float
    source: str                 # 'sync' | 'pipeline'
    job_id: int | None
    filename: str | None
    po_number: str | None
    existing_path: str | None
    file_bytes: bytes
    all_results: Any            # raw PaddleOCR output - the expensive artefact
    text: str
    average_confidence: float
    recognition_time: float
    report: dict                # QualityReport.to_dict()
    nbytes: int = 0

    def age_seconds(self) -> float:
        return time.time() - self.created_at

    def is_expired(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) >= self.expires_at


def configure(ttl_seconds: float | None = None,
              max_entries: int | None = None,
              max_bytes: int | None = None) -> None:
    """Set the cache bounds. Called once from the engine with config values."""
    global _ttl_seconds, _max_entries, _max_bytes
    with _lock:
        if ttl_seconds is not None:
            _ttl_seconds = float(ttl_seconds)
        if max_entries is not None:
            _max_entries = int(max_entries)
        if max_bytes is not None:
            _max_bytes = int(max_bytes)


def _sweep_locked(now: float) -> int:
    dropped = [t for t, e in _entries.items() if e.is_expired(now)]
    for token in dropped:
        _entries.pop(token, None)
    return len(dropped)


def sweep() -> int:
    """Drop expired entries. Returns how many were removed."""
    with _lock:
        return _sweep_locked(time.time())


def _total_bytes_locked() -> int:
    return sum(e.nbytes for e in _entries.values())


def put(*, file_bytes: bytes, all_results, text: str,
        average_confidence: float, recognition_time: float, report: dict,
        filename: str | None = None, po_number: str | None = None,
        existing_path: str | None = None, job_id: int | None = None,
        source: str = "sync") -> str | None:
    """Park a held document and return its token.

    Returns None when the entry alone exceeds the byte cap. The caller must
    then proceed with a caution flag rather than holding: the quality layer
    must never be the reason a legitimate upload fails outright.
    """
    now = time.time()
    nbytes = len(file_bytes or b"")

    with _lock:
        _sweep_locked(now)

        if _max_bytes and nbytes > _max_bytes:
            logger.warning(
                "[QUALITY] Not holding %s: %d bytes exceeds the %d byte cap.",
                filename, nbytes, _max_bytes,
            )
            return None

        token = "qa_" + secrets.token_urlsafe(16)
        entry = HoldEntry(
            token=token, created_at=now, expires_at=now + _ttl_seconds,
            source=source, job_id=job_id, filename=filename,
            po_number=po_number, existing_path=existing_path,
            file_bytes=file_bytes, all_results=all_results, text=text,
            average_confidence=average_confidence,
            recognition_time=recognition_time, report=report, nbytes=nbytes,
        )

        # Evict oldest-first until both bounds hold with the newcomer included.
        while _entries and (
            len(_entries) + 1 > _max_entries
            or (_max_bytes and _total_bytes_locked() + nbytes > _max_bytes)
        ):
            evicted_token, evicted = _entries.popitem(last=False)
            logger.info("[QUALITY] Evicted held assessment %s (%s) to stay "
                        "within cache bounds.", evicted_token, evicted.filename)

        _entries[token] = entry
        return token


def peek(token: str) -> HoldEntry | None:
    """Read an entry without consuming it. None if unknown or expired."""
    if not token:
        return None
    now = time.time()
    with _lock:
        _sweep_locked(now)
        entry = _entries.get(token)
        if entry is None or entry.is_expired(now):
            return None
        return entry


def pop(token: str) -> HoldEntry | None:
    """Atomically take and remove an entry. None if unknown or expired.

    The caller re-derives images OUTSIDE the lock - never decode while holding
    it.
    """
    if not token:
        return None
    now = time.time()
    with _lock:
        _sweep_locked(now)
        entry = _entries.pop(token, None)
        if entry is None or entry.is_expired(now):
            return None
        return entry


def discard(token: str) -> bool:
    """Drop an entry (vendor chose retry, or the job was cancelled)."""
    if not token:
        return False
    with _lock:
        return _entries.pop(token, None) is not None


def stats() -> dict:
    with _lock:
        now = time.time()
        oldest = min((e.created_at for e in _entries.values()), default=None)
        return {
            "entries": len(_entries),
            "bytes": _total_bytes_locked(),
            "oldest_age_s": round(now - oldest, 1) if oldest else None,
            "ttl_seconds": _ttl_seconds,
            "max_entries": _max_entries,
            "max_bytes": _max_bytes,
        }


def clear() -> None:
    """Test helper: drop everything."""
    with _lock:
        _entries.clear()
