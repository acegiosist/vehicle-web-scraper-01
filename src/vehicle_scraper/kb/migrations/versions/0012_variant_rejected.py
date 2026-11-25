"""Unassigned reason ``variant_rejected``: the listing's commercial variant was rejected by a person.

``kb build`` stored a variant's status but never read it, so a rejected variant kept receiving
listings. Now such a listing stays unassigned with this reason, like a listing of a rejected
generation or powertrain, but keeps its generation and powertrain (the final record inherits
their values). A rejected variant is never recreated; taking the rejection back brings its
listings back on the next build.

Downgrade turns these rows into ``ambiguous_powertrain`` (``kb.listing_level`` and
``kb.final_listing`` are rebuilt by the next ``kb build`` anyway).

Revision ID: 0012_variant_rejected
Revises: 0011_final_listing
"""
from __future__ import annotations

from alembic import op

revision = "0012_variant_rejected"
down_revision = "0011_final_listing"
branch_labels = None
depends_on = None

# Frozen here (never imported from live code), like every migration's values.
BEFORE = ("model_not_accepted", "ambiguous_body", "no_generation_for_year", "ambiguous_powertrain",
          "powertrain_rejected")
AFTER = BEFORE + ("variant_rejected",)


def _check(values) -> str:
    listed = ", ".join(f"'{v}'" for v in values)
    return f"ALTER TABLE kb.listing_level ADD CONSTRAINT listing_level_unassigned_reason_check " \
           f"CHECK (unassigned_reason IN ({listed}))"


def upgrade() -> None:
    op.execute("ALTER TABLE kb.listing_level DROP CONSTRAINT listing_level_unassigned_reason_check")
    op.execute(_check(AFTER))


def downgrade() -> None:
    op.execute("UPDATE kb.listing_level SET unassigned_reason = 'ambiguous_powertrain' "
               "WHERE unassigned_reason = 'variant_rejected'")
    op.execute("UPDATE kb.final_listing SET unassigned_reason = 'ambiguous_powertrain' "
               "WHERE unassigned_reason = 'variant_rejected'")
    op.execute("ALTER TABLE kb.listing_level DROP CONSTRAINT listing_level_unassigned_reason_check")
    op.execute(_check(BEFORE))
