"""
API routes for three-way matching.
"""
from flask import Blueprint, jsonify, request

matching_bp = Blueprint('matching', __name__)


@matching_bp.route('/api/match/update-code', methods=['POST'])
def update_item_code():
    """Manual match: update an invoice item's product code."""
    from app.services.matching_service import update_invoice_item_code
    data = request.get_json()
    invoice_item_id = data.get('invoice_item_id')
    new_product_code = data.get('product_code')

    if not invoice_item_id or not new_product_code:
        return jsonify({"error": "invoice_item_id and product_code are required"}), 400

    try:
        result = update_invoice_item_code(invoice_item_id, new_product_code)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@matching_bp.route('/api/match/po-list', methods=['GET'])
def get_po_list():
    """Return list of available PO numbers."""
    from app.services.matching_service import get_po_list as _get_po_list
    try:
        po_list = _get_po_list()
        return jsonify(po_list), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@matching_bp.route('/api/match/<po_number>', methods=['GET'])
def run_match(po_number):
    """Run three-way match for a PO number."""
    from app.services.matching_service import run_three_way_match
    try:
        result = run_three_way_match(po_number)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
