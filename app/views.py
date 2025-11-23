import datetime
from io import BytesIO

from flask import (
    Blueprint,
    render_template,
    request,
    flash,
    redirect,
    url_for,
    session,
    send_file,
)
from flask_login import login_required, current_user

from . import db
from .ai import generate_flashcards_from_text
from .pdf_utils import extract_text_from_pdf
from .deck_export import (
    create_apkg_from_flashcards,
    create_csv_from_flashcards,
    create_json_from_flashcards,
)

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def home():
    return render_template("index.html")


@views_bp.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    # ---------------------------
    # DAILY RESET
    # ---------------------------
    today = datetime.date.today()
    if (
        current_user.daily_reset_date is None
        or current_user.daily_reset_date != today
    ):
        current_user.daily_reset_date = today
        current_user.daily_cards_generated = 0
        db.session.commit()

    # ---------------------------
    # DETERMINE DAILY LIMIT
    # ---------------------------
    if current_user.is_admin:
        max_cards_per_day = 10_000_000  # effectively unlimited
    else:
        tier = current_user.tier or "free"
        if tier == "free":
            max_cards_per_day = 10
        elif tier == "basic":
            max_cards_per_day = 1000
        elif tier == "premium":
            max_cards_per_day = 5000
        elif tier == "professional":
            max_cards_per_day = 50000   # <-- Updated limit
        else:
            max_cards_per_day = 10  # fallback

    cards = None

    # ---------------------------
    # PROCESS FORM SUBMISSION
    # ---------------------------
    if request.method == "POST":
        text_content = request.form.get("text_content", "").strip()

        pdf_file = request.files.get("pdf_file")
        pdf_text = ""
        if pdf_file and pdf_file.filename.lower().endswith(".pdf"):
            pdf_text = extract_text_from_pdf(pdf_file.stream)

        source_text = (text_content + "\n" + (pdf_text or "")).strip()

        if not source_text:
            flash("Please enter text or upload a PDF.", "danger")
            return redirect(url_for("views.dashboard"))

        try:
            num_requested = int(request.form.get("num_cards", 10))
        except ValueError:
            num_requested = 10

        used_today = current_user.daily_cards_generated or 0
        remaining = max_cards_per_day - used_today

        if remaining <= 0:
            flash("You've reached your daily flashcard limit.", "danger")
            return redirect(url_for("views.dashboard"))

        if num_requested > remaining:
            flash(
                f"You have {remaining} flashcards remaining today; "
                f"generating {remaining} instead.",
                "warning",
            )
            num_requested = remaining

        # ---------------------------
        # GENERATE FLASHCARDS
        # ---------------------------
        try:
            cards = generate_flashcards_from_text(
                source_text,
                num_cards=num_requested,
                style="high-yield",
            )
        except Exception as e:
            flash(f"Error generating flashcards: {e}", "danger")
            return redirect(url_for("views.dashboard"))

        current_user.daily_cards_generated = used_today + len(cards)
        db.session.commit()

        session["cards"] = cards

        flash(
            f"Generated {len(cards)} flashcards. "
            f"Used {current_user.daily_cards_generated}/{max_cards_per_day} today.",
            "success",
        )

    if cards is None:
        cards = session.get("cards")

    return render_template("dashboard.html", cards=cards)


@views_bp.route("/download/<fmt>")
@login_required
def download(fmt: str):
    cards = session.get("cards")
    if not cards:
        flash("No flashcards to download. Generate some first.", "warning")
        return redirect(url_for("views.dashboard"))

    fmt = fmt.lower().strip()

    if fmt == "apkg":
        data = create_apkg_from_flashcards(cards, deck_name="CardifyAI Deck")
        filename = "cardifyai_deck.apkg"
        mime = "application/octet-stream"
    elif fmt == "csv":
        data = create_csv_from_flashcards(cards)
        filename = "cardifyai_deck.csv"
        mime = "text/ccsv"
    elif fmt == "json":
        data = create_json_from_flashcards(cards)
        filename = "cardifyai_deck.json"
        mime = "application/json"
    else:
        flash("Unknown download format.", "danger")
        return redirect(url_for("views.dashboard"))

    return send_file(
        BytesIO(data),
        as_attachment=True,
        download_name=filename,
        mimetype=mime,
    )
