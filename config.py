import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# ---- model / backend ----
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.1-flash-lite")
USE_VERTEX = os.getenv("USE_VERTEX", "false").lower() == "true"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GCP_PROJECT = os.getenv("GCP_PROJECT")
GCP_LOCATION = os.getenv("GCP_LOCATION", "global")

# ---- token / cost controls ----
# "minimal", "low", "medium", "high", or "" to not send a thinking setting at all
THINKING_LEVEL = os.getenv("THINKING_LEVEL", "low").strip().lower()
MAX_OUTPUT_TOKENS_CHAT = _int("MAX_OUTPUT_TOKENS_CHAT", 1000)
MAX_OUTPUT_TOKENS_SOLUTION = _int("MAX_OUTPUT_TOKENS_SOLUTION", 3000)
HISTORY_MESSAGES = max(2, _int("HISTORY_MESSAGES", 8))  # messages resent each turn
MAX_PROBLEM_CHARS = _int("MAX_PROBLEM_CHARS", 4000)
MIN_PROBLEM_CHARS = _int("MIN_PROBLEM_CHARS", 20)
MAX_MESSAGE_CHARS = _int("MAX_MESSAGE_CHARS", 6000)
MAX_CALLS_PER_SESSION = _int("MAX_CALLS_PER_SESSION", 60)
DAILY_CALL_LIMIT = _int("DAILY_CALL_LIMIT", 800)  # whole app, per server process

# ---- tutoring behaviour ----
REPLY_WORD_LIMIT = _int("REPLY_WORD_LIMIT", 120)
MAX_CONCEPTS = _int("MAX_CONCEPTS", 6)
LANGUAGES = ["Python", "C++", "Java"]