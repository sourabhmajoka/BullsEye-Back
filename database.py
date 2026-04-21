"""
Database setup for BullsEye
Handles auto-migration for existing SQLite databases (adds missing columns).
"""
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

def _migrate_sqlite(engine):
    """
    Add any missing columns to existing SQLite databases.
    SQLite does not support ALTER TABLE ADD COLUMN IF NOT EXISTS,
    so we check existing columns first and only add what's missing.
    """
    with engine.connect() as conn:
        # Get existing columns in the users table
        result = conn.execute(
            db.text("PRAGMA table_info(users)")
        )
        existing_cols = {row[1] for row in result}   # row[1] = column name

        migrations = [
            ("verification_token",          "ALTER TABLE users ADD COLUMN verification_token TEXT"),
            ("verification_token_expires",  "ALTER TABLE users ADD COLUMN verification_token_expires DATETIME"),
            ("phone",                       "ALTER TABLE users ADD COLUMN phone VARCHAR(15)"),
            ("profile_pic",                 "ALTER TABLE users ADD COLUMN profile_pic VARCHAR(500)"),
            ("investment_goal",             "ALTER TABLE users ADD COLUMN investment_goal VARCHAR(50)"),
            ("last_login",                  "ALTER TABLE users ADD COLUMN last_login DATETIME"),
        ]

        for col_name, sql in migrations:
            if col_name not in existing_cols:
                try:
                    conn.execute(db.text(sql))
                    conn.commit()
                    print(f"✅ Migration: added column '{col_name}' to users table")
                except Exception as e:
                    print(f"⚠️  Migration skipped for '{col_name}': {e}")


def init_db(app):
    """Initialize database, run migrations, create guest user."""
    # Create all tables for new installs
    db.create_all()

    # Run migrations for existing installs (adds missing columns)
    _migrate_sqlite(db.engine)

    # Ensure guest user exists
    from models.user import User
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
        db.session.commit()
        print("✅ Guest user created")
