"""A model can be split by the number its listings put at the start of the version.

Revision ID: 0007_model_split
Revises: 0006_ai_run_batch_check
Create Date: 2026-11-23

Some portals write the model family in the model field and the real model's number in the
version: CarroYa's Chevrolet "LV" + "150 Bus" / "452" are the LV 150 and LV 452 trucks, KTM
"Duke" + "200" / "390" are the Duke 200 and Duke 390. `kb normalize` used to group listings by
the model field only, so each family became one model.

`split_by_number` marks such a family (set by a review decision `split` or by
`split_models` in config/kb/makes.yaml): normalize then sends a listing whose version starts with
a 2-4 digit number to the model "<family> <number>", created on demand with `split_from`
pointing back at the family. Listings without that number stay on the family.
"""
from alembic import op

revision = "0007_model_split"
down_revision = "0006_ai_run_batch_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE kb.model
    ADD COLUMN split_by_number boolean NOT NULL DEFAULT false,
    ADD COLUMN split_from bigint REFERENCES kb.model(id);
COMMENT ON COLUMN kb.model.split_by_number IS
    'Family name: the number at the start of each listing''s version is part of the model (LV + 150 = LV 150).';
COMMENT ON COLUMN kb.model.split_from IS
    'The family this model was split from by kb normalize (NULL: not a split model).';
""")


def downgrade() -> None:
    # models already split keep their listings; older code just stops splitting new ones
    op.execute("ALTER TABLE kb.model DROP COLUMN split_from, DROP COLUMN split_by_number;")
