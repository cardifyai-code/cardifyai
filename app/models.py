from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from . import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # Core identity
    email = db.Column(db.String(255), unique=True, nullable=False)
    # Nullable to support Google-only accounts
    password_hash = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Subscription tier: "free", "basic", "premium"
    tier = db.Column(db.String(20), default="free")

    # Soft usage limits (per day)
    daily_cards_generated = db.Column(db.Integer, default=0)
    daily_reset_date = db.Column(db.Date, nullable=True)

    # Stripe linkage
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)

    # Admin flag
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password: str) -> None:
        if password:
            self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
