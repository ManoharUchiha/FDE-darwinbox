"""Dynamic LLM client. Swap model/provider via env vars only, no code change.

  LLM_PROVIDER=openai      LLM_MODEL=gpt-4o-mini      OPENAI_API_KEY=...
  LLM_PROVIDER=ollama      LLM_MODEL=llama3.1         (local, no key)
  LLM_PROVIDER=google_genai LLM_MODEL=gemini-1.5-flash GOOGLE_API_KEY=...

Returns None if unset/unavailable so callers fall back to rule-based logic.
"""
import os
from functools import lru_cache

from langchain.chat_models import init_chat_model

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "ollama": "llama3.1",
    "google_genai": "gemini-1.5-flash",
}


@lru_cache(maxsize=1)
def get_chat_model():
    provider = os.environ.get("LLM_PROVIDER")
    if not provider:
        return None
    model = os.environ.get("LLM_MODEL", DEFAULT_MODELS.get(provider))
    try:
        return init_chat_model(model, model_provider=provider)
    except Exception:
        return None
