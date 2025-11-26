# app/extension_api.py

from flask import Blueprint, request, jsonify, url_for, current_app, session
from flask_login import login_required, current_user

from . import db
from .models import Flashcard
from .ai import generate_flashcards_from_text

# We do NOT set url_prefix here, it's added in app/__init__.py
extension_api = Blueprint("extension_api", __name__)

# Only paid plans can use the Chrome extension
PAID_PLANS = {"premium", "professional"}


@extension_api.post("/generate")
@login_required
def extension_generate():
    """
    Endpoint used by the Chrome extension.

    Flow:
    - Require login (Flask-Login)
    - Require paid plan (premium/professional)
    - Accept JSON: { "text": str, "num_cards": int }
    - Generate flashcards via OpenAI
    - Save them to the Flashcard table
    - Store them in session["cards"] so /dashboard can display/export
    - Return a redirect URL for the extension to open
    """

    # ---------------------------
    # SUBSCRIPTION CHECK
    # ---------------------------
    plan = (current_user.plan or "free").lower()
    if plan not in PAID_PLANS and not getattr(current_user, "is_admin", False):
        # Send them to billing portal if they aren't allowed
        billing_url = url_for("billing.billing_portal", _external=True)
        return jsonify({
            "ok": False,
            "error": "Subscription required",
            "reason": "billing_required",
            "redirect_url": billing_url,
        }), 402

    # ---------------------------
    # READ REQUEST BODY
    # ---------------------------
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    try:
        num_cards = int(data.get("num_cards") or 10)
    except (TypeError, ValueError):
        num_cards = 10

    if not text:
        return jsonify({
            "ok": False,
            "error": "No text provided",
            "reason": "no_text",
        }), 400

    # Clamp num_cards to something reasonable
    if num_cards < 1:
        num_cards = 1
    if num_cards > 200:
        num_cards = 200

    # ---------------------------
    # GENERATE FLASHCARDS
    # ---------------------------
    try:
        cards = generate_flashcards_from_text(
            source_text=text,
            num_cards=num_cards,
        )
    except Exception as e:
        current_app.logger.exception("Extension AI generation failed")
        return jsonify({
            "ok": False,
            "error": str(e),
            "reason": "ai_error",
        }), 500

    if not cards:
        return jsonify({
            "ok": False,
            "error": "No cards generated",
            "reason": "no_cards",
        }), 200

    used = len(cards)

    # ---------------------------
    # SAVE FLASHCARDS TO DB
    # ---------------------------
    try:
        for c in cards:
            front = str(c.get("front", "")).strip()
            back = str(c.get("back", "")).strip()
            if not front or not back:
                continue

            fc = Flashcard(
                user_id=current_user.id,
                front=front,
                back=back,
                source_type="extension",  # distinct from "dashboard"
            )
            db.session.add(fc)

        # Update usage counters (analytics)
        if current_user.daily_cards_generated is None:
            current_user.daily_cards_generated = 0
        if current_user.cards_generated_this_month is None:
            current_user.cards_generated_this_month = 0

        current_user.daily_cards_generated += used
        current_user.cards_generated_this_month += used

        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error saving extension flashcards to DB")

    # ---------------------------
    # STORE IN SESSION FOR EXPORT UI
    # ---------------------------
    try:
        # So /dashboard can immediately show/export them
        session["cards"] = cards
    except Exception:
        # Session failure shouldn't kill the API
        current_app.logger.exception("Error storing cards in session")

    # ---------------------------
    # BUILD REDIRECT URL
    # ---------------------------
    dashboard_url = url_for("views.dashboard", _external=True)

    return jsonify({
        "ok": True,
        "reason": "success",
        "redirect_url": dashboard_url,
        "cards_created": used,
    }), 200
