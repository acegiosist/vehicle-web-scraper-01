"""Exclusion reason "ThreeWheeler": motocarros, mototaxis and other three-wheelers (Bajaj
Torito, Brenson Dynamic). Their attributes (payload, passengers, cab) don't fit the car or
motorcycle levels; they stay in staging and can be brought in later without re-importing.

Revision ID: 0005_three_wheeler
Revises: 0004_identity_clean
"""
from __future__ import annotations

from alembic import op

revision = "0005_three_wheeler"
down_revision = "0004_identity_clean"
branch_labels = None
depends_on = None

CATALOG_ADDITIONS = {
    "exclusion_reason": [("ThreeWheeler", "Motocarro / triciclo", "Three-wheeler (cargo or passenger)")],
}


def upgrade() -> None:
    for table, rows in CATALOG_ADDITIONS.items():
        for code, es, en in rows:
            op.execute(f"INSERT INTO kb.{table} (code, name_es, name_en, sort_order) "
                       f"SELECT '{code}', '{es}', '{en}', coalesce(max(sort_order), 0) + 1 FROM kb.{table}")


def downgrade() -> None:
    op.execute("UPDATE kb.clean_listing SET excluded_reason = NULL WHERE excluded_reason = 'ThreeWheeler'")
    for table, rows in CATALOG_ADDITIONS.items():
        for code, *_ in rows:
            op.execute(f"DELETE FROM kb.{table} WHERE code = '{code}'")
