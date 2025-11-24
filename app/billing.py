import stripe
from flask import (
    Blueprint,
    current_app,
    redirect,
    request,
    url_for,
    jsonify,
    abort,
)
from flask_login import login_required, current_user

from . import db
from .models import User


billing_bp = Blueprint("billing", __name__, url_prefix="/billing")


# -------------------------------------------------------------------
# Helper: Pick Stripe Price ID for subscription tier
# -------------------------------------------------------------------

def _get_price_id_for_tier(tier: str) -> str | None:
    tier = (tier or "").lower()
    cfg = current_app.config

    if tier == "basic":
        return cfg.get("STRIPE_BASIC_PRICE_ID")
    if tier == "premium":
        return cfg.get("STRIPE_PREMIUM_PRICE_ID")
    if tier == "professional":
        return cfg.get("STRIPE_PROFESSIONAL_PRICE_ID")

    return None


# -------------------------------------------------------------------
# Set Stripe API key for every app request
# -------------------------------------------------------------------

@billing_bp.before_app_request
def _init_stripe():
    stripe.api_key = current_app.config.get("STRIPE_SECRET_KEY")


# -------------------------------------------------------------------
# Create Stripe Checkout Session
# -------------------------------------------------------------------

@billing_bp.route("/create-checkout-session/<tier>")
@login_required
def create_checkout_session(tier):
    price_id = _get_price_id_for_tier(tier)
    if not price_id:
        abort(404)

    domain = request.host_url.rstrip("/")

    # Create Stripe customer if needed
    if not current_user.stripe_customer_id:
        customer = stripe.Customer.create(email=current_user.email)
        current_user.stripe_customer_id = customer.id
        db.session.commit()

    checkout_session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        customer=current_user.stripe_customer_id,
        success_url=f"{domain}{url_for('views.dashboard')}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{domain}{url_for('views.dashboard')}",
        metadata={
            "tier": tier.lower(),
            "user_email": current_user.email.lower(),
        },
    )

    return redirect(checkout_session.url, code=303)


# -------------------------------------------------------------------
# Stripe Billing Portal (change plan, update card, cancel, etc.)
# -------------------------------------------------------------------

@billing_bp.route("/customer-portal")
@login_required
def customer_portal():
    if not current_user.stripe_customer_id:
        customer = stripe.Customer.create(email=current_user.email)
        current_user.stripe_customer_id = customer.id
        db.session.commit()

    domain = request.host_url.rstrip("/")

    portal = stripe.billing_portal.Session.create(
        customer=current_user.stripe_customer_id,
        return_url=f"{domain}{url_for('views.dashboard')}",
    )

    return redirect(portal.url, code=303)


# -------------------------------------------------------------------
# Stripe Webhook — must be publicly accessible
# -------------------------------------------------------------------

@billing_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig = request.headers.get("Stripe-Signature")
    secret = current_app.config.get("STRIPE_WEBHOOK_SECRET")

    if not secret:
        return "Webhook secret missing", 500

    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except ValueError:
        return "Invalid payload", 400
    except stripe.error.SignatureVerificationError:
        return "Invalid signature", 400

    event_type = event["type"]

    # --------------------------------------------------------------
    # checkout.session.completed → Assign subscription to user
    # --------------------------------------------------------------
    if event_type == "checkout.session.completed":
        session_obj = event["data"]["object"]

        customer_id = session_obj.get("customer")
        subscription_id = session_obj.get("subscription")
        meta = session_obj.get("metadata") or {}

        tier = (meta.get("tier") or "free").lower()
        email = (meta.get("user_email") or "").lower()

        # Find user by Stripe customer ID OR email
        user = None

        if customer_id:
            user = User.query.filter_by(stripe_customer_id=customer_id).first()

        if not user and email:
            user = User.query.filter_by(email=email).first()

        if user:
            user.tier = tier
            user.stripe_subscription_id = subscription_id
            db.session.commit()

    # --------------------------------------------------------------
    # subscription updated/deleted → downgrade to free
    # --------------------------------------------------------------
    elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        sub = event["data"]["object"]
        customer_id = sub.get("customer")
        status = sub.get("status")

        user = User.query.filter_by(stripe_customer_id=customer_id).first()

        if user and status not in ("active", "trialing"):
            user.tier = "free"
            user.stripe_subscription_id = None
            db.session.commit()

    return jsonify({"status": "ok"})
