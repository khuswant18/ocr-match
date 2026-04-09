from flask import Blueprint, jsonify, session, request
from app.services.main_service import (
    delete_invoice_service, update_invoice_service
) 

main_bp = Blueprint('main', __name__)


@main_bp.route('/delete-invoice', methods=['DELETE'])
def delete_invoice():
    invoice_id = request.args.get('id', type=int)
    if not invoice_id:
        return jsonify({"error": "ID parameter is missing"}), 400

    deleted_invoice_id = delete_invoice_service(invoice_id)
    if not deleted_invoice_id:
        return jsonify({"error": "Invoice not found"}), 404

    return jsonify({"message": f"Invoice {invoice_id} has been deleted"}), 200


@main_bp.route('/update-invoice', methods=['POST'])
def update_invoice():
    payload = request.get_json(silent=True) or {}
    new_data = payload.get("new_data") or {}
    invoice_id = new_data.get("id")
    if not invoice_id:
        return jsonify({"error": "ID parameter is missing"}), 400

    updated_invoice_id, error = update_invoice_service(new_data)
    print("Updated invoice ID:", updated_invoice_id)
    if error:
        return jsonify({"error": error}), 400
    if not updated_invoice_id:
        return jsonify({"error": "Invoice not found"}), 404

    return jsonify({"message": "Invoice has been updated"}), 200
