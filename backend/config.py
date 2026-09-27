"""Environment loading.

Reads a .env file from the project root into os.environ before anything else
looks at it. Kept dependency-free on purpose - python-dotenv is not needed.
Real environment variables always win, so a hosted deploy (Render, Railway)
overrides the file without anyone editing it.
"""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACEHOLDERS = {"", "your_key_here", "sk-...", "changeme", "none", "null"}


def load_dotenv(path: str | None = None) -> list[str]:
    """Load KEY=VALUE lines from .env. Returns the names actually set."""
    env_path = path or os.path.join(ROOT, ".env")
    loaded: list[str] = []
    if not os.path.exists(env_path):
        return loaded

    try:
        raw = open(env_path, encoding="utf-8-sig").read()
    except OSError:
        return loaded

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # strip inline comments and surrounding quotes, then trailing whitespace
        value = value.split(" #", 1)[0].strip().strip('"').strip("'").strip()
        if not key or value.lower() in PLACEHOLDERS:
            continue
        if os.environ.get(key):          # a real env var beats the file
            continue
        os.environ[key] = value
        loaded.append(key)
    return loaded


LOADED = load_dotenv()
