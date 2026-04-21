from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from database import db
from models.user import User, Watchlist

watchlist_bp = Blueprint('watchlist', __name__)

@watchlist_bp.route('/', methods=['GET'])
@jwt_required()
def get_watchlist():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if user and user.is_guest:
        return jsonify({'error': 'Watchlist not available for guests'}), 403
    
    watchlist = Watchlist.query.filter_by(user_id=user_id).all()
    return jsonify({'watchlist': [w.to_dict() for w in watchlist]}), 200

@watchlist_bp.route('/', methods=['POST'])
@jwt_required()
def add_to_watchlist():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if user and user.is_guest:
        return jsonify({'error': 'Not available for guests'}), 403
    
    data = request.get_json()
    symbol = data.get('symbol', '').upper()
    
    if not symbol:
        return jsonify({'error': 'Symbol required'}), 400
    
    existing = Watchlist.query.filter_by(user_id=user_id, symbol=symbol).first()
    if existing:
        return jsonify({'message': 'Already in watchlist'}), 200
    
    item = Watchlist(
        user_id=user_id,
        symbol=symbol,
        company_name=data.get('company_name', symbol),
        exchange=data.get('exchange', 'NSE').upper()
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'message': 'Added to watchlist', 'item': item.to_dict()}), 201

@watchlist_bp.route('/<symbol>', methods=['DELETE'])
@jwt_required()
def remove_from_watchlist(symbol):
    user_id = int(get_jwt_identity())
    item = Watchlist.query.filter_by(user_id=user_id, symbol=symbol.upper()).first()
    if not item:
        return jsonify({'error': 'Not in watchlist'}), 404
    
    db.session.delete(item)
    db.session.commit()
    return jsonify({'message': 'Removed from watchlist'}), 200
