"""Review issue ``year_outside_generation``: listings from years outside a generation's cycle.

When a reimport brings a listing whose model year no generation of its model and body covers
(the official cycle ends before it, or starts after), ``kb build`` used to leave it unassigned
in silence (``no_generation_for_year``). Now it opens one case per generation and side (field
``year_to`` or ``year_from``) proposing to extend that generation's cycle; a person decides.

Downgrade deletes those cases (generations already extended keep their years).

Revision ID: 0013_year_outside_generation
Revises: 0012_variant_rejected
"""
from __future__ import annotations

from alembic import op

revision = "0013_year_outside_generation"
down_revision = "0012_variant_rejected"
branch_labels = None
depends_on = None

# Frozen here (never imported from live code), like every migration's values.
BEFORE = ("unknown_make", "missing_make", "weak_model", "model_is_attributes", "field_conflict",
          "implausible_value", "generation_split", "spec_disagreement", "evolution_note")
AFTER = BEFORE + ("year_outside_generation",)


def _check(values) -> str:
    listed = ", ".join(f"'{v}'" for v in values)
    return f"ALTER TABLE kb.review_item ADD CONSTRAINT review_item_issue_check CHECK (issue IN ({listed}))"


def upgrade() -> None:
    op.execute("ALTER TABLE kb.review_item DROP CONSTRAINT review_item_issue_check")
    op.execute(_check(AFTER))


def downgrade() -> None:
    op.execute("DELETE FROM kb.review_item WHERE issue = 'year_outside_generation'")
    op.execute("ALTER TABLE kb.review_item DROP CONSTRAINT review_item_issue_check")
    op.execute(_check(BEFORE))
