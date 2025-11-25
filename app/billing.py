# app/billing.py

import stripe
from flask import (
    Blueprint,
    current_app,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
)
from flask_login import login_required, current_user

from . import db
from .models import User, Subscription
from .config import Config

billing_bp = Blueprint("billing", __name__, url_prefix="/billing")

# Configure Stripe
stripe.api_key = Config.STRIPE_SECRET_KEY


# =============================
# Plan configuration
# =============================

PLAN_CONFIG = {
    "basic": {
        "price_id": Config.STRIPE_BASIC_PRICE_ID,
        "plan": "basic",
    },
    "premium": {
        "price_id": Config.STRIPE_PREMIUM_PRICE_ID,
        "plan": "premium",
    },
    "professional": {
        "price_id": Config.STRIPE_PROFESSIONAL_PRICE_ID,
        "plan": "professional",
    },
}

# Reverse lookup for quick webhook mapping
PRICE_TO_PLAN = {cfg["price_id"]: name for name, cfg in PLAN_CONFIG.items()}


# =============================
# Helpers
# =============================

def _ensure_stripe_customer() -> str:
    """Ensure user has a Stripe customer id."""
    if not current_user.stripe_customer_id:
        customer = stripe.Customer.create(email=current_user.email)
        current_user.stripe_customer_id = customer.id
        db.session.commit()
    return current_user.stripe_customer_id


def _apply_plan_change(user: User, price_id: str | None, subscription_id: str | None, status: str):
    """
    Update a user's plan + maintain a Subscription history entry.
    """

    # Determine plan from price id
    if not price_id:
        plan = "free"
    else:
        plan = PRICE_TO_PLAN.get(price_id, "free")

    # Update user object
    user.plan = plan
    user.stripe_price_id = price_id
    user.stripe_subscription_id = subscription_id
    user.is_active = (status == "active")

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Create subscription history log
    sub = Subscription(
        user_id=user.id,
        stripe_subscription_id=subscription_id,
        stripe_customer_id=user.stripe_customer_id,
        price_id=price_id,
        plan=plan,
        status=status,
        cancel_at_period_end=False,
    )
    try:
        db.session.add(sub)
        db.session.commit()
    except Exception:
        db.session.rollback()


# =============================
# Checkout
# =============================

@billing_bp.route("/checkout/<plan>", methods=["GET"])
@login_required
def checkout(plan: str):
    """
    Start Stripe Checkout session.
    """
    plan = (plan or "").lower()
    if plan not in PLAN_CONFIG:
        flash("Invalid plan selected.", "danger")
        return redirect(url_for("views.dashboard"))

    price_id = PLAN_CONFIG[plan]["price_id"]

    try:
        customer_id = _ensure_stripe_customer()

        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            payment_method_types=["card"],
            success_url=(
                url_for("billing.success", _external=True)
                + "?session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=url_for("billing.cancel", _external=True),
            line_items=[{"price": price_id, "quantity": 1}],
        )

        return redirect(checkout_session.url, code=303)

    except Exception as e:
        current_app.logger.exception("Stripe checkout error")
        flash(f"Checkout error: {e}", "danger")
        return redirect(url_for("views.dashboard"))


# =============================
# Success & Cancel
# =============================

@billing_bp.route("/success")
@login_required
def success():
    """
    User is returned after Stripe checkout.
    """
    session_id = request.args.get("session_id")
    if not session_id:
        flash("Missing session id.", "danger")
        return redirect(url_for("views.dashboard"))

    try:
        session_obj = stripe.checkout.Session.retrieve(
            session_id,
            expand=["subscription"],
        )

        subscription = session_obj.subscription
        if not subscription:
            flash("Subscription not found.", "danger")
            return redirect(url_for("views.dashboard"))

        price_id = None
        if subscription["items"]["data"]:
            price_id = subscription["items"]["data"][0]["price"]["id"]

        _apply_plan_change(
            user=current_user,
            price_id=price_id,
            subscription_id=subscription.id,
            status=subscription.status,
        )

        flash("Your subscription is now active!", "success")

    except Exception as e:
        current_app.logger.exception("Error loading Stripe checkout session")
        flash(f"Error: {e}", "danger")

    return redirect(url_for("views.dashboard"))


@billing_bp.route("/cancel")
@login_required
def cancel():
    flash("Checkout canceled.", "info")
    return redirect(url_for("views.dashboard"))


# =============================
# Stripe Billing Portal
# =============================

@billing_bp.route("/portal")
@login_required
def billing_portal():
    """Allow user to manage their subscription."""
    if not current_user.stripe_customer_id:
        flash("You do not have a subscription yet.", "warning")
        return redirect(url_for("views.dashboard"))

    try:
        session_obj = stripe.billing_portal.Session.create(
            customer=current_user.stripe_customer_id,
            return_url=url_for("views.dashboard", _external=True),
        )
        return redirect(session_obj.url, code=303)

    except Exception as e:
        current_app.logger.exception("Billing portal error")
        flash(f"Error opening billing portal: {e}", "danger")
        return redirect(url_for("views.dashboard"))


# =============================
# Stripe Webhooks (CRITICAL)
# =============================

@billing_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    """
    Sync Stripe subscription lifecycle events.
    Ensures your app always reflects the correct plan state.
    """
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            Config.STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        current_app.logger.error(f"Webhook signature error: {e}")
        return jsonify({"error": "Invalid signature"}), 400

    event_type = event["type"]

    # Subscription object depending on event
    subscription = None
    if "object" in event["data"] and "id" in event["data"]["object"]:
        subscription = event["data"]["object"]

    # Extract user via subscription's customer id
    customer_id = subscription.get("customer") if subscription else None
    user = User.query.filter_by(stripe_customer_id=customer_id).first()

    if not user:
        return jsonify({"status": "no matching user"}), 200

    # Extract price id if it exists
    price_id = None
    items = subscription.get("items", {})
    if items and items.get("data"):
        price_id = items["data"][0]["price"]["id"]

    # =============================
    # Handle all subscription events
    # =============================

    if event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "invoice.payment_succeeded",
    ):
        _apply_plan_change(
            user=user,
            price_id=price_id,
            subscription_id=subscription.get("id"),
            status=subscription.get("status", "active"),
        )

    # Payment failed → downgrade immediately
    elif event_type in (
        "invoice.payment_failed",
        "customer.subscription.unpaid",
        "customer.subscription.past_due",
    ):
        _apply_plan_change(
            user=user,
            price_id=None,
            subscription_id=None,
            status="canceled",
        )

    # Subscription canceled
    elif event_type == "customer.subscription.deleted":
        _apply_plan_change(
            user=user,
            price_id=None,
            subscription_id=None,
            status="canceled",
        )

    return jsonify({"status": "success"}), 200
