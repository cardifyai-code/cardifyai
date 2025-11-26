from flask import Blueprint, request, jsonify, url_for, current_app
from flask_login import login_required, current_user

from . import db
from .models import Deck, Flashcard
from .ai import generate_flashcards

# Create blueprint for the Chrome Extension API
extension_api = Blueprint("extension_api", __name__, url_prefix="/api/extension")

# Which plans are allowed to use the extension
PAID_PLANS = {"premium", "professional"}


@extension_api.post("/generate")
@login_required
def extension_generate():
    """
    This API endpoint is used exclusively by the Chrome extension.

    Responsibilities:
    - Validates login (Flask-Login)
    - Validates active subscription (premium or professional)
    - Accepts text + number of flashcards
    - Calls OpenAI generator (generate_flashcards)
    - Creates a new deck & flashcards in the database
    - Returns a redirect URL for the extension to open
    """

    # ---------------------------
    # SUBSCRIPTION VALIDATION
    # ---------------------------
    if current_user.plan not in PAID_PLANS:
        # This URL will redirect user to Stripe Billing Portal
        billing_url = url_for("billing.billing_portal", _external=True)

        return jsonify({
            "error": "Subscription required",
            "redirect_url": billing_url
        }), 402

    # ---------------------------
    # REQUEST PAYLOAD
    # ---------------------------
    data = request.get_json(silent=True) or {}

    text = (data.get("text") or "").strip()
    num_cards = int(data.get("num_cards") or 10)

    if not text:
        return jsonify({"error": "No text provided"}), 400

    # Clamp between 1 and 200
    num_cards = max(1, min(num_cards, 200))

    # ---------------------------
    # GENERATE FLASHCARDS
    # ---------------------------
    try:
        cards = generate_flashcards(
            text=text,
            num_cards=num_cards
        )
    except Exception as e:
        current_app.logger.exception("Chrome Extension AI generation failed")
        return jsonify({"error": str(e)}), 500

    # ---------------------------
    # CREATE DECK
    # ---------------------------
    deck = Deck(
        user_id=current_user.id,
        title="Generated via Chrome Extension"
    )
    db.session.add(deck)
    db.session.commit()

    # ---------------------------
    # SAVE FLASHCARDS
    # ---------------------------
    for c in cards:
        fc = Flashcard(
            deck_id=deck.id,
            front=c["front"],
            back=c["back"]
        )
        db.session.add(fc)

    db.session.commit()

    # ---------------------------
    # BUILD REDIRECT URL
    # ---------------------------
    deck_url = url_for("views.view_deck", deck_id=deck.id, _external=True)

    # ---------------------------
    # SEND RESPONSE TO EXTENSION
    # ---------------------------
    return jsonify({
        "ok": True,
        "redirect_url": deck_url,
        "deck_url": deck_url,
        "cards_created": len(cards)
    }), 200