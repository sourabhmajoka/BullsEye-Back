"""
ML / Technical Analysis routes
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from services.stock_service import get_historical_data
from ml.technical_analysis import get_full_analysis, calculate_rsi, calculate_macd, calculate_bollinger_bands

ml_bp = Blueprint('ml', __name__)

@ml_bp.route('/technical/<symbol>', methods=['GET'])
@jwt_required(optional=True)
def technical_analysis(symbol):
    period = request.args.get('period', '1y')
    exchange = request.args.get('exchange', 'NSE')
    
    history = get_historical_data(symbol, period=period, exchange=exchange)
    if not history:
        return jsonify({'error': 'No data available'}), 404
    
    analysis = get_full_analysis(history)
    return jsonify({
        'symbol': symbol,
        'analysis': analysis
    }), 200
