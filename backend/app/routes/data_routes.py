from flask import Blueprint, jsonify, session, request
from app.services.data_service import (
    get_invoices,
    save_time_other, get_performance_data
) 

getData_bp = Blueprint('getdata', __name__)

@getData_bp.route('/get-invoices')
def get_invoices_route():
    invoices = get_invoices()
    return jsonify({'invoices': invoices})


@getData_bp.route('/save-time-other', methods=['POST'])
def save_time_other_route():
    payload = request.get_json(silent=True) or {}
    invoice_id = payload.get('invoice_id') or payload.get('invoiceId') or payload.get('id')
    time_other = payload.get('time_other')

    if invoice_id is None:
        return jsonify({'error': 'Missing required field: invoice_id'}), 400
    if time_other is None:
        return jsonify({'error': 'Missing required field: time_other'}), 400

    success = save_time_other(invoice_id, time_other)
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'No performance data found for the given invoice_id.'}), 404


@getData_bp.route('/get-performance-data', methods=['POST'])
def get_performance_data_route():
    payload = request.get_json(silent=True) or {}
    invoice_id = payload.get('invoice_id') or payload.get('invoiceId') or payload.get('id')

    if invoice_id is None:
        return jsonify({'error': 'Missing required field: invoice_id'}), 400

    performance_data = get_performance_data(invoice_id)
    if performance_data:
        return jsonify(performance_data)
    else:
        return jsonify({'error': 'No performance data found for the given invoice_id.'}), 404
