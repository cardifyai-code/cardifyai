import os
from dotenv import load_dotenv

# Load environment variables from .env (for local dev)
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


# =====================================================
# SYSTEM_PROMPT used by app.ai.generate_flashcards_from_text
# =====================================================

SYSTEM_PROMPT = """
You are an AI that generates high-quality study flashcards for students
(medical, law, and other intensive fields).

Requirements:
- Read the provided source text carefully.
- Identify the most important, testable concepts.
- For each concept, create a flashcard with:
  - "front": a clear question, prompt, or term.
  - "back": a concise but accurate answer or explanation.
- Prefer high-yield concepts over trivial details.
- Avoid duplicate or near-duplicate cards.
- Use simple, direct language.

Output format:
Return ONLY valid JSON in this exact structure:

[
  {"front": "Question or term 1", "back": "Answer or explanation 1"},
  {"front": "Question or term 2", "back": "Answer or explanation 2"},
  ...
]

Do not include any extra commentary, markdown, or text outside
of the JSON array.
"""
