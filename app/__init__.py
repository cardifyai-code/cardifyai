# app/__init__.py

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth
from sqlalchemy import text

from .config import Config

# Global extensions
db = SQLAlchemy()
login_manager = LoginManager()
oauth = OAuth()


def create_app():
    app = Flask(__name__)

    # Load configuration (env-driven)
    app.config.from_object(Config)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)

    # Import models so SQLAlchemy registers them
    from .models import User, Subscription, Flashcard  # noqa

    # Register blueprints
    from .views import views_bp
    from .auth import auth_bp
    from .billing import billing_bp

    app.register_blueprint(views_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(billing_bp, url_prefix="/billing")

    # Login manager default route
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        """Load user by primary key."""
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    # ----------------------------------------------------
    # AUTO-MIGRATION / SCHEMA PATCHING
    # Ensures DB always has required columns; no manual SQL.
    # ----------------------------------------------------
    with app.app_context():
        db.create_all()

        alter_statements = [
            # --- Billing / plans ---
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan VARCHAR(50) DEFAULT 'free'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_price_id VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE",

            # --- Monthly quota ---
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_card_quota INTEGER DEFAULT 1000",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS cards_generated_this_month INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_reset_at TIMESTAMP",

            # --- Daily quota ---
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_cards_generated INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_reset_date DATE",
        ]

        for sql in alter_statements:
            try:
                db.session.execute(text(sql))
                db.session.commit()
            except Exception:
                db.session.rollback()

    return app
