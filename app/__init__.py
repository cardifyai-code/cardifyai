Here’s the complete, fully updated `app/__init__.py` with everything wired up, including the new `Review` model import and keeping all previous behavior intact (just fixing the analytics user tracking to use `current_user` properly):

```python
# app/__init__.py

from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from authlib.integrations.flask_client import OAuth
from sqlalchemy import text

from .config import Config

# Global extensions
db = SQLAlchemy()
login_manager = LoginManager()
oauth = OAuth()


def create_app():
    app = Flask(__name__)

    # Load configuration
    app.config.from_object(Config)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)

    # Import models so SQLAlchemy is aware of them
    # (including Review for the new reviews system)
    from .models import User, Subscription, Flashcard, Visit, Review  # noqa

    # ------------------------
    # Register blueprints
    # ------------------------
    from .views import views_bp
    from .auth import auth_bp
    from .billing import billing_bp
    from .extension_api import extension_api

    app.register_blueprint(views_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(billing_bp, url_prefix="/billing")
    app.register_blueprint(extension_api, url_prefix="/api/extension")

    # ------------------------
    # Login manager settings
    # ------------------------
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    # ------------------------
    # Database initialization
    # ------------------------
    with app.app_context():
        db.create_all()

        # Safe schema patches (no Alembic needed)
        alter_statements = [
            # Billing / plan fields
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan VARCHAR(50) DEFAULT 'free'",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_price_id VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE",

            # Monthly quota
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_card_quota INTEGER DEFAULT 1000",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS cards_generated_this_month INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_reset_at TIMESTAMP",

            # Daily quota
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_cards_generated INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_reset_date DATE",

            # Token usage (required for AI cost tracking)
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_input_tokens BIGINT DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_output_tokens BIGINT DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_input_tokens BIGINT DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_output_tokens BIGINT DEFAULT 0",
        ]

        for sql in alter_statements:
            try:
                db.session.execute(text(sql))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # Note:
        # - Review table is created by db.create_all() if it does not exist.
        # - No ALTERs are needed for reviews since it's a new table, not a
        #   modification of an existing one.

    # ------------------------
    # Automatic visit tracking
    # ------------------------
    @app.before_request
    def track_visit():
        """
        Lightweight analytics:
        - tracks path, user id, IP, and user agent
        - ignored for static files + favicon
        - super cheap (one insert)

        NOTE:
        - views.log_visit() also logs visits for key pages (/, /dashboard, /admin, etc.).
          That explicit logging is kept for more intentional analytics.
        - This before_request hook is a generic, catch-all tracker for other routes
          (auth, billing, etc.).
        """
        try:
            path = request.path or ""

            # Skip static assets and favicon
            if path.startswith("/static") or path.startswith("/favicon"):
                return

            from .models import Visit  # local import avoids circular deps

            # Use Flask-Login's current_user instead of a non-existent request.user
            user_id = None
            if current_user and getattr(current_user, "is_authenticated", False):
                user_id = current_user.id

            v = Visit(
                user_id=user_id,
                path=path,
                ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
                user_agent=request.headers.get("User-Agent"),
            )
            db.session.add(v)
            db.session.commit()

        except Exception:
            db.session.rollback()

    return app
```
