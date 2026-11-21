"""Settings the knowledge base re-reads from the repository's .env on every use.

The worker runs for days; switches that guard spending (KB_ALLOW_WEB_AI_SUBMIT, the AI budget)
must take effect when .env changes, without a restart. A value in .env wins over the process
environment (which only holds what .env had when the process started); without the key in .env,
the environment decides.
"""
from __future__ import annotations

import os
from typing import Optional

from dotenv import dotenv_values, find_dotenv

# Path of the .env to read; None = the repository's .env (found like config.py does).
# Tests point it elsewhere; "" reads no file at all (only the environment).
ENV_FILE: Optional[str] = None


def env_file() -> str:
    return ENV_FILE if ENV_FILE is not None else find_dotenv()


def env_setting(name: str) -> Optional[str]:
    path = env_file()
    values = dotenv_values(path) if path else {}
    raw = values[name] if name in values else os.getenv(name)
    return raw.strip() if raw is not None else None


def env_flag(name: str) -> bool:
    return (env_setting(name) or "").lower() in ("1", "true", "yes")
