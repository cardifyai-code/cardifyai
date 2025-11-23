from flask import (
    Blueprint,
    redirect,
    url_for,
    flash,
    current_app,
)
from flask_login import login_user, logout_user, login_required, current_user

from . import db, oauth
from .models import User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _get_google_client():
    """Return a Google OAuth client, registering it once if necessary."""
    client = oauth.create_client("google")
    if client:
        return client

    return oauth.register(
        name="google",
        client_id=current_app.config.get("GOOGLE_CLIENT_ID"),
        client_secret=current_app.config.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@auth_bp.route("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("views.dashboard"))
    google = _get_google_client()
    redirect_uri = url_for("auth.google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)


@auth_bp.route("/google/callback")
def google_callback():
    google = _get_google_client()
    token = google.authorize_access_token()

    userinfo = google.get(google.server_metadata["userinfo_endpoint"]).json()

    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        flash("Google account did not provide an email.", "danger")
        return redirect(url_for("views.home"))

    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email=email, tier="free")
        db.session.add(user)
        db.session.commit()

    # enforce admin privileges
    admin_email = current_app.config.get("ADMIN_EMAIL", "").lower()
    if admin_email and email == admin_email:
        user.is_admin = True
        user.tier = "premium"
        db.session.commit()

    login_user(user)
    flash("Logged in with Google.", "success")
    return redirect(url_for("views.dashboard"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("views.home"))
