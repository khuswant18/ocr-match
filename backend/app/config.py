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


LLM_TIMEOUT = _env_int("LLM_TIMEOUT", 90)     
LLM_MAX_RETRIES = _env_int("LLM_MAX_RETRIES", 2)   
LLM_RETRY_BACKOFF = _env_int("LLM_RETRY_BACKOFF", 2)  

WORKER_JOB_MAX_RETRIES = _env_int("WORKER_JOB_MAX_RETRIES", 1)

MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_MB", 25) * 1024 * 1024


class ApplicationConfig:
    SECRET_KEY = os.environ["SECRET_KEY"]
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_DATABASE_URI = os.environ["SQLALCHEMY_DATABASE_URI"]
    SESSION_TYPE = "sqlalchemy"
    SESSION_PERMANENT = True
