# worker.py
"""
RQ worker process for CardifyAI.

This file is used by your Render worker service to process background jobs
(enqueued in app/tasks.py).

It:
- Connects to Redis using REDIS_URL
- Listens on the "flashcards" queue
- Processes jobs like generate_flashcards_job(...)
"""

import os
import sys
import logging

from redis import Redis
from rq import Connection, Worker


# Queues this worker should listen to.
LISTEN_QUEUES = ["flashcards"]


def get_redis_connection() -> Redis:
    """
    Create a Redis connection from REDIS_URL, or fall back to localhost
    for local development.
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return Redis.from_url(redis_url)


def main() -> None:
    """
    Entry point for the worker process.
    """
    # Basic logging setup so you can see what's happening in Render logs.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logger = logging.getLogger("cardifyai.worker")

    logger.info("Starting RQ worker for queues: %s", ", ".join(LISTEN_QUEUES))

    redis_conn = get_redis_connection()

    # Important: RQ will import your job functions (e.g. app.tasks.generate_flashcards_job)
    # based on the pickled call. As long as your code is in the PYTHONPATH (Render starts
    # the worker from the project root), imports like `from app.tasks import ...` will work.
    with Connection(redis_conn):
        worker = Worker(LISTEN_QUEUES)
        logger.info("Worker booted; now listening for jobs...")
        worker.work()  # This blocks and processes jobs until the process is stopped.


if __name__ == "__main__":
    main()
