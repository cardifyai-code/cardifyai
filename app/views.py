from datetime import date
import json
from io import BytesIO

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_file,
    current_app,
)
from flask_login import login_required, current_user

from . import db
from .models import User
from .ai import generate_flashcards_from_text
from .pdf_utils import extract_text_from_pdf
from .deck_export import create_apkg_from_cards, create_csv_from_cards
from .config import Config

views_bp = Blueprint("views", __name__)


# =============================
# Card limits by tier
# =============================

TIER_LIMITS = {
    "free": 10,          # 10 cards/day logged-in free
    "basic": 5_000,      # $3.99
    "premium": 10_000,   # $7.99
    "professional": 50_000,  # $19.99
}

ADMIN_LIMIT = 3_000_000  # effectively unlimited for you


def get_daily_limit(user: User) -> int:
    if getattr(user, "is_admin", False):
        return ADMIN_LIMIT
    tier = (user.tier or "free").lower()
    return TIER_LIMITS.get(tier, TIER_LIMITS["free"])


def ensure_daily_reset(user: User) -> None:
    today = date.today()
    if not user.daily_reset_date or user.daily_reset_date < today:
        user.daily_reset_date = today
        user.daily_cards_generated = 0
        db.session.commit()


# =============================
# Routes
# =============================


@views_bp.route("/", methods=["GET"])
def index():
    """
    Landing page:
    - If logged in -> go to dashboard
    - If not logged in -> marketing + CTA + "Continue with Google"
    """
    if current_user.is_authenticated:
        return redirect(url_for("views.dashboard"))

    # Anonymous visitors can see the landing and try free tier *after login*
    return render_template("index.html")


@views_bp.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    """
    Core app screen:
    - Shows text box + PDF upload
    - Calls OpenAI to generate flashcards
    - Enforces per-day limits by tier
    - Stores cards in session for export/download
    """
    ensure_daily_reset(current_user)

    cards = session.get("cards", [])

    if request.method == "POST":
        raw_text = request.form.get("source_text", "").strip()

        # PDF upload (optional)
        pdf_file = request.files.get("pdf_file")
        pdf_text = ""
        if pdf_file and pdf_file.filename:
            try:
                pdf_bytes = pdf_file.read()
                pdf_text = extract_text_from_pdf(BytesIO(pdf_bytes))
            except Exception as e:
                current_app.logger.exception("Error reading PDF")
                flash(f"Error reading PDF: {e}", "danger")
                return render_template("dashboard.html", cards=cards)

        # Combine text inputs
        combined_text = "\n\n".join(
            [part for part in [raw_text, pdf_text] if part]
        ).strip()

        if not combined_text:
            flash("Please enter text or upload a PDF.", "warning")
            return render_template("dashboard.html", cards=cards)

        # Enforce card limits
        daily_limit = get_daily_limit(current_user)
        remaining = max(0, daily_limit - current_user.daily_cards_generated)
        if remaining <= 0:
            flash(
                "You’ve hit your daily card limit for your plan. "
                "Upgrade your plan to generate more cards.",
                "warning",
            )
            return render_template("dashboard.html", cards=cards)

        # You could also let user ask for a specific number; for now we
        # generate up to 'remaining' cards.
        max_cards = remaining

        try:
            new_cards = generate_flashcards_from_text(
                combined_text,
                max_cards=max_cards,
            )
            if not new_cards:
                flash(
                    "The AI didn’t return any flashcards. Try using more detailed text.",
                    "warning",
                )
                return render_template("dashboard.html", cards=cards)

            # Update usage and session
            used = len(new_cards)
            current_user.daily_cards_generated += used
            db.session.commit()

            cards = new_cards
            session["cards"] = cards

            flash(f"Generated {used} flashcards.", "success")

        except Exception as e:
            current_app.logger.exception("Error generating flashcards")
            flash(f"Error generating flashcards: {e}", "danger")

    # Stats for UI
    ensure_daily_reset(current_user)
    daily_limit = get_daily_limit(current_user)
    used = current_user.daily_cards_generated
    remaining = max(0, daily_limit - used)

    return render_template(
        "dashboard.html",
        cards=cards,
        tier=current_user.tier,
        daily_limit=daily_limit,
        used=used,
        remaining=remaining,
        is_admin=current_user.is_admin,
        stripe_public_key=Config.STRIPE_PUBLIC_KEY,
    )


@views_bp.route("/download/<fmt>")
@login_required
def download(fmt: str):
    """
    Download generated cards as:
    - Anki .apkg
    - CSV
    """
    cards = session.get("cards", [])
    if not cards:
        flash("No cards to download. Generate some first.", "warning")
        return redirect(url_for("views.dashboard"))

    if fmt == "apkg":
        apkg_bytes = create_apkg_from_cards(cards)
        return send_file(
            apkg_bytes,
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name="cardifyai_deck.apkg",
        )

    elif fmt == "csv":
        csv_bytes = create_csv_from_cards(cards)
        return send_file(
            csv_bytes,
            mimetype="text/csv",
            as_attachment=True,
            download_name="cardifyai_deck.csv",
        )

    flash("Unknown download format.", "danger")
    return redirect(url_for("views.dashboard"))
