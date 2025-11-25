# app/models.py

from datetime import datetime, date
from flask_login import UserMixin

from . import db


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # =========================
    # Auth
    # =========================
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255))  # optional if using Google-only login
    google_id = db.Column(db.String(255), unique=True)

    # =========================
    # Stripe / billing
    # =========================
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))
    stripe_price_id = db.Column(db.String(255))

    # free / basic / premium / professional
    plan = db.Column(db.String(50), default="free")
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)

    # =========================
    # Monthly quotas (by cards)
    # =========================
    monthly_card_quota = db.Column(db.Integer, default=1000)
    cards_generated_this_month = db.Column(db.Integer, default=0)
    quota_reset_at = db.Column(db.DateTime)

    # =========================
    # Daily quotas (by cards)
    # =========================
    daily_cards_generated = db.Column(db.Integer, default=0)
    daily_reset_date = db.Column(db.Date)

    # =========================
    # Token usage tracking (OpenAI)
    # =========================
    # These let you track real API cost per user if you want later.
    daily_input_tokens = db.Column(db.BigInteger, default=0)
    daily_output_tokens = db.Column(db.BigInteger, default=0)
    monthly_input_tokens = db.Column(db.BigInteger, default=0)
    monthly_output_tokens = db.Column(db.BigInteger, default=0)

    # =========================
    # Timestamps
    # =========================
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # =========================
    # Relationships
    # =========================
    flashcards = db.relationship("Flashcard", backref="user", lazy=True)
    subscriptions = db.relationship("Subscription", backref="user", lazy=True)
    visits = db.relationship("Visit", backref="user", lazy=True)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} plan={self.plan}>"

    @property
    def is_premium(self) -> bool:
        """Treat any paid plan as premium."""
        return self.plan in {"basic", "premium", "professional"}

    @property
    def daily_total_tokens(self) -> int:
        """Convenience: total daily tokens (input + output)."""
        return (self.daily_input_tokens or 0) + (self.daily_output_tokens or 0)

    @property
    def monthly_total_tokens(self) -> int:
        """Convenience: total monthly tokens (input + output)."""
        return (self.monthly_input_tokens or 0) + (self.monthly_output_tokens or 0)


class Subscription(db.Model):
    """
    Historical subscription records.
    User has the *current* subscription state; this table stores changes.
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


class Visit(db.Model):
    """
    Simple analytics table for page views / visits.
    Used by admin analytics to track:
      - path
      - user id (if logged in)
      - IP + user agent
      - timestamp
    """

    __tablename__ = "visits"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    path = db.Column(db.String(255), nullable=False, index=True)
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(512))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def __repr__(self) -> str:
        return f"<Visit id={self.id} path={self.path} user_id={self.user_id}>"
