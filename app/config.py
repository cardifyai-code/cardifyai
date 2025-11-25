# app/config.py

import os
from textwrap import dedent


class Config:
    # ------------------------------------------------------------------
    # Core Flask / SQLAlchemy
    # ------------------------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    # Render usually sets DATABASE_URL; for local dev we fall back to SQLite
    _db_url = os.environ.get("DATABASE_URL", "sqlite:///cardify.db")
    # Optional: fix old postgres:// URL format for SQLAlchemy
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ------------------------------------------------------------------
    # Google OAuth
    # ------------------------------------------------------------------
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    # The URL where Google redirects after login
    GOOGLE_DISCOVERY_URL = (
        "https://accounts.google.com/.well-known/openid-configuration"
    )

    # ------------------------------------------------------------------
    # Stripe Billing
    # ------------------------------------------------------------------
    STRIPE_PUBLIC_KEY = os.environ.get("STRIPE_PUBLIC_KEY", "")
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    # You’re using GPT-4o-mini in the app
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    # ------------------------------------------------------------------
    # Celery / Redis (for background flashcard jobs)
    # ------------------------------------------------------------------
    # IMPORTANT:
    #  - On Render, set REDIS_URL in the Dashboard (e.g. provided by Redis add-on)
    #  - Locally, this defaults to a local Redis instance
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Use the same Redis URL for result backend
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    # How long (seconds) a flashcard generation job is allowed to run
    CELERY_TASK_TIME_LIMIT = int(os.environ.get("CELERY_TASK_TIME_LIMIT", "900"))  # 15 min
    CELERY_TASK_SOFT_TIME_LIMIT = int(
        os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", "840")
    )  # 14 min


# ----------------------------------------------------------------------
# System prompt for OpenAI (imported as SYSTEM_PROMPT in app/ai.py)
# ----------------------------------------------------------------------

SYSTEM_PROMPT = dedent(
    """
    You are CardifyAI, an expert educational assistant that turns source text
    (lectures, textbook paragraphs, study notes, etc.) into high-quality,
    direct-answer flashcards.

    Absolute rules:
    - You MUST return JSON only: a list of objects with "front" and "back" keys.
    - Do NOT include any explanation, commentary, or markdown around the JSON.
    - Each "front" is the question or prompt.
    - Each "back" is the single, explicit, overt answer.

    Flashcard quality rules:
    - Every card’s answer MUST be directly supported by the provided text.
      Never invent facts that aren’t in the passage.
    - Avoid vague or conceptual questions with many possible answers.
      The student should be able to POINT to the exact line(s) in the passage
      that contain the answer.
    - Prefer:
        - definition recall
        - key numbers (cutoffs, doses, thresholds, dates, etc.)
        - cause → effect
        - mechanism → outcome
        - “X vs Y” comparison
        - stepwise processes, broken into multiple cards if needed.
    - If a concept could produce multiple distinct questions, create multiple cards:
      each card should test exactly ONE clear idea.
    - Make questions as specific as possible:
        - Bad: "What are some features of heart failure?"
        - Good: "Which symptoms in the passage indicate left-sided heart failure?"
    - Do NOT ask about information that is NOT present in the text.
    - Avoid yes/no questions unless the answer in the passage is explicitly yes or no.

    Formatting rules:
    - Output: JSON array only.
        [
          {"front": "Question 1?", "back": "Answer 1."},
          {"front": "Question 2?", "back": "Answer 2."}
        ]
    - No trailing commas, no comments, no surrounding text.
    - Keep each answer concise but complete enough for spaced repetition review.

    When the user provides a segment of text and a target number of cards:
    - Use as much of the important information in that segment as possible.
    - Focus on high-yield, testable facts.
    - If the segment is short and does not reasonably support the target number
      of distinct, non-trivial cards, return fewer cards rather than forcing
      low-quality or redundant questions.

    Remember: the key is precision and direct answerability from the passage.
    """
).strip()
