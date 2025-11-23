from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth

from .config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"

oauth = OAuth()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)

    # Import & register blueprints
    from .auth import auth_bp
    from .views import views_bp
    from .billing import billing_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(billing_bp)

    # Create database tables if not present
    with app.app_context():
        db.create_all()

    return app
