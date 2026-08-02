"""
Structured logging for the invoice quality assessment layer.

Kept separate from ocr/quality.py so that module stays dependency-free and
offline-testable.

WHY THIS LOGGER IS CONFIGURED BY HAND
    app/__init__.py::_setup_logging clamps the ROOT logger and
    logging.getLogger("app") to CRITICAL, to leave only print() output. A
    logger named "app.quality" would inherit CRITICAL from "app"; a logger
    named "quality" would inherit it from root. Either way every line would
    silently vanish.

    So this logger sits outside the "app" tree, sets its own level, owns its
    own handler, and does not propagate to the muted root handlers.

Output is one JSON object per line behind a fixed "QUALITY " prefix, so the
whole stream can be recovered from container logs with:

    docker compose logs backend | grep '^QUALITY ' | sed 's/^QUALITY //' > q.jsonl

Every field is flat and primitive, so the result loads with a single
pandas.read_json(..., lines=True).
"""

import json
import logging
import sys
from datetime import datetime, timezone

LOG_PREFIX = "QUALITY "

logger = logging.getLogger("invoice.quality")
logger.setLevel(logging.INFO)
logger.propagate = False

if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _emit(payload: dict) -> None:
    try:
        logger.info(LOG_PREFIX + json.dumps(payload, default=str, sort_keys=False))
    except Exception:                                   # never break extraction
        logger.info(LOG_PREFIX + json.dumps({"event": "log_error",
                                             "ts": _now()}))


# Raw signals worth keeping flat in the log line for offline tuning. Anything
# not listed still lives in the full report on the API response.
_RAW_KEYS = (
    ("blur", "laplacian_var"),
    ("blur", "ink_ratio"),
    ("resolution", "short_side_px"),
    ("cropping", "edge_count"),
    ("readability", "median_text_h_px"),
    ("readability", "low_conf_ratio"),
    ("skew", "skew_deg"),
    ("lighting", "illum_range"),
    ("lighting", "paper_mean"),
    ("contrast", "gap"),
    ("completeness", "block_count"),
    ("completeness", "vertical_coverage"),
    ("noise", "sigma_paper"),
    ("ocr_confidence", "mean_conf"),
)


def log_assessment(report, *, filename=None, job_id=None, assessment_id=None,
                   source="sync", ocr_ms=None, held=False, tier_action="ok"):
    """One line per assessed document - INCLUDING the ones that pass.

    The passing documents are the corpus needed to tune thresholds and to
    support the 'future model improvements' goal, so they are never skipped.
    """
    data = report.to_dict() if hasattr(report, "to_dict") else dict(report or {})
    metrics = data.get("metrics", {})

    raw = {}
    for metric, key in _RAW_KEYS:
        value = metrics.get(metric, {}).get("raw", {}).get(key)
        if value is not None:
            raw[f"{metric}.{key}"] = value

    cropped = metrics.get("cropping", {}).get("raw", {}).get("cropped_edges")

    _emit({
        "event": "assessment",
        "ts": _now(),
        "version": data.get("version"),
        "source": source,
        "assessment_id": assessment_id,
        "job_id": job_id,
        "filename": filename,
        "page_count": data.get("page_count"),
        "score": data.get("score"),
        "tier": data.get("tier"),
        "action": tier_action,
        "held": bool(held),
        "issues": [i.get("code") for i in data.get("issues", [])],
        "scores": {k: v.get("score") for k, v in metrics.items()},
        "raw": raw,
        "cropped_edges": cropped,
        "elapsed_ms": data.get("elapsed_ms"),
        "ocr_ms": ocr_ms,
    })


def log_decision(*, assessment_id, decision, job_id=None, source="sync",
                 tier=None, score=None, held_seconds=None):
    """One line per vendor decision (proceed / retry)."""
    _emit({
        "event": "decision",
        "ts": _now(),
        "assessment_id": assessment_id,
        "job_id": job_id,
        "source": source,
        "decision": decision,
        "tier": tier,
        "score": score,
        "held_seconds": round(held_seconds, 1) if held_seconds is not None else None,
    })


def log_event(event, **fields):
    """Degradation paths: hold_skipped_oversize, resume_reocr_fallback,
    hold_expired, assessment_failed."""
    payload = {"event": event, "ts": _now()}
    payload.update(fields)
    _emit(payload)
