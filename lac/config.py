"""
lac/config.py
─────────────
Manages user configuration stored at ~/.lac/config.json

Config schema:
{
    "model":    "claude-haiku-3-5",   # model identifier
    "provider": "claude",             # claude | openai | ollama | custom
    "api_key":  "sk-...",             # api key (empty for ollama)
    "base_url": "https://...",        # custom base url (optional)
    "server":   "ws://localhost:8765" # lac ws server address
}
"""

import json
import os
from pathlib import Path
from typing import Optional

# default location for all lac config
LAC_DIR = Path.home() / ".lac"
CONFIG_FILE = LAC_DIR / "config.json"

# known provider defaults
PROVIDER_DEFAULTS = {
    "claude": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-haiku-4-5-20251001",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "llama3",
        "api_key": "",  # ollama needs no key
    },
}


def ensure_lac_dir():
    """Create ~/.lac directory if it doesn't exist."""
    LAC_DIR.mkdir(parents=True, exist_ok=True)


def config_exists() -> bool:
    """Check if a config file already exists."""
    return CONFIG_FILE.exists()


def load_config() -> dict:
    """
    Load config from disk.
    Returns empty dict if file doesn't exist.
    """
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def save_config(config: dict):
    """Persist config to ~/.lac/config.json."""
    ensure_lac_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get(key: str, fallback=None):
    """Get a single config value by key."""
    return load_config().get(key, fallback)


def set_value(key: str, value):
    """Update a single config value and save."""
    config = load_config()
    config[key] = value
    save_config(config)


def provider_defaults(provider: str) -> dict:
    """Return default settings for a known provider."""
    return PROVIDER_DEFAULTS.get(provider, {})
