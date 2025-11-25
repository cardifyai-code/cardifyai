# app/billing.py

import stripe
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    current_app,
    request,
    jsonify,
    url_for,
)
from flask_login import login_required, current_user

from . import db
from .models import User, Subscription
from .config import Config

billing_bp = Blueprint("billing", __name__)

# Stripe global config
stripe.api_key = Config.STRIPE_SECRET_KEY


PLAN_PRICE_MAP = {
    "basic": Config.STRIPE_BASIC_PRICE_ID,
    "premium": Config.STRIPE_PREMIUM_PRICE_ID,
    "professional": Config.STRIPE_PROFESSIONAL_PRICE_ID,
}


PLAN_QUOTAS = {
    "free": 1000,
    "basic": 5000,
    "premium": 10000,
    "professional": 50000,
}


def _update_user_plan_from_stripe(user: User, plan: str, stripe_sub) -> None:
    user.plan = plan
    user.stripe_subscription_id = stripe_sub.id
    user.stripe_price_id = stripe_sub.items.data[0].price.id if stripe_sub.items.data else None
    user.is_active = stripe_sub.status == "active"

    # Reset monthly quota starting now
    user.monthly_card_quota = PLAN_QUOTAS.get(plan, 1000)
    user.cards_generated_this_month = 0
    user.quota_reset_at = datetime.utcnow() + timedelta(days=30)

    db.session.commit()

    # Log Subscription history
    sub = Subscription(
        user_id=user.id,
        stripe_subscription_id=stripe_sub.id,
        stripe_customer_id=stripe_sub.customer,
        price_id=user.stripe_price_id,
        plan=plan,
        status=stripe_sub.status,
        cancel_at_period_end=stripe_sub.cancel_at_period_end or False,
        current_period_start=datetime.fromtimestamp(stripe_sub.current_period_start),
        current_period_end=datetime.fromtimestamp(stripe_sub.current_period_end),
    )
    db.session.add(sub)
    db.session.commit()


@billing_bp.route("/checkout/<plan>", methods=["POST"])
@login_required
def checkout(plan):
    plan = plan.lower()
    if plan not in PLAN_PRICE_MAP:
        return jsonify({"error": "Invalid plan"}), 400

    price_id = PLAN_PRICE_MAP[plan]
    if not price_id:
        return jsonify({"error": "Stripe price ID not configured for this plan."}), 500

    # Ensure Stripe customer
    if not current_user.stripe_customer_id:
        customer = stripe.Customer.create(
            email=current_user.email,
        )
        current_user.stripe_customer_id = customer.id
        db.session.commit()
    else:
        customer = stripe.Customer.retrieve(current_user.stripe_customer_id)

    # Create checkout session
    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        customer=customer.id,
        line_items=[
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        success_url=url_for("views.dashboard", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=url_for("views.dashboard", _external=True),
    )

    return jsonify({"checkout_url": session.url})


@billing_bp.route("/portal", methods=["POST"])
@login_required
def billing_portal():
    if not current_user.stripe_customer_id:
        return jsonify({"error": "No Stripe customer found"}), 400

    session = stripe.billing_portal.Session.create(
        customer=current_user.stripe_customer_id,
        return_url=url_for("views.dashboard", _external=True),
    )
    return jsonify({"portal_url": session.url})


@billing_bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature")

    endpoint_secret = Config.STRIPE_WEBHOOK_SECRET
    if not endpoint_secret:
        return "missing webhook secret", 400

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError:
        return "invalid payload", 400
    except stripe.error.SignatureVerificationError:
        return "invalid signature", 400

    # Handle events
    if event["type"] == "customer.subscription.updated" or event["type"] == "customer.subscription.created":
        subscription = event["data"]["object"]
        customer_id = subscription["customer"]

        user = User.query.filter_by(stripe_customer_id=customer_id).first()
        if user:
            price_id = subscription["items"]["data"][0]["price"]["id"]
            # Reverse map price -> plan
            plan = "free"
            for p, pid in PLAN_PRICE_MAP.items():
                if pid == price_id:
                    plan = p
                    break
            _update_user_plan_from_stripe(user, plan, subscription)

    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription["customer"]

        user = User.query.filter_by(stripe_customer_id=customer_id).first()
        if user:
            user.plan = "free"
            user.stripe_subscription_id = None
            user.stripe_price_id = None
            user.is_active = True
            user.monthly_card_quota = PLAN_QUOTAS["free"]
            user.cards_generated_this_month = 0
            user.quota_reset_at = None
            db.session.commit()

    return jsonify({"status": "success"})
