from flask import Blueprint, jsonify
from services.stock_service import get_market_indices, get_top_gainers_losers, get_sector_performance

market_bp = Blueprint("market", __name__)

@market_bp.route("/indices", methods=["GET"])
def indices():
    return jsonify(get_market_indices()), 200

@market_bp.route("/movers", methods=["GET"])
def movers():
    return jsonify(get_top_gainers_losers()), 200

@market_bp.route("/sectors", methods=["GET"])
def sectors():
    return jsonify(get_sector_performance()), 200

@market_bp.route("/overview", methods=["GET"])
def overview():
    return jsonify({
        "indices": get_market_indices(),
        "movers": get_top_gainers_losers(),
        "sectors": get_sector_performance(),
    }), 200
