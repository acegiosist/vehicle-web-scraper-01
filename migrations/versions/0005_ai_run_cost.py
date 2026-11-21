"""Real cost of each AI run (for the spending limit, KB_AI_BUDGET_USD).

Revision ID: 0005_ai_run_cost
Revises: 0004_queue_ai_origin
Create Date: 2026-11-21

`kb.ai_run` already keeps the estimate (`est_cost_usd`, at submission) and the token usage of a
collected batch. It gains `cache_write_tokens` and `actual_cost_usd`, which
`ai_batch.store_and_apply` fills when the results are collected. Runs collected before this
revision get their real cost from the tokens they already have (no cache writes were recorded).
The budget counts each run with `COALESCE(actual_cost_usd, est_cost_usd)` (see kb/budget.py).
"""
from alembic import op

revision = "0005_ai_run_cost"
down_revision = "0004_queue_ai_origin"
branch_labels = None
depends_on = None

# Same prices as ai_batch.PRICE_* (Message Batches, claude-opus-5-5), per token.
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ = 2.0 / 1e6, 10.0 / 1e6, 0.10 / 1e6


def upgrade() -> None:
    op.execute("""
ALTER TABLE kb.ai_run
    ADD COLUMN cache_write_tokens bigint NOT NULL DEFAULT 0,
    ADD COLUMN actual_cost_usd numeric(10, 4);
COMMENT ON COLUMN kb.ai_run.actual_cost_usd IS
    'Real cost of the collected batch (USD), from its token usage. NULL until collected.';
""")
    op.execute(f"""
UPDATE kb.ai_run
   SET actual_cost_usd = round((input_tokens * {PRICE_IN} + output_tokens * {PRICE_OUT}
                               + cache_read_tokens * {PRICE_CACHE_READ})::numeric, 4)
 WHERE status = 'applied' AND actual_cost_usd IS NULL;
""")


def downgrade() -> None:
    op.execute("ALTER TABLE kb.ai_run DROP COLUMN actual_cost_usd, DROP COLUMN cache_write_tokens")
