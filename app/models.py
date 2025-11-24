from datetime import datetime, date
from flask_login import UserMixin

from . import db, login_manager


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)

    # Core identity
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))  # kept optional; we use Google OAuth
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Subscription tier: "free", "basic", "premium", "professional"
    tier = db.Column(db.String(32), default="free", nullable=False)

    # Daily usage tracking for flashcards
    daily_cards_generated = db.Column(db.Integer, default=0, nullable=False)
    daily_reset_date = db.Column(db.Date, default=date.today, nullable=False)

    # Stripe linkage
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))

    # Admin flag (your email gets this)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email} tier={self.tier}>"



@login_manager.user_loader
def load_user(user_id: str):
    try:
        return User.query.get(int(user_id))
    except (TypeError, ValueError):
        return None
