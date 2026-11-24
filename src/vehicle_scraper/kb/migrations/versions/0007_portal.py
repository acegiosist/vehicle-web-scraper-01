"""Portal: users with roles and the action inbox the Python worker applies.

* ``kb.app_user``: who may use the portal (email from IAP) and with which role:
  ``lector`` (sees everything), ``revisor`` (also decides review cases), ``editor`` (also
  edits sheets, generations, evolution notes, catalogs, users and runs the recalculation).
* ``kb.web_action``: the only table the portal writes. Each row is a request (decide a case,
  set a value, split a generation, ...) that ``kb worker`` validates and applies with the same
  code as the Excel review, checking the requester's role again. An AFTER INSERT trigger
  NOTIFYs ``kb_web_action`` so the worker wakes up at once.

Revision ID: 0007_portal
Revises: 0006_three_levels
"""
from __future__ import annotations

from alembic import op

revision = "0007_portal"
down_revision = "0006_three_levels"
branch_labels = None
depends_on = None

ROLES = ("lector", "revisor", "editor")
ACTION_KINDS = ("decide_case", "set_value", "split_generation", "merge_generations", "add_evolution_note",
                "catalog_upsert", "user_upsert", "recalculate")


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.execute(f"""
CREATE TABLE kb.app_user (
    email text PRIMARY KEY CHECK (email = lower(email) AND email ~ '^[^@\\s]+@[^@\\s]+$'),
    name text,
    role text NOT NULL CHECK (role IN {_in(ROLES)}),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text
)""")
    op.execute("COMMENT ON TABLE kb.app_user IS "
               "'Usuarios del portal por correo (IAP): lector < revisor < editor; sin fila = sin acceso'")

    op.execute(f"""
CREATE TABLE kb.web_action (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN {_in(ACTION_KINDS)}),
    payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
    requested_by text NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'applied', 'failed')),
    error text,
    result jsonb,
    applied_at timestamptz,
    CHECK ((status IN ('applied', 'failed')) = (applied_at IS NOT NULL))
)""")
    op.execute("CREATE INDEX web_action_queued ON kb.web_action (id) WHERE status = 'queued'")
    op.execute("COMMENT ON TABLE kb.web_action IS "
               "'Bandeja del portal: el sitio solo inserta; kb worker valida, aplica y marca applied/failed'")
    op.execute("""
CREATE FUNCTION kb.notify_web_action() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('kb_web_action', NEW.id::text);
    RETURN NEW;
END $$""")
    op.execute("CREATE TRIGGER web_action_notify AFTER INSERT ON kb.web_action "
               "FOR EACH ROW EXECUTE FUNCTION kb.notify_web_action()")


def downgrade() -> None:
    op.execute("DROP TRIGGER web_action_notify ON kb.web_action")
    op.execute("DROP FUNCTION kb.notify_web_action()")
    op.execute("DROP TABLE kb.web_action")
    op.execute("DROP TABLE kb.app_user")
