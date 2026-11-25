"""Review issue ``generation_cycle``: a source gives a generation's official years.

``kb specs import`` reads the years a person captured from a source (a maker's sheet, a
magazine). Years are the generation's identity, not evidence: changing them moves listings on
the next recalculation, so instead of writing them the import opens this case (current and
proposed ``{"year_from", "year_to"}``, the source in the evidence) and a person decides.

Downgrade deletes those cases (generations already changed keep their years).

Revision ID: 0014_generation_cycle
Revises: 0013_year_outside_generation
"""
from __future__ import annotations

from alembic import op

revision = "0014_generation_cycle"
down_revision = "0013_year_outside_generation"
branch_labels = None
depends_on = None

# Frozen here (never imported from live code), like every migration's values.
BEFORE = ("unknown_make", "missing_make", "weak_model", "model_is_attributes", "field_conflict",
          "implausible_value", "generation_split", "spec_disagreement", "evolution_note",
          "year_outside_generation")
AFTER = BEFORE + ("generation_cycle",)


def _check(values) -> str:
    listed = ", ".join(f"'{v}'" for v in values)
    return f"ALTER TABLE kb.review_item ADD CONSTRAINT review_item_issue_check CHECK (issue IN ({listed}))"


def upgrade() -> None:
    op.execute("ALTER TABLE kb.review_item DROP CONSTRAINT review_item_issue_check")
    op.execute(_check(AFTER))


def downgrade() -> None:
    op.execute("DELETE FROM kb.review_item WHERE issue = 'generation_cycle'")
    op.execute("ALTER TABLE kb.review_item DROP CONSTRAINT review_item_issue_check")
    op.execute(_check(BEFORE))
