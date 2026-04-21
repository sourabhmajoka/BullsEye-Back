"""
Authentication — register/login/guest + email verification
Uses token stored in DB; sends via SMTP (Gmail App Password) or logs to console if unconfigured.
"""
import os
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from database import db
from models.user import User, Portfolio

auth_bp = Blueprint('auth', __name__)

# ─── Email config (reads from .env) ─────────────────────────────────────────

SMTP_EMAIL    = os.environ.get('SMTP_EMAIL',    '')   # your Gmail address
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')   # Gmail App Password
APP_URL       = os.environ.get('APP_URL',       'http://localhost:3000')

def _send_verification_email(to_email, full_name, token):
    """Send verification email. Falls back to console log if SMTP not configured."""
    verify_url = f"{APP_URL}/verify-email?token={token}"
    
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        # No SMTP configured — log to console (dev mode)
        print(f"\n{'='*60}")
        print(f"📧 EMAIL VERIFICATION (Dev Mode — no SMTP configured)")
        print(f"   To: {to_email}")
        print(f"   Verify URL: {verify_url}")
        print(f"   Token: {token}")
        print(f"{'='*60}\n")
        return True
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = '✅ Verify your BullsEye account'
        msg['From']    = SMTP_EMAIL
        msg['To']      = to_email

        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 32px; background: #020617; color: #e2e8f0; border-radius: 16px;">
          <div style="text-align: center; margin-bottom: 24px;">
            <div style="background: linear-gradient(135deg, #10b981, #06b6d4); width: 48px; height: 48px; border-radius: 12px; display: inline-flex; align-items: center; justify-content: center; margin-bottom: 12px;">
              <span style="color: white; font-size: 20px; font-weight: 900;">📈</span>
            </div>
            <h1 style="color: white; margin: 0; font-size: 24px;">BullsEye</h1>
            <p style="color: #94a3b8; margin: 4px 0 0;">Indian Stock Market Intelligence</p>
          </div>
          <h2 style="color: white;">Hi {full_name or 'Investor'}! 👋</h2>
          <p style="color: #94a3b8; line-height: 1.6;">Welcome to BullsEye! Click the button below to verify your email and unlock:</p>
          <ul style="color: #94a3b8; line-height: 1.8;">
            <li>📊 Real-time portfolio tracking</li>
            <li>⭐ Personalized watchlist</li>
            <li>🤖 AI stock analysis assistant</li>
            <li>📈 Full market analytics</li>
          </ul>
          <div style="text-align: center; margin: 32px 0;">
            <a href="{verify_url}" style="background: linear-gradient(135deg, #10b981, #06b6d4); color: white; text-decoration: none; padding: 14px 32px; border-radius: 12px; font-weight: bold; font-size: 16px; display: inline-block;">
              ✅ Verify My Email
            </a>
          </div>
          <p style="color: #64748b; font-size: 12px; text-align: center;">
            This link expires in 24 hours. If you didn't create a BullsEye account, please ignore this email.
          </p>
          <p style="color: #475569; font-size: 11px; text-align: center; margin-top: 8px;">
            Or copy this URL: {verify_url}
          </p>
        </div>
        """
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(SMTP_EMAIL, SMTP_PASSWORD)
            smtp.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Email send failed: {e}")
        print(f"Verify URL for {to_email}: {verify_url}")
        return False


# ─── Routes ───────────────────────────────────────────────────────────────────

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username  = data.get('username', '').strip()
    email     = data.get('email', '').strip().lower()
    password  = data.get('password', '')
    full_name = data.get('full_name', '').strip()

    if not all([username, email, password]):
        return jsonify({'error': 'Username, email, and password are required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    if '@' not in email or '.' not in email.split('@')[-1]:
        return jsonify({'error': 'Please enter a valid email address'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already taken'}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409

    # Generate verification token (24h expiry)
    token    = secrets.token_urlsafe(32)
    token_exp = datetime.utcnow() + timedelta(hours=24)

    user = User(
        username=username, email=email,
        full_name=full_name or username,
        risk_profile=data.get('risk_profile', 'moderate'),
        investment_goal=data.get('investment_goal', ''),
        is_verified=False,                # requires email verification
        verification_token=token,
        verification_token_expires=token_exp,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()

    # Default portfolio
    portfolio = Portfolio(user_id=user.id, name='My Portfolio', description='Default portfolio')
    db.session.add(portfolio)
    db.session.commit()

    # Send verification email
    _send_verification_email(email, full_name or username, token)

    # In dev mode (no SMTP), auto-verify for convenience
    if not SMTP_EMAIL:
        user.is_verified = True
        db.session.commit()
        jwt_token = create_access_token(identity=str(user.id))
        return jsonify({
            'message': 'Registration successful! (Dev mode: auto-verified)',
            'token': jwt_token,
            'user': user.to_dict(),
            'dev_note': 'Configure SMTP_EMAIL and SMTP_PASSWORD in .env for real email verification'
        }), 201

    return jsonify({
        'message': 'Registration successful! Please check your email to verify your account.',
        'email_sent': True
    }), 201


@auth_bp.route('/verify-email', methods=['POST'])
def verify_email():
    data  = request.get_json() or {}
    token = data.get('token', '').strip()
    if not token:
        return jsonify({'error': 'Verification token required'}), 400

    user = User.query.filter_by(verification_token=token).first()
    if not user:
        return jsonify({'error': 'Invalid or expired verification token'}), 400
    if user.verification_token_expires and datetime.utcnow() > user.verification_token_expires:
        return jsonify({'error': 'Verification token has expired. Please register again.'}), 400

    user.is_verified = True
    user.verification_token = None
    user.verification_token_expires = None
    db.session.commit()

    jwt_token = create_access_token(identity=str(user.id))
    return jsonify({
        'message': 'Email verified successfully! Welcome to BullsEye.',
        'token': jwt_token,
        'user': user.to_dict()
    }), 200


@auth_bp.route('/resend-verification', methods=['POST'])
def resend_verification():
    data  = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    user  = User.query.filter_by(email=email).first()

    if not user:
        # Don't reveal if email exists
        return jsonify({'message': 'If that email is registered, a verification link has been sent.'}), 200
    if user.is_verified:
        return jsonify({'message': 'Your email is already verified. Please sign in.'}), 200

    token     = secrets.token_urlsafe(32)
    token_exp = datetime.utcnow() + timedelta(hours=24)
    user.verification_token = token
    user.verification_token_expires = token_exp
    db.session.commit()

    _send_verification_email(email, user.full_name, token)
    return jsonify({'message': 'Verification email resent. Please check your inbox.'}), 200


@auth_bp.route('/login', methods=['POST'])
def login():
    data       = request.get_json() or {}
    identifier = data.get('identifier', '').strip()
    password   = data.get('password', '')

    if not identifier or not password:
        return jsonify({'error': 'Credentials required'}), 400

    user = User.query.filter(
        (User.username == identifier) | (User.email == identifier.lower())
    ).first()

    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid email/username or password'}), 401

    if not user.is_guest and not user.is_verified:
        return jsonify({
            'error': 'Please verify your email before signing in.',
            'needs_verification': True,
            'email': user.email
        }), 403

    user.last_login = datetime.utcnow()
    db.session.commit()

    token = create_access_token(identity=str(user.id))
    return jsonify({'message': 'Login successful', 'token': token, 'user': user.to_dict()}), 200


@auth_bp.route('/guest', methods=['POST'])
def guest_login():
    guest = User.query.filter_by(username='guest').first()
    if not guest:
        guest = User(username='guest', email='guest@bullseye.in',
                     full_name='Guest User', is_guest=True, is_verified=True)
        guest.set_password('guest123')
        db.session.add(guest)
        db.session.commit()
    token = create_access_token(identity=str(guest.id))
    return jsonify({
        'message': 'Guest access granted', 'token': token, 'user': guest.to_dict(),
        'limitations': ['No portfolio', 'No watchlist', 'No AI assistant', 'Read-only data']
    }), 200


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_me():
    uid  = int(get_jwt_identity())
    user = User.query.get(uid)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'user': user.to_dict()}), 200


@auth_bp.route('/update-profile', methods=['PUT'])
@jwt_required()
def update_profile():
    uid  = int(get_jwt_identity())
    user = User.query.get(uid)
    if not user or user.is_guest:
        return jsonify({'error': 'Not allowed'}), 403
    data = request.get_json() or {}
    if data.get('full_name'):       user.full_name       = data['full_name']
    if data.get('phone'):           user.phone           = data['phone']
    if data.get('risk_profile'):    user.risk_profile    = data['risk_profile']
    if data.get('investment_goal'): user.investment_goal = data['investment_goal']
    db.session.commit()
    return jsonify({'message': 'Profile updated', 'user': user.to_dict()}), 200


@auth_bp.route('/change-password', methods=['PUT'])
@jwt_required()
def change_password():
    uid  = int(get_jwt_identity())
    user = User.query.get(uid)
    if not user or user.is_guest:
        return jsonify({'error': 'Not allowed'}), 403
    data = request.get_json() or {}
    if not user.check_password(data.get('old_password', '')):
        return jsonify({'error': 'Current password is incorrect'}), 400
    new_pwd = data.get('new_password', '')
    if len(new_pwd) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    user.set_password(new_pwd)
    db.session.commit()
    return jsonify({'message': 'Password changed successfully'}), 200
