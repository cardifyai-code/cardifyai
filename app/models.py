from datetime import datetime, date
from flask_login import UserMixin

from . import db


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # Auth
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255))  # optional if using Google-only login
    google_id = db.Column(db.String(255), unique=True)

    # Stripe / billing (current active subscription info)
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))
    stripe_price_id = db.Column(db.String(255))

    # Legacy plan field (kept for compatibility)
    plan = db.Column(db.String(50), default="free")  # free/basic/premium/professional

    # New field used throughout the app (auth.py, views.py)
    tier = db.Column(db.String(50), default="free")  # free/basic/premium/professional

    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)

    # Monthly quotas (optional, kept from original design)
    monthly_card_quota = db.Column(db.Integer, default=1000)
    cards_generated_this_month = db.Column(db.Integer, default=0)
    quota_reset_at = db.Column(db.DateTime)

    # Daily usage tracking (used by views.py)
    daily_cards_generated = db.Column(db.Integer, default=0)
    daily_reset_date = db.Column(db.Date)  # date of last reset

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    flashcards = db.relationship("Flashcard", backref="user", lazy=True)
    subscriptions = db.relationship("Subscription", backref="user", lazy=True)

    def __repr__(self) -> str:
        effective_tier = self.tier or self.plan or "free"
        return f"<User id={self.id} email={self.email} tier={effective_tier}>"

    @property
    def effective_tier(self) -> str:
        """Use tier if set, otherwise fall back to plan, then 'free'."""
        return (self.tier or self.plan or "free").lower()

    @property
    def is_premium(self) -> bool:
        """Treat any paid plan/tier as premium."""
        return self.effective_tier in {"basic", "premium", "professional"}


class Subscription(db.Model):
    """
    Historical subscription records.

    The User table keeps the *current* subscription fields for quick checks.
    This table tracks changes over time: upgrades, downgrades, cancellations, etc.
    """

    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )

    stripe_subscription_id = db.Column(db.String(255), index=True)
    stripe_customer_id = db.Column(db.String(255))
    price_id = db.Column(db.String(255))  # Stripe price id (e.g. price_XXXX)
    plan = db.Column(db.String(50))  # basic/premium/professional
    status = db.Column(db.String(50))  # active/canceled/incomplete/etc.
    cancel_at_period_end = db.Column(db.Boolean, default=False)

    current_period_start = db.Column(db.DateTime)
    current_period_end = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<Subscription id={self.id} user_id={self.user_id} "
            f"plan={self.plan} status={self.status}>"
        )


class Flashcard(db.Model):
    __tablename__ = "flashcards"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )

    front = db.Column(db.Text, nullable=False)
    back = db.Column(db.Text, nullable=False)

    # Optional metadata
    source_type = db.Column(db.String(50))  # e.g. "text", "pdf", "url"
    source_title = db.Column(db.String(255))
    source_id = db.Column(db.String(255))  # if you later add docs/uploads

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Flashcard id={self.id} user_id={self.user_id}>"
