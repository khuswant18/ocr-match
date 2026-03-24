"""
API routes for three-way matching.
"""
from flask import Blueprint, jsonify

matching_bp = Blueprint('matching', __name__)


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
