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
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'bullseye-secret-key-2024-india')
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'bullseye-jwt-secret-2024')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
        'DATABASE_URL', 
        f"sqlite:///{os.path.join(os.path.dirname(__file__), 'bullseye.db')}"
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
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
    ALLOWED_ORIGINS = os.environ.get(
        'ALLOWED_ORIGINS',
        'https://bullseye-analysis.vercel.app'
    ).split(',')
    
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
