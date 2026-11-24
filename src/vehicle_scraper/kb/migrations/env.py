"""Alembic environment for the knowledge base.

The database URL comes, in order, from ``config.attributes["url"]`` (set by
``vehicle_scraper kb migrate``), ``alembic -x url=...``, or ``$OMNIBASE_DATABASE_URL``.
The ``alembic_version`` table lives in the database's default schema (``public``).
"""
from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from vehicle_scraper.kb.db import database_url, sqlalchemy_url

config = context.config
url = sqlalchemy_url(config.attributes.get("url")
                     or context.get_x_argument(as_dictionary=True).get("url")
                     or database_url())


def run_offline() -> None:
    context.configure(url=url, literal_binds=True, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
