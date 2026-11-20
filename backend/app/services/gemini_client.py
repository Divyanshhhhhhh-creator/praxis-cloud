"""Shared google-genai client factory (one HTTP pool per API key)."""

from __future__ import annotations

from functools import lru_cache

from google import genai


@lru_cache(maxsize=4)
def get_genai_client(api_key: str) -> genai.Client:
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    return genai.Client(api_key=api_key)


def is_retryable_model_error(exc: BaseException) -> bool:
    """429 / 5xx overload errors that justify falling back to a secondary model."""
    code = getattr(exc, "code", None)
    return code in (429, 500, 503, 504)
