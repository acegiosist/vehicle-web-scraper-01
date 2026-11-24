"""First portal editor, from the environment (so no email is written in the repository).

Reads ``KB_FIRST_EDITOR_EMAIL`` (required) and ``KB_FIRST_EDITOR_NAME`` (optional) from the
environment or ``.env`` when the migration runs, and inserts that user as ``editor``: the role
that can give access to everyone else from the portal's Usuarios page.

* Variable missing or not an email: nothing is inserted and a warning is logged. To retry,
  set it and run ``kb migrate 0007_portal --downgrade`` followed by ``kb migrate``.
* The user already exists: it is left as it is (its role is never changed here).
* Downgrade removes the row only if this migration created it and nobody changed it since
  (an edit from the portal replaces ``updated_by`` with the editor's email).

Revision ID: 0008_first_editor
Revises: 0007_portal
"""
from __future__ import annotations

import logging
import os
import re

import sqlalchemy as sa
from alembic import op

revision = "0008_first_editor"
down_revision = "0007_portal"
branch_labels = None
depends_on = None

MARK = "migration:0008_first_editor"
log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    email = os.getenv("KB_FIRST_EDITOR_EMAIL", "").strip().lower()
    name = os.getenv("KB_FIRST_EDITOR_NAME", "").strip() or None
    if not re.fullmatch(r"[^@\s]+@[^@\s]+", email):
        log.warning("KB_FIRST_EDITOR_EMAIL is not set (or not an email): no portal user was created. "
                    "Set it in .env and run `kb migrate 0007_portal --downgrade` then `kb migrate`, "
                    "or insert the row into kb.app_user by hand.")
        return
    result = op.get_bind().execute(sa.text("""
INSERT INTO kb.app_user (email, name, role, updated_by) VALUES (:email, :name, 'editor', :mark)
ON CONFLICT (email) DO NOTHING"""), {"email": email, "name": name, "mark": MARK})
    log.info("first portal editor %s", "created" if result.rowcount else "already existed: left unchanged")


def downgrade() -> None:
    op.execute(f"DELETE FROM kb.app_user WHERE updated_by = '{MARK}'")
