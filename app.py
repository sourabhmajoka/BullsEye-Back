"""
BullsEye - Indian Stock Market Analysis Platform
Flask Backend API
"""

from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from database import db, init_db
from routes.auth import auth_bp
from routes.stocks import stocks_bp
from routes.portfolio import portfolio_bp
from routes.market import market_bp
from routes.ai_assistant import ai_bp
from routes.watchlist import watchlist_bp
import os
from datetime import timedelta

# Load .env file first
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
except Exception:
    pass

def create_app():
    app = Flask(__name__)
    
    # Configuration
    secret_key = os.environ.get('SECRET_KEY')
    jwt_secret_key = os.environ.get('JWT_SECRET_KEY')
    if not secret_key or not jwt_secret_key:
        raise RuntimeError(
            "SECRET_KEY and JWT_SECRET_KEY must be set as environment variables. "
            "Generate strong random values and add them in Render → Environment."
        )
    app.config['SECRET_KEY'] = secret_key
    app.config['JWT_SECRET_KEY'] = jwt_secret_key
    # 30 days — users should stay logged in across normal usage patterns.
    # They log out explicitly, not because a token silently expired overnight.
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)

    # PostgreSQL — fix Render's legacy "postgres://" scheme
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL must be set. "
            "Example: postgresql://user:password@host:5432/bullseye"
        )
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Connection pool tuning for Render free tier.
    # Render sleeps after 15 min inactivity; idle connections go stale.
    # pool_pre_ping tests each connection before use and recycles dead ones,
    # so the first request after a sleep period never throws a connection error.
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,       # test connection health before every use
        'pool_recycle': 280,         # recycle connections every ~4.5 min
        'pool_size': 5,              # keep 5 connections open
        'max_overflow': 10,          # allow up to 10 extra under load
        'connect_args': {
            'connect_timeout': 10,   # fail fast if DB is unreachable
        },
    }
    
    # AI API Keys (set any ONE in .env to enable full AI)
    app.config['GROQ_API_KEY']   = os.environ.get('GROQ_API_KEY', '')
    app.config['GEMINI_API_KEY'] = os.environ.get('GEMINI_API_KEY', '')
    app.config['CLAUDE_API_KEY'] = os.environ.get('CLAUDE_API_KEY',
                                    os.environ.get('OPENAI_API_KEY', ''))
    # Pass to os.environ so ai_assistant.py can read them
    for k in ('GROQ_API_KEY', 'GEMINI_API_KEY', 'CLAUDE_API_KEY'):
        if app.config[k]:
            os.environ[k] = app.config[k]
    
    # Initialize extensions
    # Allow both Vercel production URL and localhost for local dev
    default_origins = 'https://bullseye-analysis.vercel.app,http://localhost:3000,http://127.0.0.1:3000'
    ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', default_origins).split(',')

    CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}})
    db.init_app(app)
    jwt = JWTManager(app)
    
    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(stocks_bp, url_prefix='/api/stocks')
    app.register_blueprint(portfolio_bp, url_prefix='/api/portfolio')
    app.register_blueprint(market_bp, url_prefix='/api/market')
    app.register_blueprint(ai_bp, url_prefix='/api/ai')
    app.register_blueprint(watchlist_bp, url_prefix='/api/watchlist')
    
    # Create tables
    with app.app_context():
        init_db(app)
    
    @app.route('/api/health')
    def health():
        return {'status': 'ok', 'message': 'BullsEye API is running', 'version': '1.0.0'}
    
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
