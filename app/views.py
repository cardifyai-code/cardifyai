# app/views.py

from datetime import date, datetime, timedelta
from io import BytesIO
from collections import Counter, defaultdict
import json

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
from .models import User, Subscription, Flashcard, Visit, Review
from .ai import generate_flashcards_from_text  # direct AI call
from .pdf_utils import extract_text_from_pdf
from .deck_export import (
    create_apkg_from_cards,
    create_csv_from_cards,
    create_json_from_cards,
)
from .config import Config

views_bp = Blueprint("views", __name__)

# ============================================================
# Card limits by plan (DAILY ONLY)
# ============================================================

PLAN_LIMITS = {
    "free": 10,            # 10 cards/day
    "basic": 200,          # 200 cards/day
    "premium": 1_000,      # 1,000 cards/day
    "professional": 5_000, # 5,000 cards/day
}

ADMIN_LIMIT = 3_000_000  # effectively unlimited for your admin account

# ============================================================
# OpenAI cost assumptions
# (GPT-4o-mini-style pricing; adjust if you change models)
# ============================================================

# Dollars per token (0.15$ per 1M input, 0.60$ per 1M output)
INPUT_TOKEN_RATE = 0.15 / 1_000_000
OUTPUT_TOKEN_RATE = 0.60 / 1_000_000

# ============================================================
# Subscription prices (YOUR PLANS)
# ============================================================

PLAN_PRICES = {
    "free": 0.00,
    "basic": 3.99,
    "premium": 7.99,
    "professional": 19.99,
}

# Plans that are allowed to access browser extension downloads
EXTENSION_PLANS = {"premium", "professional"}


# ============================================================
# Helper functions
# ============================================================

def get_daily_limit(user: User) -> int:
    """Return the per-day flashcard limit based on the user's plan."""
    if getattr(user, "is_admin", False):
        return ADMIN_LIMIT
    plan = (user.plan or "free").lower()
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


def ensure_daily_reset(user: User) -> None:
    """
    Reset daily usage counters if a new day has started.

    This handles:
    - daily_cards_generated
    - daily_input_tokens
    - daily_output_tokens
    """
    today = date.today()
    if not user.daily_reset_date or user.daily_reset_date < today:
        user.daily_reset_date = today
        user.daily_cards_generated = 0
        user.daily_input_tokens = 0
        user.daily_output_tokens = 0
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def log_visit(path: str) -> None:
    """
    Record a page visit in the Visit table.
    Safe to call even if something goes wrong.
    """
    try:
        v = Visit(
            path=path,
            user_id=current_user.id
            if getattr(current_user, "is_authenticated", False)
            else None,
            ip_address=request.remote_addr or "",
            user_agent=request.headers.get("User-Agent", "")[:512],
        )
        db.session.add(v)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error logging visit for path %s", path)


def user_has_extension_access(user: User) -> bool:
    """
    Helper: return True if the user is allowed to access browser extensions.
    """
    if getattr(user, "is_admin", False):
        return True
    plan = (user.plan or "free").lower()
    return plan in EXTENSION_PLANS


# ============================================================
# Public routes
# ============================================================

@views_bp.route("/", methods=["GET"])
def index():
    """
    Landing page.

    If authenticated, send straight to dashboard.
    Otherwise, show marketing + selected reviews.
    """
    log_visit("/")

    if current_user.is_authenticated:
        return redirect(url_for("views.dashboard"))

    # Show a handful of recent, approved reviews on the homepage
    homepage_reviews = (
        Review.query.filter_by(is_approved=True)
        .order_by(Review.created_at.desc())
        .limit(6)
        .all()
    )

    return render_template("index.html", homepage_reviews=homepage_reviews)


@views_bp.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    """
    Main generator UI:
    - Text + PDF input
    - Calls AI generator directly (no Celery/Redis)
    - Enforces daily limits (NO MONTHLY LIMIT)
    - Stores cards in session for export/download
    - Can also be entered after extension_api generates cards
      (prefills from session["ext_text"] / session["ext_num_cards"])
    """
    log_visit("/dashboard")
    ensure_daily_reset(current_user)

    cards = session.get("cards", [])

    # Flags for extension-originated generation (optional)
    from_extension = session.pop("from_extension", False)
    cards_created = session.pop("cards_created", None)

    # Original text / card count from the extension (if present)
    ext_text = session.pop("ext_text", None)
    ext_num_cards = session.pop("ext_num_cards", None)

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
                used = current_user.daily_cards_generated or 0
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
                    from_extension=from_extension,
                    cards_created=cards_created,
                    ext_text=ext_text,
                    ext_num_cards=ext_num_cards,
                    has_extension_access=user_has_extension_access(current_user),
                )

        # Combine text + PDF
        combined_text = "\n\n".join(x for x in [raw_text, pdf_text] if x).strip()

        if not combined_text:
            flash("Please enter text or upload a PDF.", "warning")

            daily_limit = get_daily_limit(current_user)
            used = current_user.daily_cards_generated or 0
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
                from_extension=from_extension,
                cards_created=cards_created,
                ext_text=ext_text,
                ext_num_cards=ext_num_cards,
                has_extension_access=user_has_extension_access(current_user),
            )

        # ------------ Requested cards ---------------
        try:
            requested_num = int(request.form.get("num_cards", 10))
        except ValueError:
            requested_num = 10

        requested_num = max(1, min(requested_num, 2000))

        # ------------ Enforce DAILY limits only ---------------
        daily_limit = get_daily_limit(current_user)
        remaining = max(
            0, daily_limit - (current_user.daily_cards_generated or 0)
        )

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
                used=current_user.daily_cards_generated or 0,
                remaining=0,
                is_admin=current_user.is_admin,
                from_extension=from_extension,
                cards_created=cards_created,
                ext_text=ext_text,
                ext_num_cards=ext_num_cards,
                has_extension_access=user_has_extension_access(current_user),
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
                used = current_user.daily_cards_generated or 0
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
                    from_extension=from_extension,
                    cards_created=cards_created,
                    ext_text=ext_text,
                    ext_num_cards=ext_num_cards,
                    has_extension_access=user_has_extension_access(current_user),
                )

            used = len(new_cards)

            # Track usage (cards)
            # DAILY limit enforcement only; monthly is just analytics count
            current_user.daily_cards_generated = (
                current_user.daily_cards_generated or 0
            ) + used

            # Monthly usage counter (for analytics ONLY, not a limit)
            if current_user.cards_generated_this_month is None:
                current_user.cards_generated_this_month = 0
            current_user.cards_generated_this_month += used

            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

            # Persist cards for analytics (Flashcard table)
            try:
                for c in new_cards:
                    # c should be a dict, but be defensive
                    if isinstance(c, dict):
                        front = str(c.get("front", "")).strip()
                        back = str(c.get("back", "")).strip()
                    elif isinstance(c, (list, tuple)) and len(c) >= 2:
                        front = str(c[0]).strip()
                        back = str(c[1]).strip()
                    else:
                        continue

                    if not front or not back:
                        continue

                    fc = Flashcard(
                        user_id=current_user.id,
                        front=front,
                        back=back,
                        source_type="dashboard",
                    )
                    db.session.add(fc)
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Error saving flashcards to DB")

            session["cards"] = new_cards
            cards = new_cards

            flash(f"Generated {used} flashcards.", "success")

        except Exception as e:
            current_app.logger.exception("Error during card generation")
            flash(f"Error generating flashcards: {e}", "danger")

    # ----------------- Stats for GET / fallback --------------------
    ensure_daily_reset(current_user)
    daily_limit = get_daily_limit(current_user)
    used = current_user.daily_cards_generated or 0
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
        from_extension=from_extension,
        cards_created=cards_created,
        ext_text=ext_text,
        ext_num_cards=ext_num_cards,
        has_extension_access=user_has_extension_access(current_user),
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


# ============================================================
# Browser extension download routes (gated)
# ============================================================

@views_bp.route("/extensions/chrome", methods=["GET"])
@login_required
def extension_chrome():
    """
    Chrome extension link.
    Only Premium / Professional (or admin) can access.
    Others are redirected to Premium checkout.
    """
    log_visit("/extensions/chrome")

    if not user_has_extension_access(current_user):
        flash(
            "Browser extensions are available for Premium and Professional users.",
            "warning",
        )
        return redirect(url_for("billing.checkout", plan="premium"))

    # Placeholder URL – replace with your actual Chrome Web Store URL
    chrome_url = "https://example.com/chrome-extension-placeholder"
    return redirect(chrome_url)


@views_bp.route("/extensions/edge", methods=["GET"])
@login_required
def extension_edge():
    """
    Edge extension link.
    Only Premium / Professional (or admin) can access.
    """
    log_visit("/extensions/edge")

    if not user_has_extension_access(current_user):
        flash(
            "Browser extensions are available for Premium and Professional users.",
            "warning",
        )
        return redirect(url_for("billing.checkout", plan="premium"))

    # Placeholder URL – replace with your actual Edge Add-ons URL
    edge_url = "https://example.com/edge-extension-placeholder"
    return redirect(edge_url)


@views_bp.route("/extensions/firefox", methods=["GET"])
@login_required
def extension_firefox():
    """
    Firefox extension link.
    Only Premium / Professional (or admin) can access.
    """
    log_visit("/extensions/firefox")

    if not user_has_extension_access(current_user):
        flash(
            "Browser extensions are available for Premium and Professional users.",
            "warning",
        )
        return redirect(url_for("billing.checkout", plan="premium"))

    # Placeholder URL – replace with your actual Firefox Add-ons URL
    firefox_url = "https://example.com/firefox-extension-placeholder"
    return redirect(firefox_url)


# ============================================================
# About / Privacy / Terms
# ============================================================

@views_bp.route("/about", methods=["GET"])
def about():
    """
    About / tutorial page.
    Your template can show:
    - GIFs walking users through how to use CardifyAI
    - Social media links
    """
    log_visit("/about")
    return render_template("about.html")


@views_bp.route("/privacy", methods=["GET"])
def privacy():
    """
    Privacy policy page.
    """
    log_visit("/privacy")
    return render_template("privacy.html")


@views_bp.route("/terms", methods=["GET"])
def terms():
    """
    Terms of use page.
    """
    log_visit("/terms")
    return render_template("terms.html")


# ============================================================
# Reviews
# ============================================================

@views_bp.route("/reviews", methods=["GET", "POST"])
def reviews():
    """
    Reviews page:
    - GET: show list of approved reviews
    - POST: allow logged-in users to submit a review
    """
    log_visit("/reviews")

    if request.method == "POST":
        # Require login to submit
        if not current_user.is_authenticated:
            flash("Please log in to leave a review.", "warning")
            return redirect(url_for("auth.login", next=url_for("views.reviews")))

        rating_raw = request.form.get("rating", "").strip()
        title = (request.form.get("title") or "").strip()
        body = (request.form.get("body") or "").strip()

        # Basic validation
        try:
            rating = int(rating_raw or 5)
        except ValueError:
            rating = 5
        if rating < 1:
            rating = 1
        if rating > 5:
            rating = 5

        if not title or not body:
            flash("Please provide both a title and review body.", "warning")
        else:
            try:
                r = Review(
                    user_id=current_user.id,
                    rating=rating,
                    title=title,
                    body=body,
                    is_approved=True,  # you can change this to False if you want manual moderation
                )
                db.session.add(r)
                db.session.commit()
                flash("Thank you for your review!", "success")
                return redirect(url_for("views.reviews"))
            except Exception as e:
                db.session.rollback()
                current_app.logger.exception("Error saving review")
                flash(f"Error saving your review: {e}", "danger")

    # GET (and also fall-through if POST invalid)
    approved_reviews = (
        Review.query.filter_by(is_approved=True)
        .order_by(Review.created_at.desc())
        .all()
    )

    return render_template(
        "reviews.html",
        reviews=approved_reviews,
    )


# ============================================================
# Admin dashboard (cost + revenue + users, NO monthly limit)
# ============================================================

@views_bp.route("/admin", methods=["GET"])
@login_required
def admin_dashboard():
    """
    Admin-only panel showing:
    - All users, their plans, and DAILY usage details
    - Cards generated this month (analytics only)
    - Aggregated token usage + estimated cost
    - Estimated monthly revenue by plan
    """
    log_visit("/admin")

    if not current_user.is_admin:
        flash("Admin access only.", "danger")
        return redirect(url_for("views.dashboard"))

    users = User.query.order_by(User.created_at.desc()).all()
    plan_counts = Counter((u.plan or "free").lower() for u in users)

    # Token usage aggregates
    total_daily_input = 0
    total_daily_output = 0
    total_monthly_input = 0
    total_monthly_output = 0

    # Revenue / cost aggregates
    total_estimated_revenue = 0.0
    total_estimated_cost = 0.0
    total_monthly_cards = 0  # analytics only

    user_rows = []

    for u in users:
        plan = (u.plan or "free").lower()
        daily_limit = get_daily_limit(u)
        daily_used = u.daily_cards_generated or 0
        daily_remaining = max(0, daily_limit - daily_used)

        # Monthly cards = how many cards they generated this month
        monthly_cards = u.cards_generated_this_month or 0
        total_monthly_cards += monthly_cards

        d_in = u.daily_input_tokens or 0
        d_out = u.daily_output_tokens or 0
        m_in = u.monthly_input_tokens or 0
        m_out = u.monthly_output_tokens or 0

        total_daily_input += d_in
        total_daily_output += d_out
        total_monthly_input += m_in
        total_monthly_output += m_out

        # Estimated *cost* per user based on monthly tokens
        estimated_cost = (m_in * INPUT_TOKEN_RATE) + (m_out * OUTPUT_TOKEN_RATE)

        # Estimated *revenue* per user based on plan
        plan_price = PLAN_PRICES.get(plan, 0.0)

        # Do NOT count admins as revenue, even if they're on a paid plan
        if u.is_admin:
            plan_price = 0.0

        estimated_revenue = plan_price
        total_estimated_cost += estimated_cost
        total_estimated_revenue += estimated_revenue

        user_rows.append(
            {
                "user": u,
                "plan": plan,
                "daily_limit": daily_limit,
                "daily_used": daily_used,
                "daily_remaining": daily_remaining,
                "monthly_cards": monthly_cards,  # analytics only
                "daily_input_tokens": d_in,
                "daily_output_tokens": d_out,
                "monthly_input_tokens": m_in,
                "monthly_output_tokens": m_out,
                "estimated_cost": estimated_cost,
                "estimated_revenue": estimated_revenue,
            }
        )

    # Net margin
    net_estimated_profit = total_estimated_revenue - total_estimated_cost

    return render_template(
        "admin.html",
        # user/plan stats
        user_rows=user_rows,
        plan_counts=plan_counts,
        plan_limits=PLAN_LIMITS,
        total_users=len(users),
        total_monthly_cards=total_monthly_cards,
        # token usage aggregate
        total_daily_input_tokens=total_daily_input,
        total_daily_output_tokens=total_daily_output,
        total_monthly_input_tokens=total_monthly_input,
        total_monthly_output_tokens=total_monthly_output,
        # cost & revenue
        total_estimated_cost=total_estimated_cost,
        total_estimated_revenue=total_estimated_revenue,
        net_estimated_profit=net_estimated_profit,
        input_token_rate=INPUT_TOKEN_RATE,
        output_token_rate=OUTPUT_TOKEN_RATE,
    )


# ============================================================
# Admin Analytics (charts, visits, subs, cards)
# ============================================================

@views_bp.route("/admin/analytics", methods=["GET"])
@login_required
def admin_analytics():
    """
    Analytics panel for admins:
    - Website visits per day (last 30 days)
    - New subscriptions per day (last 30 days)
    - Flashcards created per day (last 30 days)
    - Aggregate token usage + cost
    """
    log_visit("/admin/analytics")

    if not current_user.is_admin:
        flash("Admin access only.", "danger")
        return redirect(url_for("views.dashboard"))

    today = date.today()
    start_date = today - timedelta(days=29)
    start_dt = datetime.combine(start_date, datetime.min.time())

    # -------------------------
    # Visits per day
    # -------------------------
    visits = (
        Visit.query.filter(Visit.created_at >= start_dt)
        .order_by(Visit.created_at.asc())
        .all()
    )
    visits_by_day = defaultdict(int)
    for v in visits:
        d = v.created_at.date().isoformat()
        visits_by_day[d] += 1

    # -------------------------
    # New subscriptions per day
    # -------------------------
    subs = (
        Subscription.query.filter(Subscription.created_at >= start_dt)
        .order_by(Subscription.created_at.asc())
        .all()
    )
    subs_by_day = defaultdict(int)
    for s in subs:
        if s.created_at:
            d = s.created_at.date().isoformat()
            subs_by_day[d] += 1

    # -------------------------
    # Flashcards created per day
    # -------------------------
    flashcards = (
        Flashcard.query.filter(Flashcard.created_at >= start_dt)
        .order_by(Flashcard.created_at.asc())
        .all()
    )
    cards_by_day = defaultdict(int)
    for c in flashcards:
        if c.created_at:
            d = c.created_at.date().isoformat()
            cards_by_day[d] += 1

    # Normalize labels to a continuous 30-day window
    labels = [
        (start_date + timedelta(days=i)).isoformat()
        for i in range(30)
    ]

    visits_series = [visits_by_day.get(d, 0) for d in labels]
    subs_series = [subs_by_day.get(d, 0) for d in labels]
    cards_series = [cards_by_day.get(d, 0) for d in labels]

    # Aggregate token usage + cost (monthly)
    users = User.query.all()
    total_monthly_input = sum((u.monthly_input_tokens or 0) for u in users)
    total_monthly_output = sum((u.monthly_output_tokens or 0) for u in users)
    total_monthly_cost = (total_monthly_input * INPUT_TOKEN_RATE) + (
        total_monthly_output * OUTPUT_TOKEN_RATE
    )

    # JSON for Chart.js
    labels_json = json.dumps(labels)
    visits_json = json.dumps(visits_series)
    subs_json = json.dumps(subs_series)
    cards_json = json.dumps(cards_series)

    return render_template(
        "admin_analytics.html",
        labels_json=labels_json,
        visits_json=visits_json,
        subs_json=subs_json,
        cards_json=cards_json,
        total_monthly_input_tokens=total_monthly_input,
        total_monthly_output_tokens=total_monthly_output,
        total_monthly_cost=total_monthly_cost,
        input_token_rate=INPUT_TOKEN_RATE,
        output_token_rate=OUTPUT_TOKEN_RATE,
        start_date=start_date,
        end_date=today,
    )
