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


# ======================================================
# Helper: Retrieve or register Google OAuth client
# ======================================================
def _get_google_client():
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


# ======================================================
# Login → Redirect to Google
# ======================================================
@auth_bp.route("/login")
def login():
    """
    Start Google OAuth login.
    In production (Render), force HTTPS for redirect_uri.
    """
    if current_user.is_authenticated:
        return redirect(url_for("views.dashboard"))

    google = _get_google_client()

    # HTTPS required on Render/custom domain
    if current_app.config.get("FLASK_ENV") == "production":
        redirect_uri = url_for("auth.google_callback", _external=True, _scheme="https")
    else:
        redirect_uri = url_for("auth.google_callback", _external=True)

    current_app.logger.info(f"[Google OAuth] redirect_uri = {redirect_uri}")
    return google.authorize_redirect(redirect_uri)


# ======================================================
# OAuth Callback Handler
# ======================================================
@auth_bp.route("/google/callback")
def google_callback():
    google = _get_google_client()
    token = google.authorize_access_token()

    userinfo = google.get(google.server_metadata["userinfo_endpoint"]).json()
    email = (userinfo.get("email") or "").strip().lower()

    if not email:
        flash("Google did not provide an email address.", "danger")
        return redirect(url_for("views.index"))

    # Create or load user
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email=email, tier="free")
        db.session.add(user)
        db.session.commit()

    # Admin auto-upgrade
    admin_email = current_app.config.get("ADMIN_EMAIL", "").lower()
    if admin_email and email == admin_email:
        user.is_admin = True
        user.tier = "premium"
        db.session.commit()

    login_user(user)
    flash("Successfully logged in with Google!", "success")
    return redirect(url_for("views.dashboard"))


# ======================================================
# Logout
# ======================================================
@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("views.index"))
