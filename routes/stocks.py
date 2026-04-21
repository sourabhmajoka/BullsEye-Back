from flask import Blueprint, request, jsonify
from services.stock_service import (
    get_stock_quote, get_historical_data, get_fundamentals,
    search_stocks, get_batch_quotes, INDIAN_STOCKS
)

stocks_bp = Blueprint("stocks", __name__)

@stocks_bp.route("/search", methods=["GET"])
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": []}), 200
    return jsonify({"results": search_stocks(q)}), 200

@stocks_bp.route("/quote/<symbol>", methods=["GET"])
def quote(symbol):
    exchange = request.args.get("exchange", "NSE").upper()
    return jsonify(get_stock_quote(symbol.upper(), exchange)), 200

@stocks_bp.route("/history/<symbol>", methods=["GET"])
def history(symbol):
    period = request.args.get("period", "1y")
    interval = request.args.get("interval", "1d")
    exchange = request.args.get("exchange", "NSE").upper()
    valid_periods = ["1d","5d","1mo","3mo","6mo","1y","2y","5y","max"]
    valid_intervals = ["1m","5m","15m","30m","1h","1d","1wk","1mo"]
    if period not in valid_periods: period = "1y"
    if interval not in valid_intervals: interval = "1d"
    data = get_historical_data(symbol.upper(), period, interval, exchange)
    return jsonify({"symbol": symbol.upper(), "period": period,
                    "interval": interval, "data": data}), 200

@stocks_bp.route("/fundamentals/<symbol>", methods=["GET"])
def fundamentals(symbol):
    exchange = request.args.get("exchange", "NSE").upper()
    return jsonify(get_fundamentals(symbol.upper(), exchange)), 200

@stocks_bp.route("/batch-quotes", methods=["POST"])
def batch_quotes():
    data = request.get_json() or {}
    symbols = data.get("symbols", [])[:20]
    return jsonify(get_batch_quotes(symbols)), 200

@stocks_bp.route("/list", methods=["GET"])
def list_stocks():
    stocks = [{"symbol": s, "company_name": n, "exchange": "NSE"}
              for s, n in INDIAN_STOCKS.items()]
    return jsonify({"stocks": stocks, "count": len(stocks)}), 200
