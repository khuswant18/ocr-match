# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
from pathlib import Path
import os

# Always load from backend/.env regardless of the working directory.
load_dotenv(Path(__file__).parent.parent / ".env")

BACKEND_URL = "http://localhost:4333"


class ApplicationConfig:
    SECRET_KEY = os.environ["SECRET_KEY"]
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_DATABASE_URI = os.environ["SQLALCHEMY_DATABASE_URI"]
    SESSION_TYPE = "sqlalchemy"
    SESSION_PERMEMNAT = True
