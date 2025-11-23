import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    # =============================
    # Flask
    # =============================
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev_secret_key")
    FLASK_ENV = os.getenv("FLASK_ENV", "development")

    # =============================
    # Database
    # =============================
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///ankifyai.sqlite3"  # fallback for local dev
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # =============================
    # OpenAI
    # =============================
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # =============================
    # Stripe
    # =============================
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
    STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

    STRIPE_BASIC_PRICE_ID = os.getenv("STRIPE_BASIC_PRICE_ID")         # $3.99
    STRIPE_PREMIUM_PRICE_ID = os.getenv("STRIPE_PREMIUM_PRICE_ID")     # $7.99
    STRIPE_PROFESSIONAL_PRICE_ID = os.getenv("STRIPE_PROFESSIONAL_PRICE_ID")  # $19.99

    # =============================
    # Google OAuth
    # =============================
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

    # Admin email for unlimited privileges
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").lower()
