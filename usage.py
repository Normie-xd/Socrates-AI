"""Guardrails that protect the free-tier quota from runaway or accidental use."""
import threading
from datetime import date

import config


class LimitReached(Exception):
    """Message is safe to show to the user."""


_lock = threading.Lock()
_state = {"day": None, "total": 0}


def check_and_count(session_calls: int) -> None:
    if session_calls >= config.MAX_CALLS_PER_SESSION:
        raise LimitReached(
            "You've reached the AI call limit for this session. "
            "Start a new problem or refresh the page to continue."
        )
    with _lock:
        today = date.today()
        if _state["day"] != today:
            _state["day"], _state["total"] = today, 0
        if _state["total"] >= config.DAILY_CALL_LIMIT:
            raise LimitReached(
                "The app's daily AI quota is used up. Please try again tomorrow."
            )
        _state["total"] += 1