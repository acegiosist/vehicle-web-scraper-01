"""Connection settings for the knowledge base database (``omnibase``)."""
from __future__ import annotations

import os
import re
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

ENV_VAR = "OMNIBASE_DATABASE_URL"
# Key of the transaction-scoped advisory lock every writing command takes, so two imports
# (or, later, an import and a consolidation) never interleave.
WRITER_LOCK_KEY = 7_340_001


class MissingDatabaseUrl(RuntimeError):
    pass


def database_url(explicit: Optional[str] = None) -> str:
    """The connection string: ``explicit`` (``--database-url``) or ``$OMNIBASE_DATABASE_URL``."""
    url = (explicit or os.getenv(ENV_VAR, "")).strip()
    if not url:
        raise MissingDatabaseUrl(
            f"no database configured: set {ENV_VAR} in .env "
            "(e.g. postgresql://user:password@localhost:5432/omnibase) or pass --database-url")
    return url


def libpq_url(url: str) -> str:
    """``postgresql+psycopg://`` (SQLAlchemy style) -> ``postgresql://`` (what psycopg takes)."""
    return re.sub(r"^postgres(?:ql)?\+\w+://", "postgresql://", url)


def sqlalchemy_url(url: str) -> str:
    """Any PostgreSQL URL -> ``postgresql+psycopg://`` so Alembic uses psycopg 3."""
    return re.sub(r"^postgres(?:ql)?(?:\+\w+)?://", "postgresql+psycopg://", url)


def connect(url: str):
    import psycopg
    return psycopg.connect(libpq_url(url))


def take_writer_lock(cur) -> None:
    """Wait for, then hold until commit/rollback, the knowledge base's single-writer lock."""
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (WRITER_LOCK_KEY,))
