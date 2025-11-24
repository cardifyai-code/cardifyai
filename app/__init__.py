import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from .config import Config

db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # =============================
    # Initialize Extensions
    # =============================
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "views.login"
    login_manager.login_message_category = "info"

    # =============================
    # Import Models
    # =============================
    from .models import User  # Avoid circular imports

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # =============================
    # Register Blueprints
    # =============================
    from .views import views_bp
    from .auth import auth_bp
    from .billing import billing_bp

    app.register_blueprint(views_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(billing_bp)

    # =============================
    # Create Database on Startup
    # =============================
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            print("❌ DATABASE INIT ERROR:", e)

    # =============================
    # Stripe Webhook Route Load
    # =============================
    try:
        import stripe
        stripe.api_key = Config.STRIPE_SECRET_KEY
    except Exception:
        print("⚠️ Stripe not initialized (likely during local dev).")

    return app
