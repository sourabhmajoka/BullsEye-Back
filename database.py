"""
Database setup for BullsEye
PostgreSQL via Flask-SQLAlchemy.
All schema changes are handled by SQLAlchemy's create_all() —
no manual migrations needed.
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_db(app):
    """Create all tables (idempotent) and seed the guest user."""
    # create_all() is safe to call on every startup:
    # it only creates tables that do not already exist.
    db.create_all()

    # Ensure the guest user always exists
    from models.user import User, Portfolio
    guest = User.query.filter_by(username='guest').first()
    if not guest:
        guest = User(
            username='guest',
            email='guest@bullseye.in',
            full_name='Guest User',
            is_guest=True,
            is_verified=True,
        )
        guest.set_password('guest123')
        db.session.add(guest)
        db.session.flush()

        portfolio = Portfolio(
            user_id=guest.id,
            name='Guest Portfolio',
            description='Read-only demo portfolio',
        )
        db.session.add(portfolio)
        db.session.commit()
        print("✅ Guest user created")
