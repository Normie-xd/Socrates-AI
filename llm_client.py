import json
import logging
from functools import lru_cache

from google import genai
from google.genai import errors, types

import config

log = logging.getLogger("socrates.llm")


class LLMError(Exception):
    """Error whose message is safe to show to the user."""


@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """Create the client once and reuse it for the whole app."""
    if config.USE_VERTEX:
        return genai.Client(
            vertexai=True, project=config.GCP_PROJECT, location=config.GCP_LOCATION
        )
    if not config.GOOGLE_API_KEY:
        raise LLMError("GOOGLE_API_KEY is missing. Add it to your .env file.")
    return genai.Client(api_key=config.GOOGLE_API_KEY)


def generate(prompt: str, system: str | None = None) -> str:
    resp = get_client().models.generate_content(
        model=config.MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system),
    )
    return resp.text


# Flips to False if the model rejects our thinking setting, so we stop retrying it.
_thinking_ok = True

_VALID_LEVELS = {"minimal", "low", "medium", "high"}


def _thinking_config():
    level = config.THINKING_LEVEL
    if not _thinking_ok or not level:
        return None
    if level not in _VALID_LEVELS:
        log.warning("Ignoring invalid THINKING_LEVEL=%r", level)
        return None
    return types.ThinkingConfig(thinking_level=types.ThinkingLevel(level.upper()))


def _call(contents, system, schema, max_tokens, thinking):
    return get_client().models.generate_content(
        model=config.MODEL_NAME,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=max_tokens,
            thinking_config=thinking,
        ),
    )


def _friendly(e: errors.APIError) -> str:
    code = getattr(e, "code", None)
    if code == 429:
        return "Rate limit reached on the free tier. Wait a minute and try again."
    if code in (401, 403):
        return "The API key was rejected. Check GOOGLE_API_KEY in your .env file."
    if code == 404:
        return "Model not found. Check MODEL_NAME in your .env file."
    if isinstance(code, int) and code >= 500:
        return "Google's servers are busy. Try again in a moment."
    return "The AI service rejected the request. Try rephrasing or try again."


def generate_json(contents, system: str, schema, max_tokens: int | None = None):
    """Call the model and return a validated pydantic object."""
    global _thinking_ok
    max_tokens = max_tokens or config.MAX_OUTPUT_TOKENS_CHAT
    thinking = _thinking_config()
    try:
        try:
            resp = _call(contents, system, schema, max_tokens, thinking)
        except errors.ClientError as e:
            if thinking is not None and getattr(e, "code", None) == 400:
                log.warning("Thinking setting rejected by %s; retrying without it", config.MODEL_NAME)
                _thinking_ok = False
                resp = _call(contents, system, schema, max_tokens, None)
            else:
                raise
    except errors.APIError as e:
        log.error("API error %s: %s", getattr(e, "code", "?"), e)
        raise LLMError(_friendly(e)) from e
    except LLMError:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("Unexpected error calling the model")
        raise LLMError("Unexpected error talking to the AI. See the terminal for details.") from e

    if resp.parsed is not None:
        return resp.parsed
    if not resp.text:
        raise LLMError("The model returned an empty response (it may have been blocked). Try rephrasing.")
    try:
        return schema.model_validate(json.loads(resp.text))
    except Exception as e:  # noqa: BLE001
        log.error("Could not parse model output: %.200s", resp.text)
        raise LLMError("The model's answer was cut off or malformed. Please try again.") from e