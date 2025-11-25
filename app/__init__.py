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

    # Load config
    app.config.from_object(Config)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)

    # Import models so SQLAlchemy is aware of them
    from .models import User, Subscription, Flashcard  # noqa

    # Register blueprints
    from .views import views_bp
    from .auth import auth_bp
    from .billing import billing_bp

    app.register_blueprint(views_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(billing_bp, url_prefix="/billing")

    # Login manager configuration
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    # ------------------------------
    # Database setup / schema patch
    # ------------------------------
    with app.app_context():
        db.create_all()

        # Patch schema safely without Alembic
        alter_statements = [
            # Plan / subscription fields
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan VARCHAR(50) DEFAULT 'free'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_price_id VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE",

            # Monthly quota fields
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_card_quota INTEGER DEFAULT 1000',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS cards_generated_this_month INTEGER DEFAULT 0',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_reset_at TIMESTAMP',

            # Daily quota fields
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_cards_generated INTEGER DEFAULT 0',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_reset_date DATE',

            # Token tracking fields (required to stop Google login errors)
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_input_tokens BIGINT DEFAULT 0',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_output_tokens BIGINT DEFAULT 0',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_input_tokens BIGINT DEFAULT 0',
            'ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_output_tokens BIGINT DEFAULT 0',
        ]

        for sql in alter_statements:
            try:
                db.session.execute(text(sql))
                db.session.commit()
            except Exception:
                # Column may already exist — safely continue
                db.session.rollback()

    return app
