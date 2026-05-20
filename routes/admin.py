"""
Admin routes for BullsEye.
All routes are protected by a separate admin JWT.
Credentials are verified against ADMIN_USERNAME and ADMIN_PASSWORD env vars.
"""
import os
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, verify_jwt_in_request
from functools import wraps
from sqlalchemy import func, text
from database import db
from models.user import User, Portfolio, Holding, Watchlist, AIConversation
from routes.auth import (
    _send_verification_email, _send_deletion_email,
    _send_ban_email, _send_unban_email, _send_manual_verify_email
)

admin_bp = Blueprint('admin', __name__)

ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', '')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')
ADMIN_JWT_PREFIX = 'admin_'


def admin_required(fn):
    """Decorator that checks the JWT belongs to an admin session."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        identity = get_jwt_identity()
        if not identity or not identity.startswith(ADMIN_JWT_PREFIX):
            return jsonify({'error': 'Admin access required'}), 403
        return fn(*args, **kwargs)
    return wrapper


# ── Login ─────────────────────────────────────────────────────────────────────
@admin_bp.route('/login', methods=['POST'])
def admin_login():
    data     = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        return jsonify({'error': 'Admin not configured'}), 503

    if username != ADMIN_USERNAME or password != ADMIN_PASSWORD:
        return jsonify({'error': 'Invalid admin credentials'}), 401

    # Prefix identity so it can never be confused with a user JWT
    token = create_access_token(
        identity=f'{ADMIN_JWT_PREFIX}{username}',
        expires_delta=timedelta(hours=4)
    )
    return jsonify({'token': token, 'message': 'Admin access granted'}), 200


# ── Overview Stats ─────────────────────────────────────────────────────────────
@admin_bp.route('/stats', methods=['GET'])
@admin_required
def get_stats():
    now   = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week  = today - timedelta(days=7)
    month = today - timedelta(days=30)

    total_users     = User.query.filter_by(is_guest=False).count()
    verified_users  = User.query.filter_by(is_verified=True, is_guest=False).count()
    unverified      = User.query.filter_by(is_verified=False, is_guest=False).count()
    new_today       = User.query.filter(User.created_at >= today,  User.is_guest==False).count()
    new_week        = User.query.filter(User.created_at >= week,   User.is_guest==False).count()
    new_month       = User.query.filter(User.created_at >= month,  User.is_guest==False).count()

    total_portfolios = Portfolio.query.count()
    total_holdings   = Holding.query.count()
    total_watchlist  = Watchlist.query.count()

    try:
        total_ai = db.session.execute(text('SELECT COUNT(*) FROM ai_conversations')).scalar()
    except Exception:
        total_ai = 0

    return jsonify({
        'users': {
            'total':      total_users,
            'verified':   verified_users,
            'unverified': unverified,
            'new_today':  new_today,
            'new_week':   new_week,
            'new_month':  new_month,
        },
        'app': {
            'total_portfolios': total_portfolios,
            'total_holdings':   total_holdings,
            'total_watchlist':  total_watchlist,
            'total_ai_chats':   total_ai,
        }
    }), 200


# ── Signup Trend (last 30 days) ────────────────────────────────────────────────
@admin_bp.route('/signup-trend', methods=['GET'])
@admin_required
def signup_trend():
    rows = db.session.execute(text("""
        SELECT DATE(created_at) as day, COUNT(*) as count
        FROM users
        WHERE is_guest = false
          AND created_at >= NOW() - INTERVAL '30 days'
        GROUP BY DATE(created_at)
        ORDER BY day ASC
    """)).fetchall()

    data = [{'date': str(row[0]), 'signups': row[1]} for row in rows]
    return jsonify({'trend': data}), 200


# ── All Users ──────────────────────────────────────────────────────────────────
@admin_bp.route('/users', methods=['GET'])
@admin_required
def get_users():
    users = User.query.filter_by(is_guest=False).order_by(User.created_at.desc()).all()

    result = []
    for u in users:
        holdings_count  = Holding.query.join(Portfolio).filter(Portfolio.user_id == u.id).count()
        watchlist_count = Watchlist.query.filter_by(user_id=u.id).count()
        try:
            ai_count = db.session.execute(
                text('SELECT COUNT(*) FROM ai_conversations WHERE user_id = :uid'),
                {'uid': u.id}
            ).scalar()
        except Exception:
            ai_count = 0

        result.append({
            'id':           u.id,
            'username':     u.username,
            'full_name':    u.full_name,
            'email':        u.email,
            'is_verified':  u.is_verified,
            'is_banned':    u.is_banned,
            'risk_profile': u.risk_profile,
            'created_at':   u.created_at.isoformat() if u.created_at else None,
            'last_login':   u.last_login.isoformat()  if u.last_login  else None,
            'holdings':     holdings_count,
            'watchlist':    watchlist_count,
            'ai_chats':     ai_count,
        })

    return jsonify({'users': result}), 200


# ── Most Popular Stocks ────────────────────────────────────────────────────────
@admin_bp.route('/popular-stocks', methods=['GET'])
@admin_required
def popular_stocks():
    portfolio_stocks = db.session.execute(text("""
        SELECT symbol, COUNT(*) as count
        FROM holdings
        GROUP BY symbol
        ORDER BY count DESC
        LIMIT 10
    """)).fetchall()

    watchlist_stocks = db.session.execute(text("""
        SELECT symbol, COUNT(*) as count
        FROM watchlists
        GROUP BY symbol
        ORDER BY count DESC
        LIMIT 10
    """)).fetchall()

    return jsonify({
        'most_held':      [{'symbol': r[0], 'count': r[1]} for r in portfolio_stocks],
        'most_watched':   [{'symbol': r[0], 'count': r[1]} for r in watchlist_stocks],
    }), 200


# ── Delete User ────────────────────────────────────────────────────────────────
@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    user = User.query.get(user_id)
    if not user or user.is_guest:
        return jsonify({'error': 'User not found'}), 404

    # Save details before deletion
    deleted_email    = user.email
    deleted_name     = user.full_name
    deleted_username = user.username

    db.session.execute(text('DELETE FROM transactions    WHERE user_id = :uid'), {'uid': user_id})
    db.session.execute(text('DELETE FROM ai_conversations WHERE user_id = :uid'), {'uid': user_id})
    db.session.delete(user)
    db.session.commit()

    # Send deletion email with admin flag
    import threading
    threading.Thread(
        target=_send_deletion_email,
        args=(deleted_email, deleted_name, deleted_username),
        kwargs={'by_admin': True},
        daemon=True,
    ).start()

    return jsonify({'message': f'User {deleted_username} deleted'}), 200


# ── Resend Verification ────────────────────────────────────────────────────────
@admin_bp.route('/users/<int:user_id>/resend-verification', methods=['POST'])
@admin_required
def admin_resend_verification(user_id):
    import secrets
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    if user.is_verified:
        return jsonify({'message': 'User is already verified'}), 200

    token     = secrets.token_urlsafe(32)
    token_exp = datetime.utcnow() + timedelta(hours=48)
    user.verification_token         = token
    user.verification_token_expires = token_exp
    db.session.commit()

    import threading
    threading.Thread(
        target=_send_verification_email,
        args=(user.email, user.full_name, token),
        daemon=True,
    ).start()

    return jsonify({'message': f'Verification email resent to {user.email}'}), 200

# ── User Detail ────────────────────────────────────────────────────────────────
@admin_bp.route('/users/<int:user_id>/detail', methods=['GET'])
@admin_required
def get_user_detail(user_id):
    user = User.query.get(user_id)
    if not user or user.is_guest:
        return jsonify({'error': 'User not found'}), 404

    holdings  = Holding.query.join(Portfolio).filter(Portfolio.user_id == user_id).all()
    watchlist = Watchlist.query.filter_by(user_id=user_id).all()
    try:
        ai_count = db.session.execute(
            text('SELECT COUNT(*) FROM ai_conversations WHERE user_id = :uid'), {'uid': user_id}
        ).scalar()
    except Exception:
        ai_count = 0

    return jsonify({
        'user': {
            'id':           user.id,
            'username':     user.username,
            'full_name':    user.full_name,
            'email':        user.email,
            'phone':        user.phone,
            'risk_profile': user.risk_profile,
            'investment_goal': user.investment_goal,
            'is_verified':  user.is_verified,
            'is_banned':    user.is_banned,
            'ban_reason':   user.ban_reason,
            'banned_until': user.banned_until.isoformat() if user.banned_until else None,
            'banned_at':    user.banned_at.isoformat()    if user.banned_at    else None,
            'created_at':   user.created_at.isoformat()   if user.created_at   else None,
            'last_login':   user.last_login.isoformat()   if user.last_login   else None,
        },
        'holdings':  [{'symbol': h.symbol, 'company_name': h.company_name, 'quantity': h.quantity, 'avg_buy_price': h.avg_buy_price} for h in holdings],
        'watchlist': [{'symbol': w.symbol, 'company_name': w.company_name} for w in watchlist],
        'ai_chats':  ai_count,
    }), 200


# ── Ban User ────────────────────────────────────────────────────────────────────
@admin_bp.route('/users/<int:user_id>/ban', methods=['POST'])
@admin_required
def ban_user(user_id):
    user = User.query.get(user_id)
    if not user or user.is_guest:
        return jsonify({'error': 'User not found'}), 404

    data         = request.get_json() or {}
    reason       = data.get('reason', '').strip()
    duration_days = data.get('duration_days')  # None = manual

    user.is_banned    = True
    user.ban_reason   = reason or None
    user.banned_at    = datetime.utcnow()
    user.banned_until = (
        datetime.utcnow() + timedelta(days=int(duration_days))
        if duration_days else None
    )
    db.session.commit()

    import threading
    threading.Thread(
        target=_send_ban_email,
        args=(user.email, user.full_name, user.username, reason, user.banned_until),
        daemon=True,
    ).start()

    return jsonify({'message': f'User @{user.username} has been suspended'}), 200


# ── Unban User ──────────────────────────────────────────────────────────────────
@admin_bp.route('/users/<int:user_id>/unban', methods=['POST'])
@admin_required
def unban_user(user_id):
    user = User.query.get(user_id)
    if not user or user.is_guest:
        return jsonify({'error': 'User not found'}), 404

    user.is_banned    = False
    user.ban_reason   = None
    user.banned_until = None
    user.banned_at    = None
    db.session.commit()

    import threading
    threading.Thread(
        target=_send_unban_email,
        args=(user.email, user.full_name, user.username),
        kwargs={'auto_expired': False},
        daemon=True,
    ).start()

    return jsonify({'message': f'User @{user.username} has been reinstated'}), 200


# ── Manual Verify ───────────────────────────────────────────────────────────────
@admin_bp.route('/users/<int:user_id>/verify', methods=['POST'])
@admin_required
def manual_verify(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    if user.is_verified:
        return jsonify({'message': 'User already verified'}), 200

    user.is_verified                = True
    user.verification_token         = None
    user.verification_token_expires = None
    db.session.commit()

    import threading
    threading.Thread(
        target=_send_manual_verify_email,
        args=(user.email, user.full_name, user.username),
        daemon=True,
    ).start()

    return jsonify({'message': f'User @{user.username} manually verified'}), 200


# ── Export Users CSV ────────────────────────────────────────────────────────────
@admin_bp.route('/export-users', methods=['GET'])
@admin_required
def export_users():
    users = User.query.filter_by(is_guest=False).order_by(User.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Full Name', 'Username', 'Email', 'Verified', 'Banned',
                     'Risk Profile', 'Joined', 'Last Login'])
    for u in users:
        writer.writerow([
            u.id, u.full_name or '', u.username, u.email,
            'Yes' if u.is_verified else 'No',
            'Yes' if u.is_banned   else 'No',
            u.risk_profile or '',
            u.created_at.strftime('%Y-%m-%d') if u.created_at else '',
            u.last_login.strftime('%Y-%m-%d') if u.last_login else 'Never',
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=bullseye_users.csv'}
    )


# ── App Stats Over Time ─────────────────────────────────────────────────────────
@admin_bp.route('/app-stats', methods=['GET'])
@admin_required
def app_stats():
    holdings_trend = db.session.execute(text("""
        SELECT DATE(added_at) as day, COUNT(*) as count
        FROM holdings
        WHERE added_at >= NOW() - INTERVAL '30 days'
        GROUP BY DATE(added_at)
        ORDER BY day ASC
    """)).fetchall()

    ai_trend = db.session.execute(text("""
        SELECT DATE(created_at) as day, COUNT(*) as count
        FROM ai_conversations
        WHERE created_at >= NOW() - INTERVAL '30 days'
          AND role = 'user'
        GROUP BY DATE(created_at)
        ORDER BY day ASC
    """)).fetchall()

    return jsonify({
        'holdings_trend': [{'date': str(r[0]), 'count': r[1]} for r in holdings_trend],
        'ai_trend':       [{'date': str(r[0]), 'count': r[1]} for r in ai_trend],
    }), 200