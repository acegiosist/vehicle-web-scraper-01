"""The worker checks submitted AI batches and marks the finished ones (to tell the reviewers).

Revision ID: 0006_ai_run_batch_check
Revises: 0005_ai_run_cost
Create Date: 2026-11-23

Nothing told anyone when a Message Batch finished: a run stayed `submitted` until someone ran
`--collect`. Now `kb worker` asks Anthropic every few minutes (`--batch-check`, a free read) and
moves a finished run to `ended` (a status the CHECK already allowed), with the batch's end time
in `ended_at` and its request counts in `batch_counts`. The review website shows a notice for
`ended` runs; collecting stays a human action and then sets `applied` as before.
"""
from alembic import op

revision = "0006_ai_run_batch_check"
down_revision = "0005_ai_run_cost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE kb.ai_run
    ADD COLUMN batch_checked_at timestamptz,
    ADD COLUMN batch_counts jsonb;
COMMENT ON COLUMN kb.ai_run.batch_checked_at IS
    'Last time the worker asked Anthropic for the batch status (NULL: never checked).';
COMMENT ON COLUMN kb.ai_run.batch_counts IS
    'Request counts of the batch at the last check: succeeded, errored, expired, canceled, processing.';
""")


def downgrade() -> None:
    # older code only collects `submitted` runs: give the finished, uncollected ones back
    op.execute("""
UPDATE kb.ai_run SET status = 'submitted', ended_at = NULL WHERE status = 'ended';
ALTER TABLE kb.ai_run DROP COLUMN batch_counts, DROP COLUMN batch_checked_at;
""")
