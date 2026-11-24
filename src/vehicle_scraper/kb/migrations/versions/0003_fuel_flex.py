"""Fuel type "Flex" (gasoline/ethanol, E85), now written by the scraper (models.py FuelType).

Revision ID: 0003_fuel_flex
Revises: 0002_segments
"""
from __future__ import annotations

from alembic import op

revision = "0003_fuel_flex"
down_revision = "0002_segments"
branch_labels = None
depends_on = None

# Read by tests/test_kb_catalogs.py together with 0001's seeds: (code, name_es, name_en).
CATALOG_ADDITIONS = {
    "fuel_type": [("Flex", "Flex (gasolina/etanol)", "Flex fuel (gasoline/ethanol)")],
}


def upgrade() -> None:
    for table, rows in CATALOG_ADDITIONS.items():
        for code, es, en in rows:
            op.execute(f"INSERT INTO kb.{table} (code, name_es, name_en, sort_order) "
                       f"SELECT '{code}', '{es}', '{en}', coalesce(max(sort_order), 0) + 1 FROM kb.{table}")


def downgrade() -> None:
    for table, rows in CATALOG_ADDITIONS.items():
        for code, *_ in rows:
            op.execute(f"DELETE FROM kb.{table} WHERE code = '{code}'")
