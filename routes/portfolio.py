"""
Portfolio management routes — includes edit & remove holdings, AI analysis
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from database import db
from models.user import User, Portfolio, Holding, Transaction
from services.stock_service import get_stock_quote, STOCK_SECTOR

portfolio_bp = Blueprint("portfolio", __name__)


def _guest(uid):
    u = User.query.get(uid)
    return u and u.is_guest


@portfolio_bp.route("/", methods=["GET"])
@jwt_required()
def get_portfolios():
    uid = int(get_jwt_identity())
    if _guest(uid):
        return jsonify({"error": "Portfolio not available for guests"}), 403
    ps = Portfolio.query.filter_by(user_id=uid).all()
    return jsonify({"portfolios": [p.to_dict() for p in ps]}), 200


@portfolio_bp.route("/", methods=["POST"])
@jwt_required()
def create_portfolio():
    uid = int(get_jwt_identity())
    if _guest(uid):
        return jsonify({"error": "Not available for guests"}), 403
    data = request.get_json() or {}
    p = Portfolio(user_id=uid, name=data.get("name", "My Portfolio"),
                  description=data.get("description", ""))
    db.session.add(p)
    db.session.commit()
    return jsonify({"portfolio": p.to_dict()}), 201


@portfolio_bp.route("/<int:pid>", methods=["GET"])
@jwt_required()
def get_portfolio(pid):
    uid = int(get_jwt_identity())
    if _guest(uid):
        return jsonify({"error": "Not available for guests"}), 403
    p = Portfolio.query.filter_by(id=pid, user_id=uid).first()
    if not p:
        return jsonify({"error": "Portfolio not found"}), 404

    holdings_out = []
    total_inv = total_curr = 0.0

    for h in p.holdings:
        q         = get_stock_quote(h.symbol, h.exchange)
        cp        = q.get("current_price", 0) or h.avg_buy_price
        invested  = h.quantity * h.avg_buy_price
        curr_val  = h.quantity * cp
        pnl       = curr_val - invested
        pnl_pct   = (pnl / invested * 100) if invested else 0
        day_pnl   = h.quantity * (q.get("change", 0) or 0)
        total_inv  += invested
        total_curr += curr_val
        holdings_out.append({
            **h.to_dict(),
            "current_price":  round(cp, 2),
            "current_value":  round(curr_val, 2),
            "invested_value": round(invested, 2),
            "pnl":      round(pnl, 2),
            "pnl_percent": round(pnl_pct, 2),
            "change":   q.get("change", 0),
            "change_percent": q.get("change_percent", 0),
            "day_pnl":  round(day_pnl, 2),
        })

    total_pnl     = total_curr - total_inv
    total_pnl_pct = (total_pnl / total_inv * 100) if total_inv else 0

    return jsonify({
        "portfolio": p.to_dict(),
        "holdings":  holdings_out,
        "summary": {
            "total_invested":      round(total_inv, 2),
            "total_current_value": round(total_curr, 2),
            "total_pnl":           round(total_pnl, 2),
            "total_pnl_percent":   round(total_pnl_pct, 2),
            "day_pnl": round(sum(h.get("day_pnl", 0) for h in holdings_out), 2),
        },
    }), 200


@portfolio_bp.route("/<int:pid>/holding", methods=["POST"])
@jwt_required()
def add_holding(pid):
    uid = int(get_jwt_identity())
    if _guest(uid):
        return jsonify({"error": "Not available for guests"}), 403
    p = Portfolio.query.filter_by(id=pid, user_id=uid).first()
    if not p:
        return jsonify({"error": "Portfolio not found"}), 404

    data     = request.get_json() or {}
    symbol   = str(data.get("symbol", "")).upper()
    quantity = float(data.get("quantity", 0))
    price    = float(data.get("price", 0))
    exchange = str(data.get("exchange", "NSE")).upper()

    if not symbol or quantity <= 0 or price <= 0:
        return jsonify({"error": "Invalid data"}), 400

    existing = Holding.query.filter_by(portfolio_id=pid, symbol=symbol).first()
    if existing:
        total_qty          = existing.quantity + quantity
        existing.avg_buy_price = (existing.quantity * existing.avg_buy_price + quantity * price) / total_qty
        existing.quantity  = total_qty
    else:
        q = get_stock_quote(symbol, exchange)
        h = Holding(
            portfolio_id=pid, symbol=symbol,
            company_name=data.get("company_name") or q.get("company_name", symbol),
            quantity=quantity, avg_buy_price=price, exchange=exchange,
        )
        db.session.add(h)

    db.session.add(Transaction(
        user_id=uid, portfolio_id=pid, symbol=symbol,
        company_name=data.get("company_name", symbol),
        transaction_type="BUY", quantity=quantity, price=price,
        total_amount=quantity * price, exchange=exchange,
        notes=data.get("notes", ""),
    ))
    db.session.commit()
    return jsonify({"message": "Holding added"}), 201


@portfolio_bp.route("/<int:pid>/holding/<int:hid>", methods=["PUT"])
@jwt_required()
def edit_holding(pid, hid):
    """Edit quantity and/or avg buy price of a holding"""
    uid = int(get_jwt_identity())
    if _guest(uid):
        return jsonify({"error": "Not available for guests"}), 403
    p = Portfolio.query.filter_by(id=pid, user_id=uid).first()
    if not p:
        return jsonify({"error": "Portfolio not found"}), 404
    h = Holding.query.filter_by(id=hid, portfolio_id=pid).first()
    if not h:
        return jsonify({"error": "Holding not found"}), 404

    data = request.get_json() or {}
    if "quantity" in data:
        new_qty = float(data["quantity"])
        if new_qty <= 0:
            return jsonify({"error": "Quantity must be > 0"}), 400
        h.quantity = new_qty
    if "avg_buy_price" in data:
        new_price = float(data["avg_buy_price"])
        if new_price <= 0:
            return jsonify({"error": "Price must be > 0"}), 400
        h.avg_buy_price = new_price
    if "notes" in data:
        pass  # notes stored on transaction level, not holding

    db.session.commit()
    return jsonify({"message": "Holding updated", "holding": h.to_dict()}), 200


@portfolio_bp.route("/<int:pid>/holding/<int:hid>", methods=["DELETE"])
@jwt_required()
def remove_holding(pid, hid):
    uid = int(get_jwt_identity())
    if _guest(uid):
        return jsonify({"error": "Not available for guests"}), 403
    p = Portfolio.query.filter_by(id=pid, user_id=uid).first()
    if not p:
        return jsonify({"error": "Portfolio not found"}), 404
    h = Holding.query.filter_by(id=hid, portfolio_id=pid).first()
    if not h:
        return jsonify({"error": "Holding not found"}), 404
    db.session.delete(h)
    db.session.commit()
    return jsonify({"message": "Holding removed"}), 200


@portfolio_bp.route("/transactions", methods=["GET"])
@jwt_required()
def get_transactions():
    uid = int(get_jwt_identity())
    if _guest(uid):
        return jsonify({"error": "Not available for guests"}), 403
    txns = (Transaction.query.filter_by(user_id=uid)
            .order_by(Transaction.transaction_date.desc()).limit(100).all())
    return jsonify({"transactions": [t.to_dict() for t in txns]}), 200


@portfolio_bp.route("/analytics/<int:pid>", methods=["GET"])
@jwt_required()
def analytics(pid):
    uid = int(get_jwt_identity())
    if _guest(uid):
        return jsonify({"error": "Not available for guests"}), 403
    p = Portfolio.query.filter_by(id=pid, user_id=uid).first()
    if not p:
        return jsonify({"error": "Portfolio not found"}), 404

    sector_alloc = {}
    holdings_alloc = []
    total_val = 0.0

    for h in p.holdings:
        q = get_stock_quote(h.symbol, h.exchange)
        cv = h.quantity * (q.get("current_price", h.avg_buy_price) or h.avg_buy_price)
        total_val += cv
        sector = STOCK_SECTOR.get(h.symbol.upper(), q.get("sector", "Unknown") or "Unknown")
        sector_alloc[sector] = sector_alloc.get(sector, 0) + cv
        pnl_pct = ((cv - h.quantity * h.avg_buy_price) / (h.quantity * h.avg_buy_price) * 100
                   if h.avg_buy_price else 0)
        holdings_alloc.append({"symbol": h.symbol, "value": round(cv, 2),
                                "pnl_percent": round(pnl_pct, 2), "weight": 0})

    if total_val > 0:
        for h in holdings_alloc:
            h["weight"] = round(h["value"] / total_val * 100, 2)
        for s in sector_alloc:
            sector_alloc[s] = round(sector_alloc[s] / total_val * 100, 2)

    n = len(holdings_alloc)
    divers = min(100, n * 7)

    return jsonify({
        "holdings_allocation": holdings_alloc,
        "sector_allocation":   sector_alloc,
        "total_value":         round(total_val, 2),
        "diversification_score": divers,
        "num_holdings":        n,
    }), 200
