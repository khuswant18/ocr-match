from flask import Flask
from flask_cors import CORS
from flask_session import Session
from flask_bcrypt import Bcrypt
from app.config import ApplicationConfig
from .extensions import db

bcrypt = Bcrypt()


def create_app():
    app = Flask(__name__)
    app.config.from_object(ApplicationConfig)
    app.config.update(ENV='development')
    app.config['SESSION_SQLALCHEMY'] = db
    app.config['CORS_HEADERS'] = 'Content-Type'

    CORS(app, supports_credentials=True)
    Session(app)
    db.init_app(app)
    bcrypt.init_app(app)

    with app.app_context():
        db.create_all()
    register_blueprints(app)

    return app


def register_blueprints(app):
    from app.routes.preprocessing import preprocessing_bp
    from app.routes.data_routes import getData_bp
    from app.ocr.tesseractOCR import tesseract_bp
    from app.ocr.paddleOCR import paddleocr_bp
    from app.api.companyAPI import companyAPI_bp
    from app.routes.main_routes import main_bp
    from app.routes.matching_routes import matching_bp

    app.register_blueprint(preprocessing_bp)
    app.register_blueprint(getData_bp)
    app.register_blueprint(tesseract_bp)
    app.register_blueprint(paddleocr_bp)
    app.register_blueprint(companyAPI_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(matching_bp)

