# app/views.py

from datetime import date
from io import BytesIO
from collections import Counter

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
from .ai import generate_flashcards_from_text  # <- direct AI call
from .pdf_utils import extract_text_from_pdf
from .deck_export import (
    create_apkg_from_cards,
    create_csv_from_cards,
    create_json_from_cards,
)
from .config import Config

views_bp = Blueprint("views", __name__)

# =============================
# Card limits by plan
# =============================

PLAN_LIMITS = {
    "free": 10,           # 10 cards/day
    "basic": 200,         # 200 cards/day
    "premium": 1_000,     # 1,000 cards/day
    "professional": 5_000 # 5,000 cards/day
}

ADMIN_LIMIT = 3_000_000  # effectively unlimited for your admin account


def get_daily_limit(user: User) -> int:
    """Return the per-day flashcard limit based on the user's plan."""
    if getattr(user, "is_admin", False):
        return ADMIN_LIMIT
    plan = (user.plan or "free").lower()
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


def ensure_daily_reset(user: User) -> None:
    """Reset daily usage counters if a new day has started."""
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
    """Landing page."""
    if current_user.is_authenticated:
        return redirect(url_for("views.dashboard"))
    return render_template("index.html")


@views_bp.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    """
    Main generator UI:
    - Text + PDF input
    - Calls AI generator directly (no Celery/Redis)
    - Enforces daily limits
    - Stores cards in session for export/download
    """
    ensure_daily_reset(current_user)

    cards = session.get("cards", [])

    if request.method == "POST":
        # ------------ Input text ---------------
        raw_text = request.form.get("text_content", "").strip()

        # ------------ PDF input ---------------
        pdf_file = request.files.get("pdf_file")
        pdf_text = ""
        if pdf_file and pdf_file.filename:
            try:
                pdf_bytes = pdf_file.read()
                pdf_text = extract_text_from_pdf(BytesIO(pdf_bytes))
            except Exception as e:
                current_app.logger.exception("Error reading PDF")
                flash(f"Error reading PDF: {e}", "danger")

                # Recompute stats for re-render
                daily_limit = get_daily_limit(current_user)
                used = current_user.daily_cards_generated
                remaining = max(0, daily_limit - used)

                return render_template(
                    "dashboard.html",
                    cards=cards,
                    plan=current_user.plan,
                    stripe_public_key=Config.STRIPE_PUBLIC_KEY,
                    daily_limit=daily_limit,
                    used=used,
                    remaining=remaining,
                    is_admin=current_user.is_admin,
                )

        # Combine text + PDF
        combined_text = "\n\n".join(x for x in [raw_text, pdf_text] if x).strip()

        if not combined_text:
            flash("Please enter text or upload a PDF.", "warning")

            daily_limit = get_daily_limit(current_user)
            used = current_user.daily_cards_generated
            remaining = max(0, daily_limit - used)

            return render_template(
                "dashboard.html",
                cards=cards,
                plan=current_user.plan,
                stripe_public_key=Config.STRIPE_PUBLIC_KEY,
                daily_limit=daily_limit,
                used=used,
                remaining=remaining,
                is_admin=current_user.is_admin,
            )

        # ------------ Requested cards ---------------
        try:
            requested_num = int(request.form.get("num_cards", 10))
        except ValueError:
            requested_num = 10

        requested_num = max(1, min(requested_num, 2000))

        # ------------ Enforce daily limits ---------------
        daily_limit = get_daily_limit(current_user)
        remaining = max(0, daily_limit - current_user.daily_cards_generated)

        if remaining <= 0:
            flash(
                "You’ve hit your daily card limit for your plan. "
                "Upgrade your plan to generate more cards.",
                "warning",
            )

            return render_template(
                "dashboard.html",
                cards=cards,
                plan=current_user.plan,
                stripe_public_key=Config.STRIPE_PUBLIC_KEY,
                daily_limit=daily_limit,
                used=current_user.daily_cards_generated,
                remaining=0,
                is_admin=current_user.is_admin,
            )

        num_cards = min(requested_num, remaining)

        # ------------ Direct AI call ---------------
        try:
            new_cards = generate_flashcards_from_text(
                combined_text,
                num_cards=num_cards,
            )

            if not new_cards:
                flash(
                    "No flashcards were produced. "
                    "Try using more detailed input.",
                    "warning",
                )
                daily_limit = get_daily_limit(current_user)
                used = current_user.daily_cards_generated
                remaining = max(0, daily_limit - used)

                return render_template(
                    "dashboard.html",
                    cards=cards,
                    plan=current_user.plan,
                    stripe_public_key=Config.STRIPE_PUBLIC_KEY,
                    daily_limit=daily_limit,
                    used=used,
                    remaining=remaining,
                    is_admin=current_user.is_admin,
                )

            used = len(new_cards)

            # Track usage
            current_user.daily_cards_generated += used
            # monthly tracking (optional, but fits your schema)
            if current_user.cards_generated_this_month is None:
                current_user.cards_generated_this_month = 0
            current_user.cards_generated_this_month += used

            db.session.commit()

            session["cards"] = new_cards
            cards = new_cards

            flash(f"Generated {used} flashcards.", "success")

        except Exception as e:
            current_app.logger.exception("Error during card generation")
            flash(f"Error generating flashcards: {e}", "danger")

    # ----------------- Stats for GET / fallback --------------------
    ensure_daily_reset(current_user)
    daily_limit = get_daily_limit(current_user)
    used = current_user.daily_cards_generated
    remaining = max(0, daily_limit - used)

    return render_template(
        "dashboard.html",
        cards=cards,
        plan=current_user.plan,
        daily_limit=daily_limit,
        used=used,
        remaining=remaining,
        is_admin=current_user.is_admin,
        stripe_public_key=Config.STRIPE_PUBLIC_KEY,
    )


@views_bp.route("/download/<fmt>")
@login_required
def download(fmt: str):
    """Download flashcards in APKG / CSV / JSON."""
    cards = session.get("cards", [])
    if not cards:
        flash("No cards to download.", "warning")
        return redirect(url_for("views.dashboard"))

    if fmt == "apkg":
        return send_file(
            create_apkg_from_cards(cards),
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name="cardifyai_deck.apkg",
        )

    if fmt == "csv":
        return send_file(
            create_csv_from_cards(cards),
            mimetype="text/csv",
            as_attachment=True,
            download_name="cardifyai_deck.csv",
        )

    if fmt == "json":
        return send_file(
            create_json_from_cards(cards),
            mimetype="application/json",
            as_attachment=True,
            download_name="cardifyai_deck.json",
        )

    flash("Unknown export format.", "danger")
    return redirect(url_for("views.dashboard"))


# =============================
# Admin dashboard
# =============================

@views_bp.route("/admin", methods=["GET"])
@login_required
def admin_dashboard():
    """Admin-only panel showing all users, plan stats, and usage details."""
    if not current_user.is_admin:
        flash("Admin access only.", "danger")
        return redirect(url_for("views.dashboard"))

    users = User.query.order_by(User.created_at.desc()).all()
    plan_counts = Counter((u.plan or "free").lower() for u in users)

    user_rows = []
    for u in users:
        plan = (u.plan or "free").lower()
        daily_limit = get_daily_limit(u)
        daily_used = u.daily_cards_generated or 0
        daily_remaining = max(0, daily_limit - daily_used)

        monthly_quota = u.monthly_card_quota or 0
        monthly_used = u.cards_generated_this_month or 0
        monthly_remaining = (
            max(0, monthly_quota - monthly_used) if monthly_quota > 0 else None
        )

        user_rows.append(
            {
                "user": u,
                "plan": plan,
                "daily_limit": daily_limit,
                "daily_used": daily_used,
                "daily_remaining": daily_remaining,
                "monthly_quota": monthly_quota,
                "monthly_used": monthly_used,
                "monthly_remaining": monthly_remaining,
            }
        )

    return render_template(
        "admin.html",
        user_rows=user_rows,
        plan_counts=plan_counts,
        plan_limits=PLAN_LIMITS,
        total_users=len(users),
    )
