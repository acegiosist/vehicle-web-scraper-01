"""Unassigned reason ``powertrain_rejected``: the listing's powertrain was rejected by a person.

``kb build`` used to skip rejected powertrains while matching, so a listing whose key matched
one exactly tried to create it again and the recalculation failed on
``UNIQUE (generation_id, match_key)``. Now such a listing stays unassigned with this reason,
like a listing of a rejected generation; a rejected powertrain is never recreated.

Downgrade turns these rows into ``ambiguous_powertrain`` (``kb.listing_level`` is rebuilt by the
next ``kb build`` anyway).

Revision ID: 0010_powertrain_rejected
Revises: 0009_review_case_view
"""
from __future__ import annotations

from alembic import op

revision = "0010_powertrain_rejected"
down_revision = "0009_review_case_view"
branch_labels = None
depends_on = None

# Frozen here (never imported from live code), like every migration's values.
BEFORE = ("model_not_accepted", "ambiguous_body", "no_generation_for_year", "ambiguous_powertrain")
AFTER = BEFORE + ("powertrain_rejected",)


def _check(values) -> str:
    listed = ", ".join(f"'{v}'" for v in values)
    return f"ALTER TABLE kb.listing_level ADD CONSTRAINT listing_level_unassigned_reason_check " \
           f"CHECK (unassigned_reason IN ({listed}))"


def upgrade() -> None:
    op.execute("ALTER TABLE kb.listing_level DROP CONSTRAINT listing_level_unassigned_reason_check")
    op.execute(_check(AFTER))


def downgrade() -> None:
    op.execute("UPDATE kb.listing_level SET unassigned_reason = 'ambiguous_powertrain' "
               "WHERE unassigned_reason = 'powertrain_rejected'")
    op.execute("ALTER TABLE kb.listing_level DROP CONSTRAINT listing_level_unassigned_reason_check")
    op.execute(_check(BEFORE))
