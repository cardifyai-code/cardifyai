import os

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth

from .config import Config

# -------------------------------------------------
# Global extensions (imported by other modules)
# -------------------------------------------------
db = SQLAlchemy()
login_manager = LoginManager()
oauth = OAuth()  # <-- this is what auth.py imports


def create_app() -> Flask:
    """Application factory for CardifyAI."""
    app = Flask(__name__)
    app.config.from_object(Config)

    # ---------------------------------------------
    # Init extensions
    # ---------------------------------------------
    db.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)

    # Where to send users when they need to log in
    # (this should match the route name in auth.py)
    login_manager.login_view = "auth.login"

    # ---------------------------------------------
    # User loader for Flask-Login
    # ---------------------------------------------
    from .models import User

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return User.query.get(int(user_id))
        except (TypeError, ValueError):
            return None

    # ---------------------------------------------
    # Register blueprints
    # ---------------------------------------------
    from .views import views_bp
    from .auth import auth_bp
    from .billing import billing_bp

    app.register_blueprint(views_bp)                # main / dashboard routes
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(billing_bp, url_prefix="/billing")

    # ---------------------------------------------
    # Create tables (Render will call this on boot)
    # ---------------------------------------------
    with app.app_context():
        db.create_all()

    return app
