# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
from pathlib import Path
import os

# Always load from backend/.env regardless of the working directory.
load_dotenv(Path(__file__).parent.parent / ".env")

BACKEND_URL = "http://localhost:4333"


def _env_int(name: str, default: int) -> int:
    """Read an int from the environment, falling back to `default` if unset/invalid."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- LLM parser budget (per provider call) -------------------------------
# Bounded so the total LLM stage can't exceed the job budget. Worst case with
# defaults ~= LLM_MAX_RETRIES * LLM_TIMEOUT + backoff.
LLM_TIMEOUT = _env_int("LLM_TIMEOUT", 90)          # seconds per HTTP call
LLM_MAX_RETRIES = _env_int("LLM_MAX_RETRIES", 2)   # attempts per provider
LLM_RETRY_BACKOFF = _env_int("LLM_RETRY_BACKOFF", 2)  # backoff base (seconds)

# --- Match worker -------------------------------------------------------
# Extra attempts for a job after a *transient* failure (network/timeout).
# Permanent failures (bad file, low OCR confidence, cancelled) never retry.
WORKER_JOB_MAX_RETRIES = _env_int("WORKER_JOB_MAX_RETRIES", 1)


class ApplicationConfig:
    SECRET_KEY = os.environ["SECRET_KEY"]
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_DATABASE_URI = os.environ["SQLALCHEMY_DATABASE_URI"]
    SESSION_TYPE = "sqlalchemy"
    SESSION_PERMEMNAT = True
