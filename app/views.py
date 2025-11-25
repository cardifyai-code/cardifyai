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
from .pdf_utils import extract_text_from_pdf
from .deck_export import (
    create_apkg_from_cards,
    create_csv_from_cards,
    create_json_from_cards,
)
from .config import Config
from .tasks import enqueue_flashcard_job, get_job  # Celery background tasks
from .ai import generate_flashcards_from_text      # fallback direct generation

views_bp = Blueprint("views", __name__)

# =============================
# Card limits by plan
# =============================

PLAN_LIMITS = {
    "free": 10,           # 10 cards/day
    "basic": 200,         # 200 cards/day
    "premium": 1_000,     # 1,000 cards/day
    "professional": 5_000  # 5,000 cards/day
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
    - Tries to enqueue AI generator job in the background (Celery)
    - If Celery/Redis is unavailable, falls back to direct generation
    - Enforces daily limits
    - Polls job status stored in Redis and loads cards when complete
    """
    ensure_daily_reset(current_user)

    cards = session.get("cards", [])
    job_pending = False

    # ---------------------------------
    # Check status of any existing job
    # ---------------------------------
    job_id = session.get("job_id")
    if job_id:
        try:
            job_data = get_job(job_id)  # returns dict or None
            if not job_data:
                # Job disappeared or expired
                current_app.logger.warning("Job %s not found in Redis", job_id)
                flash(
                    "We couldn't find your flashcard job. Please try again.",
                    "danger",
                )
                session.pop("job_id", None)
            else:
                status = job_data.get("status")
                if status == "error":
                    err_msg = job_data.get("error", "Unknown error")
                    current_app.logger.error(
                        "Flashcard job %s errored: %s", job_id, err_msg
                    )
                    flash(
                        "There was an error generating your flashcards. "
                        "Please try again.",
                        "danger",
                    )
                    session.pop("job_id", None)

                elif status in ("queued", "running"):
                    # Still in progress
                    job_pending = True

                elif status == "complete":
                    result = job_data.get("result") or []
                    if isinstance(result, list):
                        cards = result
                        session["cards"] = cards

                        # Count usage *once* when job completes
                        used = len(cards)
                        if used > 0:
                            current_user.daily_cards_generated += used
                            # Monthly tracking (optional but already in your model)
                            if current_user.cards_generated_this_month is None:
                                current_user.cards_generated_this_month = 0
                            current_user.cards_generated_this_month += used
                            db.session.commit()

                        flash(f"Generated {used} flashcards.", "success")
                    else:
                        flash(
                            "Generation completed but returned an unexpected result.",
                            "danger",
                        )

                    # Job consumed, stop checking on subsequent requests
                    session.pop("job_id", None)
                else:
                    # Unknown status, be safe
                    current_app.logger.warning(
                        "Job %s returned unknown status: %s", job_id, status
                    )
                    flash(
                        "Unexpected job status while generating flashcards.",
                        "danger",
                    )
                    session.pop("job_id", None)
        except Exception:
            current_app.logger.exception("Error checking background job")
            flash("Error checking flashcard generation job.", "danger")
            session.pop("job_id", None)

    # ---------------------------------
    # Handle new POST: enqueue new job
    # ---------------------------------
    if request.method == "POST":
        # Don't allow stacking background jobs in this simple version
        if session.get("job_id"):
            flash(
                "A flashcard generation job is already in progress. "
                "Please wait for it to finish or refresh the page.",
                "warning",
            )
            return redirect(url_for("views.dashboard"))

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
                # Re-render with current stats
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
                    job_pending=job_pending,
                )

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
                job_pending=job_pending,
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
                job_pending=job_pending,
            )

        num_cards = min(requested_num, remaining)

        # ------------ Enqueue background job ---------------
        try:
            job_id = enqueue_flashcard_job(
                user_id=current_user.id,
                text=combined_text,
                num_cards=num_cards,
            )
            session["job_id"] = job_id
            # Clear any old cards from session; new ones will replace them
            session.pop("cards", None)

            flash(
                "Your flashcards are being generated in the background. "
                "This usually takes a short moment. Refresh the page to see when they’re ready.",
                "info",
            )
            return redirect(url_for("views.dashboard"))

        except Exception as e:
            # If Celery/Redis fails, fall back to direct generation in-process
            current_app.logger.exception(
                "Error enqueuing background job; falling back to direct generation"
            )

            try:
                cards = generate_flashcards_from_text(combined_text, num_cards)

                if not cards:
                    flash(
                        "No flashcards were produced. Try using more detailed input.",
                        "warning",
                    )
                else:
                    used = len(cards)
                    current_user.daily_cards_generated += used
                    if current_user.cards_generated_this_month is None:
                        current_user.cards_generated_this_month = 0
                    current_user.cards_generated_this_month += used
                    db.session.commit()

                    session["cards"] = cards
                    flash(
                        f"Generated {used} flashcards (direct mode, worker unavailable).",
                        "success",
                    )

                return redirect(url_for("views.dashboard"))

            except Exception as inner:
                current_app.logger.exception(
                    "Error generating flashcards directly after Celery failure"
                )
                flash(f"Error generating flashcards: {inner}", "danger")

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
        job_pending=job_pending,
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
