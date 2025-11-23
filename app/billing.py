import json

import stripe
from flask import (
    Blueprint,
    request,
    current_app,
    redirect,
    url_for,
    flash,
    jsonify,
)
from flask_login import login_required, current_user

from . import db
from .models import User

billing_bp = Blueprint("billing", __name__, url_prefix="/billing")


# ============================================================
# Initialize Stripe
# ============================================================
def init_stripe():
    """Configure the global Stripe API key from app config."""
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]


# ============================================================
# Create Checkout Session for Subscription
# ============================================================
@billing_bp.route("/subscribe/<plan>", methods=["GET"])
@login_required
def subscribe(plan):
    """
    Start a Stripe Checkout session for the given plan:
      - basic
      - premium
      - professional
    """
    init_stripe()

    # Map plan -> Stripe Price ID from config
    if plan == "basic":
        price_id = current_app.config["STRIPE_BASIC_PRICE_ID"]
    elif plan == "premium":
        price_id = current_app.config["STRIPE_PREMIUM_PRICE_ID"]
    elif plan == "professional":
        price_id = current_app.config["STRIPE_PROFESSIONAL_PRICE_ID"]
    else:
        flash("Invalid plan selected.", "danger")
        return redirect(url_for("views.dashboard"))

    if not price_id:
        flash("This plan is not configured yet. Contact support.", "danger")
        return redirect(url_for("views.dashboard"))

    try:
        # Create checkout session
        session = stripe.checkout.Session.create(
            customer_email=current_user.email,
            payment_method_types=["card"],
            mode="subscription",
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            success_url=request.host_url.rstrip("/")
            + url_for("billing.success"),
            cancel_url=request.host_url.rstrip("/")
            + url_for("views.dashboard"),
        )

        return redirect(session.url, code=303)

    except Exception as e:
        flash(f"Stripe error: {e}", "danger")
        return redirect(url_for("views.dashboard"))


# ============================================================
# Success Page
# ============================================================
@billing_bp.route("/success")
def success():
    """
    Land here after a successful Stripe Checkout.
    The actual subscription activation is handled by webhooks.
    """
    flash("Subscription activated! Thank you!", "success")
    return redirect(url_for("views.dashboard"))


# ============================================================
# Stripe Billing Portal (Manage Billing)
# ============================================================
@billing_bp.route("/portal")
@login_required
def billing_portal():
    """
    Send the user to Stripe's Billing Portal to manage:
      - card details
      - subscription (cancel/upgrade)
      - invoices
    """
    init_stripe()

    if not current_user.stripe_customer_id:
        flash("No Stripe customer found for your account.", "danger")
        return redirect(url_for("views.dashboard"))

    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=current_user.stripe_customer_id,
            return_url=request.host_url.rstrip("/") + url_for("views.dashboard"),
        )
        return redirect(portal_session.url, code=303)
    except Exception as e:
        flash(f"Error loading billing portal: {e}", "danger")
        return redirect(url_for("views.dashboard"))


# ============================================================
# Stripe Webhook — handles subscription events
# ============================================================
@billing_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    """
    Handle Stripe webhook events such as:
      - customer.subscription.updated
      - customer.subscription.deleted
      - customer.created
    These events keep our User.tier and Stripe IDs in sync.
    """
    init_stripe()

    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    webhook_secret = current_app.config["STRIPE_WEBHOOK_SECRET"]

    if webhook_secret:
        # Verify webhook signature in production
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    else:
        # In dev, if no secret is set, just parse JSON
        event = json.loads(payload)

    event_type = event.get("type")
    data = event.get("data", {}).get("object", {})

    # ========================================================
    # customer.subscription.updated
    #   - Set user.tier based on price ID
    # ========================================================
    if event_type == "customer.subscription.updated":
        subscription_id = data.get("id")
        customer_id = data.get("customer")
        status = data.get("status")

        # Determine tier from price ID
        try:
            item = data["items"]["data"][0]
            price_id = item["price"]["id"]
        except Exception:
            price_id = None

        if price_id == current_app.config["STRIPE_BASIC_PRICE_ID"]:
            tier = "basic"
        elif price_id == current_app.config["STRIPE_PREMIUM_PRICE_ID"]:
            tier = "premium"
        elif price_id == current_app.config["STRIPE_PROFESSIONAL_PRICE_ID"]:
            tier = "professional"
        else:
            tier = "free"

        user = User.query.filter_by(stripe_customer_id=customer_id).first()
        if user:
            # If subscription is not active, downgrade to free
            if status not in ("active", "trialing"):
                user.tier = "free"
            else:
                user.tier = tier
            user.stripe_subscription_id = subscription_id
            db.session.commit()

    # ========================================================
    # customer.created
    #   - Attach stripe_customer_id to User via email
    # ========================================================
    elif event_type == "customer.created":
        customer_id = data.get("id")
        email = data.get("email")

        if email:
            user = User.query.filter_by(email=email).first()
            if user:
                user.stripe_customer_id = customer_id
                db.session.commit()

    # ========================================================
    # customer.subscription.deleted
    #   - Downgrade user to free tier
    # ========================================================
    elif event_type == "customer.subscription.deleted":
        customer_id = data.get("customer")
        user = User.query.filter_by(stripe_customer_id=customer_id).first()
        if user:
            user.tier = "free"
            user.stripe_subscription_id = None
            db.session.commit()

    return jsonify({"status": "success"}), 200
