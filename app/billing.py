# app/billing.py

import stripe
from flask import (
    Blueprint,
    current_app,
    request,
    redirect,
    url_for,
    flash,
)
from flask_login import login_required, current_user

from . import db
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
        "tier": "basic",
    },
    "premium": {
        "price_id": Config.STRIPE_PREMIUM_PRICE_ID,
        "tier": "premium",
    },
    "professional": {
        "price_id": Config.STRIPE_PROFESSIONAL_PRICE_ID,
        "tier": "professional",
    },
}


# =============================
# Helpers
# =============================

def _ensure_stripe_customer():
    """
    Ensure the current_user has a Stripe Customer id.
    Creates one in Stripe if needed, and saves it to the DB.
    """
    if not current_user.stripe_customer_id:
        customer = stripe.Customer.create(email=current_user.email)
        current_user.stripe_customer_id = customer.id
        db.session.commit()
    return current_user.stripe_customer_id


def _set_user_plan_from_price(price_id: str, subscription_id: str | None):
    """
    Map a Stripe price_id to an internal tier ("basic", "premium", "professional")
    and update the current_user accordingly (tier + Stripe IDs).
    """
    if not price_id:
        # If no price, treat as free
        current_user.tier = "free"
        if hasattr(current_user, "plan"):
            current_user.plan = "free"
        current_user.stripe_subscription_id = None
        current_user.stripe_price_id = None
        db.session.commit()
        return

    tier = "free"
    for key, cfg in PLAN_CONFIG.items():
        if cfg["price_id"] == price_id:
            tier = cfg["tier"]
            break

    # Update user record
    current_user.tier = tier
    if hasattr(current_user, "plan"):
        current_user.plan = tier

    current_user.stripe_subscription_id = subscription_id
    current_user.stripe_price_id = price_id
    db.session.commit()


# =============================
# Routes
# =============================

@billing_bp.route("/checkout/<plan>", methods=["GET", "POST"])
@login_required
def checkout(plan: str):
    """
    Start a Stripe Checkout session for the selected plan.
    Redirects user directly to Stripe Checkout.
    """
    plan = (plan or "").lower()
    if plan not in PLAN_CONFIG:
        flash("Unknown plan selected.", "danger")
        return redirect(url_for("views.dashboard"))

    price_id = PLAN_CONFIG[plan]["price_id"]
    if not price_id:
        current_app.logger.error("Missing Stripe price id for plan: %s", plan)
        flash("Billing is not configured correctly. Please try again later.", "danger")
        return redirect(url_for("views.dashboard"))

    try:
        customer_id = _ensure_stripe_customer()

        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            success_url=(
                url_for("billing.success", _external=True)
                + "?session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=url_for("billing.cancel", _external=True),
            payment_method_types=["card"],
            mode="subscription",
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
        )

        # Redirect straight to Stripe Checkout
        return redirect(checkout_session.url, code=303)

    except Exception as e:
        current_app.logger.exception("Error creating Stripe checkout session")
        flash(f"Error starting checkout: {e}", "danger")
        return redirect(url_for("views.dashboard"))


@billing_bp.route("/success")
@login_required
def success():
    """
    Landing page after successful Stripe Checkout.
    Verifies the session with Stripe and immediately updates the user's tier.
    """
    session_id = request.args.get("session_id")
    if not session_id:
        flash("Missing Stripe session id.", "danger")
        return redirect(url_for("views.dashboard"))

    try:
        checkout_session = stripe.checkout.Session.retrieve(
            session_id,
            expand=["subscription"],
        )

        subscription = checkout_session.subscription
        if not subscription:
            flash("No subscription attached to this session.", "danger")
            return redirect(url_for("views.dashboard"))

        # Verify this session actually belongs to this user (customer match)
        if (
            checkout_session.customer
            and current_user.stripe_customer_id
            and checkout_session.customer != current_user.stripe_customer_id
        ):
            current_app.logger.warning(
                "Stripe session customer mismatch: %s vs %s",
                checkout_session.customer,
                current_user.stripe_customer_id,
            )
            flash("This checkout session does not belong to your account.", "danger")
            return redirect(url_for("views.dashboard"))

        # If user previously had no customer id, save it now
        if not current_user.stripe_customer_id and checkout_session.customer:
            current_user.stripe_customer_id = checkout_session.customer

        # Extract price id from subscription
        price_id = None
        if subscription.get("items") and subscription["items"]["data"]:
            price_id = subscription["items"]["data"][0]["price"]["id"]

        # Update user immediately based on that price id
        _set_user_plan_from_price(price_id, subscription.id)

        flash("Your subscription is now active!", "success")

    except Exception as e:
        current_app.logger.exception("Error processing Stripe success callback")
        flash(f"Error confirming subscription: {e}", "danger")

    return redirect(url_for("views.dashboard"))


@billing_bp.route("/cancel")
@login_required
def cancel():
    """
    User canceled Stripe Checkout. Just show a message and send them back.
    """
    flash("You canceled the checkout.", "info")
    return redirect(url_for("views.dashboard"))


@billing_bp.route("/portal")
@login_required
def billing_portal():
    """
    Open the Stripe Billing Portal so the user can manage/cancel their subscription.
    After they return, we will sync their subscription status when they visit the dashboard.
    """
    if not current_user.stripe_customer_id:
        flash("You don't have a subscription to manage yet.", "warning")
        return redirect(url_for("views.dashboard"))

    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=current_user.stripe_customer_id,
            return_url=url_for("views.dashboard", _external=True),
        )
        return redirect(portal_session.url, code=303)

    except Exception as e:
        current_app.logger.exception("Error creating Stripe billing portal session")
        flash(f"Error opening billing portal: {e}", "danger")
        return redirect(url_for("views.dashboard"))
