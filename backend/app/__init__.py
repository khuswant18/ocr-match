import logging
import sys

from flask import Flask
from flask_cors import CORS
from flask_session import Session
from flask_bcrypt import Bcrypt
from app.config import ApplicationConfig
from .extensions import db

bcrypt = Bcrypt()


def _setup_logging(app):
    # Suppress all standard logs as requested, leaving only print() output
    logging.getLogger().setLevel(logging.CRITICAL)
    app.logger.setLevel(logging.CRITICAL)
    logging.getLogger("app").setLevel(logging.CRITICAL)
    logging.getLogger("werkzeug").setLevel(logging.CRITICAL)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.CRITICAL)


def create_app():
    app = Flask(__name__)
    app.config.from_object(ApplicationConfig)
    app.config.update(ENV='development')
    app.config['SESSION_SQLALCHEMY'] = db
    app.config['CORS_HEADERS'] = 'Content-Type'
    # Preserve the order in which we build response dicts instead of
    # alphabetising JSON keys, so related fields stay grouped/readable.
    app.json.sort_keys = False

    _setup_logging(app)

    CORS(app, supports_credentials=True)
    Session(app)
    db.init_app(app)
    bcrypt.init_app(app)

    with app.app_context():
        db.create_all()
    register_blueprints(app)

    # NOTE: the background match worker is started by the serving entrypoint
    # (run.py), NOT here. Starting it in create_app() would launch a second
    # worker in the Werkzeug reloader's supervisor process (it re-execs the
    # module), doubling PaddleOCR memory and splitting the in-process cancel
    # registry so /cancel can't reach a job running in the other process.

    return app


def register_blueprints(app):
    from app.routes.preprocessing import preprocessing_bp
    from app.routes.data_routes import getData_bp
    from app.ocr.paddleOCR import paddleocr_bp
    from app.routes.main_routes import main_bp
    from app.routes.matching_routes import matching_bp
    from app.routes.pipeline_routes import pipeline_bp
    from app.routes.psr_routes import psr_bp

    app.register_blueprint(preprocessing_bp)
    app.register_blueprint(getData_bp)
    app.register_blueprint(paddleocr_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(matching_bp)
    app.register_blueprint(pipeline_bp)
    app.register_blueprint(psr_bp)


