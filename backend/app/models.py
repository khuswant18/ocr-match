import string
import random

from enum import Enum

from app.extensions import db
from app.utils.utils import get_uuid


class UserRole(Enum):
    ADMIN = "admin"
    OWNER = "owner"
    USER = "user"


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.String(32), primary_key=True,
                   unique=True, default=get_uuid)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(345), unique=True)
    password = db.Column(db.Text, nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False, default=UserRole.USER)
    invoices = db.relationship("Invoice", backref="user")


class Invoice(db.Model):
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.String(32), db.ForeignKey(
        'users.id'), nullable=False)
    invoice_number = db.Column(db.String(100))
    po_number = db.Column(db.String(100))
    invoice_date = db.Column(db.String(100))
    due_date = db.Column(db.String(100))
    payment_method = db.Column(db.String(100))
    total_amount = db.Column(db.String(100))
    cgst = db.Column(db.String(100))
    sgst = db.Column(db.String(100))
    igst = db.Column(db.String(100))
    bank = db.Column(db.String(100))
    ifsc = db.Column(db.String(100))
    account_number = db.Column(db.String(100))
    supplier_id = db.Column(
        db.Integer, db.ForeignKey('suppliers.id'), unique=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('buyers.id'), unique=True)
    text = db.Column(db.String(100000))
    pdf_file = db.Column(db.LargeBinary)
    image_file = db.Column(db.LargeBinary)
    performance_id = db.Column(db.Integer, db.ForeignKey('performance.id'))


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tin = db.Column(db.String(100))
    name = db.Column(db.String(255))
    address = db.Column(db.String(500))
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    pincode = db.Column(db.String(100))
    invoices = db.relationship("Invoice", backref="supplier")


class Buyer(db.Model):
    __tablename__ = "buyers"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    tin = db.Column(db.String(100))
    name = db.Column(db.String(255))
    address = db.Column(db.String(500))
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    pincode = db.Column(db.String(100))
    invoices = db.relationship("Invoice", backref="buyer")


class Performance(db.Model):
    __tablename__ = "performance"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    average_confidence = db.Column(db.Float)
    recognition_time = db.Column(db.Float)
    parsing_time = db.Column(db.Float)
    other_time = db.Column(db.Float)
    ocr_method = db.Column(db.String(100))
    invoice = db.relationship("Invoice", backref="performance", uselist=False)
