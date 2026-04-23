"""
lac/mind/models.py
──────────────────
Model registry — read/write ~/.lac/mind_models.json
Supports: claude, openai, ollama, custom (local)
"""

import json
from pathlib import Path
from typing import Optional

MODELS_FILE = Path.home() / ".lac" / "mind_models.json"


def load_models() -> list[dict]:
    if not MODELS_FILE.exists():
        return []
    with open(MODELS_FILE) as f:
        return json.load(f)


def save_models(models: list[dict]):
    MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MODELS_FILE, "w") as f:
        json.dump(models, f, indent=2)


def add_model(name: str, provider: str, model: str, api_key: str = "", base_url: str = "") -> dict:
    models = load_models()
    models = [m for m in models if m["name"] != name]
    entry = {"name": name, "provider": provider, "model": model, "api_key": api_key, "base_url": base_url}
    models.append(entry)
    save_models(models)
    return entry


def remove_model(name: str):
    models = [m for m in load_models() if m["name"] != name]
    save_models(models)


def clear_all_models():
    """Delete all models - used for logout"""
    save_models([])


def get_model(name: str) -> Optional[dict]:
    return next((m for m in load_models() if m["name"] == name), None)


PROVIDER_DEFAULTS = {
    "claude":  {"base_url": "https://api.anthropic.com", "model": "claude-haiku-4-5-20251001"},
    "openai":  {"base_url": "https://api.openai.com",    "model": "gpt-4o-mini"},
    "ollama":  {"base_url": "http://localhost:11434",     "model": "llama3", "api_key": ""},
    "custom":  {"base_url": "",                           "model": ""},
}

PROVIDER_LITELLM_PREFIX = {
    "claude": "anthropic",
    "openai": "openai",
    "ollama": "ollama",
    "custom": None,  # user provides full litellm string themselves
}


def to_litellm_model(entry: dict) -> str:
    """Convert stored model entry to a LiteLLM model string."""
    provider = entry.get("provider", "custom")
    model = entry["model"]
    prefix = PROVIDER_LITELLM_PREFIX.get(provider)

    # Already prefixed (e.g. user typed "openai/gpt-4o") — don't double-prefix
    if prefix and not model.startswith(f"{prefix}/"):
        return f"{prefix}/{model}"
    return model