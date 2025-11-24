# app/__init__.py

import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth

from .config import Config

# Global extensions
db = SQLAlchemy()
login_manager = LoginManager()
oauth = OAuth()


def create_app():
    app = Flask(__name__)

    # Load all config from Config class (uses env vars)
    app.config.from_object(Config)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)

    # Import models so SQLAlchemy knows about them
    from .models import User, Subscription, Flashcard

    # Register blueprints
    from .views import views_bp
    from .auth import auth_bp
    from .billing import billing_bp

    app.register_blueprint(views_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(billing_bp, url_prefix="/billing")

    # Login manager config
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    # Create tables on startup
    with app.app_context():
        db.create_all()

    return app
