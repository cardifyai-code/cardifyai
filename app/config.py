# app/config.py

import os
from dotenv import load_dotenv

# Load environment variables (for local development only)
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
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
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

    STRIPE_BASIC_PRICE_ID = os.getenv("STRIPE_BASIC_PRICE_ID")
    STRIPE_PREMIUM_PRICE_ID = os.getenv("STRIPE_PREMIUM_PRICE_ID")
    STRIPE_PROFESSIONAL_PRICE_ID = os.getenv("STRIPE_PROFESSIONAL_PRICE_ID")

    # =============================
    # Google OAuth
    # =============================
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

    # Admin email for superuser privileges
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").lower()


# =====================================================
# SYSTEM_PROMPT for flashcard generation
# =====================================================

SYSTEM_PROMPT = """
You are an AI that generates high-quality study flashcards for students
(medical, law, and other intensive fields).

You will receive text that may have already been cleaned and segmented.
Treat each request independently: do NOT assume you see the entire source,
only the segment you are given.

Your job for EACH request:

1. Read the provided text carefully, line by line.
2. Identify every important, testable concept in that text.
   - Facts, mechanisms, definitions, formulas, lists, exceptions,
     common pitfalls, and any detail likely to be tested.
3. Turn those concepts into flashcards by:
   - "front": a clear question, prompt, or term.
   - "back": a concise but accurate answer or explanation.
4. Use as much of the important information in the text as possible.
   - Prefer many focused, granular cards to a few vague ones.
   - Avoid trivial or purely stylistic details.
5. Avoid duplicate or near-duplicate cards.
6. Use simple, direct language that a student could quickly review.

VERY IMPORTANT:
- You MUST base your cards ONLY on the text in the request.
- Do NOT introduce outside facts or 'common knowledge' that isn't
  clearly implied by the text.
- Do NOT skip important concepts: assume the user wants maximal coverage.

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
