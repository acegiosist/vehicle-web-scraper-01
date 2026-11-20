"""Alembic environment for the knowledge base.

The database URL comes from ``alembic -x url=...`` or the ``KB_DATABASE_URL`` environment
variable (also read from .env). ``postgresql://`` URLs are switched to the psycopg 3 driver.
The version table lives in ``public.kb_alembic_version`` so the KB can share a database
with other applications without clashing with their own ``alembic_version`` table.
"""
from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

try:  # .env support, same as the rest of the project
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

VERSION_TABLE = "kb_alembic_version"


def database_url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url") or os.getenv("KB_DATABASE_URL", "")
    if not url:
        raise SystemExit("No database URL: pass `alembic -x url=postgresql://...` or set KB_DATABASE_URL")
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def run_migrations_offline() -> None:
    context.configure(url=database_url(), literal_binds=True, version_table=VERSION_TABLE,
                      transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, version_table=VERSION_TABLE,
                          transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
