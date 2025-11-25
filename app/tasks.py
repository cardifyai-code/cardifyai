# app/tasks.py

"""
Celery background flashcard generation for CardifyAI (Option A).

This file:
✔ Defines the Celery instance
✔ Connects to Redis for broker + backend
✔ Provides enqueue_flashcard_job() for views.py
✔ Provides get_job() so the dashboard can poll
✔ Stores job status/results in Redis
✔ Uses your AI generator to create flashcards in the background
"""

import json
import redis
from datetime import datetime
from celery import Celery

from .config import Config
from .ai import generate_flashcards_from_text


# ================================
# Celery Setup
# ================================
celery = Celery(
    "cardify_tasks",
    broker=Config.REDIS_URL,
    backend=Config.REDIS_URL,
)

redis_client = redis.StrictRedis.from_url(
    Config.REDIS_URL, decode_responses=True
)


# ================================
# Internal Redis helpers
# ================================
def _save_job(job_id: str, data: dict):
    """Store job metadata/state in Redis."""
    redis_client.set(f"job:{job_id}", json.dumps(data))


def _load_job(job_id: str):
    """Retrieve job state from Redis."""
    raw = redis_client.get(f"job:{job_id}")
    if not raw:
        return None
    return json.loads(raw)


# ================================
# PUBLIC: enqueue a job
# ================================
def enqueue_flashcard_job(user_id: int, text: str, num_cards: int):
    """
    Called by views.py.

    Kicks off a Celery background job and stores an initial placeholder
    in Redis so the UI can poll immediately.
    """
    job = generate_flashcards_task.apply_async(
        args=[user_id, text, num_cards]
    )
    job_id = job.id

    # Immediately store that the job was queued
    _save_job(
        job_id,
        {
            "status": "queued",
            "result": None,
            "created_at": datetime.utcnow().isoformat(),
        },
    )

    return job_id


# ================================
# PUBLIC: retrieve job info
# ================================
def get_job(job_id: str):
    """Used by the polling endpoint in views.py."""
    return _load_job(job_id)


# ================================
# Celery task
# ================================
@celery.task(bind=True)
def generate_flashcards_task(self, user_id: int, text: str, num_cards: int):
    """
    True background AI generation.

    Runs inside the Celery worker and saves result status to Redis.
    """
    job_id = self.request.id

    # Mark as running
    _save_job(
        job_id,
        {
            "status": "running",
            "result": None,
            "started_at": datetime.utcnow().isoformat(),
        },
    )

    try:
        # Actually generate flashcards
        cards = generate_flashcards_from_text(text, num_cards)

        # Save success to Redis
        _save_job(
            job_id,
            {
                "status": "complete",
                "result": cards,
                "finished_at": datetime.utcnow().isoformat(),
            },
        )

        return cards

    except Exception as e:
        # Save error details
        _save_job(
            job_id,
            {
                "status": "error",
                "error": str(e),
            },
        )
        raise e
