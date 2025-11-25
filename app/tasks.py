# app/tasks.py

"""
Background / maintenance tasks for CardifyLabs.

This module is **not** automatically scheduled by Flask or Render.
You can:

- Import and call these functions from a management script, or
- Run them manually in a Flask shell, or
- Wire them into a cron job / external scheduler later.

All functions here are safe to run multiple times; they only update
users when needed.
"""

from datetime import datetime, date

from . import db
from .models import User


def reset_daily_quotas() -> None:
    """
    Reset `daily_cards_generated` for all users when the date changes.

    NOTE:
    - Your main app already does a per-user daily reset on login
      via `ensure_daily_reset(current_user)` in `views.py`.
    - This function is useful if you ever want a global scheduled
      reset (e.g., at midnight via cron).
    """
    today = date.today()

    users = User.query.all()
    changed = 0

    for user in users:
        if not user.daily_reset_date or user.daily_reset_date < today:
            user.daily_reset_date = today
            user.daily_cards_generated = 0
            changed += 1

    if changed:
        db.session.commit()

    print(f"[reset_daily_quotas] Reset daily usage for {changed} users.")


def reset_monthly_quotas() -> None:
    """
    Reset `cards_generated_this_month` and update `quota_reset_at`
    for all users when a new month starts.

    This pairs with your `User` model fields:

        monthly_card_quota
        cards_generated_this_month
        quota_reset_at

    You can call this once per month (e.g., via a cron job) if you
    decide to enforce monthly quotas in addition to daily limits.
    """
    now = datetime.utcnow()

    users = User.query.all()
    changed = 0

    for user in users:
        # If never reset, or month/year changed, reset monthly counters
        if (
            not user.quota_reset_at
            or user.quota_reset_at.year != now.year
            or user.quota_reset_at.month != now.month
        ):
            user.cards_generated_this_month = 0
            user.quota_reset_at = now
            changed += 1

    if changed:
        db.session.commit()

    print(f"[reset_monthly_quotas] Reset monthly usage for {changed} users.")


def recalc_quota_for_plan(user: User) -> None:
    """
    Optional helper: adjust `monthly_card_quota` based on current `plan`.

    This function does **not** write changes to the DB by itself; you
    must call `db.session.commit()` after using it.
    """
    plan = (user.plan or "free").lower()

    # Example mapping (you can tweak these numbers as you like)
    plan_monthly_quota = {
        "free": 300,          # 10/day * ~30 days
        "basic": 6_000,       # 200/day * 30
        "premium": 30_000,    # 1,000/day * 30
        "professional": 150_000,  # 5,000/day * 30
    }

    user.monthly_card_quota = plan_monthly_quota.get(plan, 300)


def sync_all_users_monthly_quota() -> None:
    """
    Walk all users and set `monthly_card_quota` based on their current plan.

    Use this if you ever change the plan limits and want to re-align
    everyone’s monthly quotas in bulk.
    """
    users = User.query.all()
    changed = 0

    for user in users:
        old_quota = user.monthly_card_quota or 0
        recalc_quota_for_plan(user)
        if user.monthly_card_quota != old_quota:
            changed += 1

    if changed:
        db.session.commit()

    print(f"[sync_all_users_monthly_quota] Updated monthly quota for {changed} users.")


# ---------------------------------------------------------------------------
# If you want to run these tasks from the command line, you can do:
#
#   from app import create_app, db
#   from app.tasks import reset_daily_quotas, reset_monthly_quotas
#
#   app = create_app()
#   with app.app_context():
#       reset_daily_quotas()
#       reset_monthly_quotas()
#
# Or wire them into a separate manage.py/CLI script.
# ---------------------------------------------------------------------------
