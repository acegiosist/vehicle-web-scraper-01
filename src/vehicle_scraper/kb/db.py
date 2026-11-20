"""PostgreSQL access for the knowledge base (psycopg 3)."""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ENV_VAR = "KB_DATABASE_URL"


def database_url(explicit: Optional[str] = None) -> str:
    url = explicit or os.getenv(ENV_VAR, "")
    if not url:
        raise SystemExit(f"No database URL: pass --database-url or set {ENV_VAR}")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def connect(url: Optional[str] = None) -> Iterator[psycopg.Connection]:
    """One connection, one transaction: committed on success, rolled back on any error."""
    with psycopg.connect(database_url(url), row_factory=dict_row) as conn:
        yield conn


WRITER_LOCK = "vehicle_scraper.kb.writer"


def writer_lock(conn: psycopg.Connection, wait_message: Optional[str] = None) -> None:
    """Only one writer at a time (CLI steps and the review worker). Transaction-scoped:
    released on commit/rollback. Blocks until the other writer finishes."""
    got = conn.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s)) AS ok", (WRITER_LOCK,)).fetchone()["ok"]
    if not got:
        if wait_message:
            print(wait_message, file=sys.stderr, flush=True)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (WRITER_LOCK,))


def jsonb(value) -> Jsonb:
    return Jsonb(value)


def compact_key(text: object) -> str:
    """Spelling-insensitive key: 'Rav 4' / 'RAV4' / 'rav-4' -> 'rav4'."""
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def slugify(text: object) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "unknown"


def dumps(value) -> str:
    """Deterministic JSON (sorted keys): stable hashes and cache-friendly prompts."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
