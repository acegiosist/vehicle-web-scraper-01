"""Portal actions ``export_specs`` and ``import_specs``: the capture template from the portal.

The portal's Captura page queues them in ``kb.web_action`` and ``kb worker`` runs the same code
as ``kb specs export`` / ``kb specs import`` (kb/specs.py): the prepared template comes back in
the action's ``result`` (base64) and an uploaded one travels in its ``payload`` (base64, at
most 700 KB). Both need the revisor role (worker.REQUIRED_ROLE).

Downgrade deletes those actions.

Revision ID: 0015_capture_actions
Revises: 0014_generation_cycle
"""
from __future__ import annotations

from alembic import op

revision = "0015_capture_actions"
down_revision = "0014_generation_cycle"
branch_labels = None
depends_on = None

# Frozen here (never imported from live code), like every migration's values.
BEFORE = ("decide_case", "set_value", "split_generation", "merge_generations", "add_evolution_note",
          "catalog_upsert", "user_upsert", "recalculate")
AFTER = BEFORE + ("export_specs", "import_specs")


def _check(values) -> str:
    listed = ", ".join(f"'{v}'" for v in values)
    return f"ALTER TABLE kb.web_action ADD CONSTRAINT web_action_kind_check CHECK (kind IN ({listed}))"


def upgrade() -> None:
    op.execute("ALTER TABLE kb.web_action DROP CONSTRAINT web_action_kind_check")
    op.execute(_check(AFTER))


def downgrade() -> None:
    op.execute("DELETE FROM kb.web_action WHERE kind IN ('export_specs', 'import_specs')")
    op.execute("ALTER TABLE kb.web_action DROP CONSTRAINT web_action_kind_check")
    op.execute(_check(BEFORE))
