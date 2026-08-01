from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path(__file__).parent.parent / ".env")


def _env_int(name: str, default: int) -> int:
    """Read an int from the environment, falling back to `default` if unset/invalid."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    """Read a float from the environment, falling back to `default` if unset/invalid."""
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    """Read a bool from the environment. '1', 'true', 'yes', 'on' are True."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


LLM_TIMEOUT = _env_int("LLM_TIMEOUT", 90)     
LLM_MAX_RETRIES = _env_int("LLM_MAX_RETRIES", 2)   
LLM_RETRY_BACKOFF = _env_int("LLM_RETRY_BACKOFF", 2)  

WORKER_JOB_MAX_RETRIES = _env_int("WORKER_JOB_MAX_RETRIES", 1)

MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_MB", 25) * 1024 * 1024

# ── Invoice quality assessment layer ──
# Master switch. False = the engine behaves exactly as it did before the gate.
QUALITY_GATE_ENABLED = _env_bool("QUALITY_GATE_ENABLED", True)
# Apply the hold to async /api/pipeline jobs too. Set False to assess and log
# without ever parking a job, for API clients that cannot handle the new
# non-terminal 'quality_hold' status.
QUALITY_GATE_PIPELINE_ENABLED = _env_bool("QUALITY_GATE_PIPELINE_ENABLED", True)
# Shadow mode: assess, score and log, but never hold and never flag. Use this
# to tune thresholds against live traffic before arming the gate.
QUALITY_LOG_ONLY = _env_bool("QUALITY_LOG_ONLY", False)

# Tier boundaries on the 0-100 confidence score.
QUALITY_SCORE_HIGH = _env_float("QUALITY_SCORE_HIGH", 85.0)
QUALITY_SCORE_LOW = _env_float("QUALITY_SCORE_LOW", 70.0)

# Hold cache: how long a paused OCR result stays resumable, and its bounds.
QUALITY_HOLD_TTL_SECONDS = _env_int("QUALITY_HOLD_TTL_SECONDS", 1800)
QUALITY_HOLD_MAX_ENTRIES = _env_int("QUALITY_HOLD_MAX_ENTRIES", 20)
QUALITY_HOLD_MAX_BYTES = _env_int("QUALITY_HOLD_MAX_MB", 256) * 1024 * 1024

# Longest edge of the analysis probe. All metric cut-points in ocr/quality.py
# are calibrated to this value - changing it invalidates the calibration.
QUALITY_PROBE_MAX_DIM = _env_int("QUALITY_PROBE_MAX_DIM", 1600)
# Max pages assessed per document (latency bound). Document score is the
# minimum across assessed pages.
QUALITY_MAX_PAGES = _env_int("QUALITY_MAX_PAGES", 5)

# When set, a request carrying `X-Quality-Bypass: <token>` is assessed and
# logged but never held. Used by the batch harness so a tuning run measures
# extraction quality rather than being blocked by the gate under test.
QUALITY_BYPASS_TOKEN = os.environ.get("QUALITY_BYPASS_TOKEN", "").strip()


class ApplicationConfig:
    SECRET_KEY = os.environ["SECRET_KEY"]
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_DATABASE_URI = os.environ["SQLALCHEMY_DATABASE_URI"]
    SESSION_TYPE = "sqlalchemy"
    SESSION_PERMANENT = True
