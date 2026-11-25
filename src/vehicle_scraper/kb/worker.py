"""``kb worker``: applies the portal's requests from ``kb.web_action``.

The portal only INSERTs requests; this worker is what changes the knowledge base. For each
queued action, oldest first and one at a time:

1. It checks the requester's role again in ``kb.app_user`` (``lector`` < ``revisor`` <
   ``editor``); the portal hiding a button is not the guard, this is.
2. It validates the payload with the same code as the Excel review (``review.decide``,
   ``review.parse_value``) and applies it inside a savepoint under the writer lock.
3. It marks the action ``applied`` (with a ``result``) or ``failed`` (with the error shown in
   the portal). A failed action changes nothing.

``recalculate`` runs ``kb clean`` + ``kb build``: it is marked ``running`` first (committed),
so the portal can show it, and decisions queued meanwhile wait.

LISTEN/NOTIFY on ``kb_web_action`` wakes the worker at once; ``poll`` seconds is the fallback.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Callable, Optional

from .db import take_writer_lock
from .levels import GENERATION_COLUMNS, POWERTRAIN_COLUMNS, VARIANT_COLUMNS
from .review import InvalidDecision, parse_value, record_decision

log = logging.getLogger(__name__)

ROLE_RANK = {"lector": 0, "revisor": 1, "editor": 2}
# everything else needs "editor"
REQUIRED_ROLE = {"decide_case": "revisor", "export_specs": "revisor", "import_specs": "revisor"}
SPECS_MAX_BYTES = 700 * 1024                         # an uploaded template (the portal says the same)
SPECS_MAX_LIMIT = 2000                               # rows per sheet in a template prepared from the portal
SPECS_MAX_ERRORS = 200                               # row errors kept on the action
TABLES = {"generation": "kb.generation", "powertrain": "kb.powertrain", "variant": "kb.commercial_variant"}
# Values published from evidence: an edit becomes manual evidence (which always wins).
EVIDENCE_COLUMNS = {"generation": set(GENERATION_COLUMNS), "powertrain": set(POWERTRAIN_COLUMNS),
                    "variant": set(VARIANT_COLUMNS)}
# Identity columns edited in place (marked source = 'manual' where the table has it).
DIRECT_COLUMNS = {
    "generation": {"name", "code", "year_from", "year_to", "status"},
    "powertrain": {"engine_displacement_l", "fuel_type_code", "transmission_type_code", "drivetrain_code", "status"},
    "variant": {"status"},
}
TEXT_COLUMNS = {"name", "code", "engine_code", "engine_name", "tire_size", "country_of_manufacture"}
STATUSES = {"provisional", "verified", "rejected"}
EDIT_RANGES = {"length_mm": (1000, 20000), "width_mm": (500, 3000), "height_mm": (500, 4500),
               "wheelbase_mm": (500, 8000), "torque_nm": (1, 5000), "gears": (1, 12),
               "engine_displacement_l": (0.04, 20), "year_from": (1900, 2100), "year_to": (1900, 2100)}
CATALOG_COLUMNS = {"segment_code": "segment", "fuel_type_code": "fuel_type",
                   "transmission_type_code": "transmission_type", "drivetrain_code": "drivetrain",
                   "headlight_type_code": "headlight_type", "brake_front_code": "brake_type",
                   "brake_rear_code": "brake_type"}
CATALOGS = ("fuel_type", "transmission_type", "drivetrain", "body_style", "segment", "headlight_type",
            "brake_type", "exclusion_reason", "vehicle_class", "country")
NEW_CODES_ALLOWED = ("segment", "headlight_type", "brake_type")     # others are tied to the scraper's rules


class ActionError(ValueError):
    pass


def user_role(cur, email: str) -> Optional[str]:
    cur.execute("SELECT role FROM kb.app_user WHERE email = %s AND active", (str(email).strip().lower(),))
    row = cur.fetchone()
    return row[0] if row else None


def _int(payload: dict, key: str) -> int:
    try:
        return int(payload[key])
    except (KeyError, TypeError, ValueError):
        raise ActionError(f"falta o no es válido: {key}")


def _value(cur, field_name: str, raw):
    """A value typed by a person, checked like the Excel review does."""
    if field_name in TEXT_COLUMNS:
        text = str(raw or "").strip()
        if not text:
            raise ActionError("el valor está vacío")
        return text
    if field_name == "status":
        if raw not in STATUSES:
            raise ActionError(f"estado {raw!r}: usar provisional, verified o rejected")
        return raw
    if field_name in CATALOG_COLUMNS:
        cur.execute(f"SELECT code, name_es, name_en FROM kb.{CATALOG_COLUMNS[field_name]} WHERE active")
        from .identity import compact_key
        wanted = compact_key(raw)
        for code, es, en in cur.fetchall():
            if wanted in (compact_key(code), compact_key(es), compact_key(en)):
                return code
        raise ActionError(f"{raw!r} no está en el catálogo {CATALOG_COLUMNS[field_name]}")
    if field_name in EDIT_RANGES:
        try:
            n = float(str(raw).replace(",", "."))
        except ValueError:
            raise ActionError(f"{raw!r} no es un número")
        lo, hi = EDIT_RANGES[field_name]
        if not lo <= n <= hi:
            raise ActionError(f"{raw} está fuera del rango {lo}-{hi}")
        return round(n, 3) if field_name == "engine_displacement_l" else int(n)
    try:
        return parse_value(cur, field_name, raw)
    except InvalidDecision as e:
        raise ActionError(str(e))


# --- handlers -------------------------------------------------------------------------------
def _decide_case(cur, p: dict, email: str) -> dict:
    try:
        status = record_decision(cur, _int(p, "case_id"), p.get("decision"), p.get("corrected_value"),
                                 p.get("class"), p.get("note"), email)
    except InvalidDecision as e:
        raise ActionError(str(e))
    if status == "already_decided":
        raise ActionError("el caso ya estaba decidido")
    return {"status": status}


def _set_value(cur, p: dict, email: str) -> dict:
    etype, field_name = p.get("entity_type"), p.get("field")
    if etype not in TABLES:
        raise ActionError(f"entidad {etype!r} no válida")
    eid = _int(p, "entity_id")
    cur.execute(f"SELECT 1 FROM {TABLES[etype]} WHERE id = %s", (eid,))
    if not cur.fetchone():
        raise ActionError(f"no existe {etype} {eid}")
    raw = p.get("value")
    if field_name in EVIDENCE_COLUMNS[etype]:
        if raw is None or str(raw).strip() == "":            # clear the manual value
            cur.execute("DELETE FROM kb.spec_evidence WHERE entity_type = %s AND entity_id = %s AND field = %s "
                        "AND source_kind = 'manual'", (etype, eid, field_name))
            return {"cleared": True, "note": "el valor publicado cambia al recalcular"}
        value = _value(cur, field_name, raw)
        cur.execute("""
INSERT INTO kb.spec_evidence (entity_type, entity_id, field, source_kind, value, status, detail)
VALUES (%s, %s, %s, 'manual', %s, 'accepted', %s)
ON CONFLICT (entity_type, entity_id, field, source_kind) DO UPDATE SET value = EXCLUDED.value,
    status = 'accepted', detail = EXCLUDED.detail, updated_at = now()""",
                    (etype, eid, field_name, json.dumps(value),
                     json.dumps({"by": email, "note": p.get("note")})))
        cur.execute(f"UPDATE {TABLES[etype]} SET {field_name} = %s, updated_at = now() WHERE id = %s", (value, eid))
        return {"value": value}
    if field_name in DIRECT_COLUMNS[etype]:
        value = None if raw is None or str(raw).strip() == "" else _value(cur, field_name, raw)
        if value is None and field_name in ("name", "status"):
            raise ActionError("el valor está vacío")
        source = ", source = 'manual'" if etype in ("generation", "powertrain") else ""
        cur.execute(f"UPDATE {TABLES[etype]} SET {field_name} = %s{source}, updated_at = now() WHERE id = %s",
                    (value, eid))
        return {"value": value}
    raise ActionError(f"el campo {field_name!r} no se puede editar en {etype}")


def _split_generation(cur, p: dict, email: str) -> dict:
    from .build import split_generation
    new_id = split_generation(cur, _int(p, "generation_id"), _int(p, "year_from"))
    if new_id is None:
        raise ActionError("la generación no existe o el año no cae dentro de sus años")
    return {"new_generation_id": new_id, "note": "los anuncios se mueven al recalcular"}


def _merge_generations(cur, p: dict, email: str) -> dict:
    src, dst = _int(p, "source_id"), _int(p, "target_id")
    if src == dst:
        raise ActionError("no se puede unir una generación consigo misma")
    cur.execute("SELECT id, model_id, body_style_code, year_from, year_to, status FROM kb.generation "
                "WHERE id = ANY(%s)", ([src, dst],))
    rows = {r[0]: r for r in cur.fetchall()}
    if len(rows) != 2:
        raise ActionError("alguna de las generaciones no existe")
    if rows[src][1:3] != rows[dst][1:3]:
        raise ActionError("solo se unen generaciones del mismo modelo y carrocería")
    if "rejected" in (rows[src][5], rows[dst][5]):
        raise ActionError("una de las generaciones ya está rechazada")
    years_from = [y for y in (rows[src][3], rows[dst][3]) if y is not None]
    ends = (rows[src][4], rows[dst][4])
    cur.execute("UPDATE kb.generation SET year_from = %s, year_to = %s, source = 'manual', updated_at = now() "
                "WHERE id = %s", (min(years_from) if len(years_from) == 2 else None,
                                  None if None in ends else max(ends), dst))
    cur.execute("UPDATE kb.generation SET status = 'rejected', source = 'manual', updated_at = now() WHERE id = %s",
                (src,))
    return {"merged_into": dst, "note": "los anuncios se mueven al recalcular"}


def _add_evolution_note(cur, p: dict, email: str) -> dict:
    vid, field_name = _int(p, "variant_id"), p.get("field")
    if field_name not in EVIDENCE_COLUMNS["variant"]:
        raise ActionError(f"el campo {field_name!r} no es de la variante")
    cur.execute("SELECT 1 FROM kb.commercial_variant WHERE id = %s", (vid,))
    if not cur.fetchone():
        raise ActionError(f"no existe la variante {vid}")
    value = _value(cur, field_name, p.get("value"))
    year = _int(p, "year_from")
    if not 1900 <= year <= 2100:
        raise ActionError(f"{year} no es un año válido")
    cur.execute("""
INSERT INTO kb.evolution_note (variant_id, field, value, year_from, note, source)
VALUES (%s, %s, %s, %s, %s, 'manual')
ON CONFLICT (variant_id, field, year_from) DO UPDATE SET value = EXCLUDED.value, note = EXCLUDED.note
RETURNING id""", (vid, field_name, json.dumps(value), year, p.get("note")))
    return {"evolution_note_id": cur.fetchone()[0]}


def _catalog_upsert(cur, p: dict, email: str) -> dict:
    table = p.get("table")
    if table not in CATALOGS:
        raise ActionError(f"catálogo {table!r} no válido")
    code = str(p.get("code") or "").strip()
    es, en = str(p.get("name_es") or "").strip(), str(p.get("name_en") or "").strip()
    active = bool(p.get("active", True))
    cur.execute(f"SELECT 1 FROM kb.{table} WHERE code = %s", (code,))
    exists = cur.fetchone() is not None
    if not exists:
        if table not in NEW_CODES_ALLOWED:
            raise ActionError(f"en {table} solo se pueden renombrar o desactivar valores")
        pattern = r"^[A-Za-z0-9]+$"
        if not re.fullmatch(pattern, code) or not es or not en:
            raise ActionError("código (letras y números) y nombres en español e inglés son obligatorios")
        if table == "segment":
            cls = p.get("vehicle_class_code")
            if cls not in ("car", "motorcycle"):
                raise ActionError("un segmento necesita su clase: car o motorcycle")
            cur.execute("INSERT INTO kb.segment (code, name_es, name_en, sort_order, active, vehicle_class_code, "
                        "body_style_code) SELECT %s, %s, %s, coalesce(max(sort_order), 0) + 1, %s, %s, %s "
                        "FROM kb.segment", (code, es, en, active, cls, p.get("body_style_code") or None))
        else:
            cur.execute(f"INSERT INTO kb.{table} (code, name_es, name_en, sort_order, active) "
                        f"SELECT %s, %s, %s, coalesce(max(sort_order), 0) + 1, %s FROM kb.{table}",
                        (code, es, en, active))
        return {"created": code}
    sets, args = ["active = %s"], [active]
    if es:
        sets.append("name_es = %s")
        args.append(es)
    if en:
        sets.append("name_en = %s")
        args.append(en)
    cur.execute(f"UPDATE kb.{table} SET {', '.join(sets)} WHERE code = %s", (*args, code))
    return {"updated": code}


def _user_upsert(cur, p: dict, email: str) -> dict:
    target = str(p.get("email") or "").strip().lower()
    role, active = p.get("role"), bool(p.get("active", True))
    if not re.fullmatch(r"[^@\s]+@[^@\s]+", target):
        raise ActionError(f"correo {target!r} no válido")
    if role not in ROLE_RANK:
        raise ActionError("rol: lector, revisor o editor")
    if target == email.strip().lower() and (role != "editor" or not active):
        raise ActionError("no puedes quitarte el rol de editor a ti mismo")
    cur.execute("""
INSERT INTO kb.app_user (email, name, role, active, updated_by) VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (email) DO UPDATE SET name = coalesce(EXCLUDED.name, kb.app_user.name), role = EXCLUDED.role,
    active = EXCLUDED.active, updated_by = EXCLUDED.updated_by, updated_at = now()""",
                (target, p.get("name") or None, role, active, email))
    return {"email": target, "role": role, "active": active}


def _export_specs(cur, p: dict, email: str) -> dict:
    """The capture template (kb/specs.py), returned in the result for the portal to download."""
    from .specs import write_template
    make = str(p.get("make") or "").strip() or None
    country = str(p.get("country") or "").strip().upper() or None
    if country and not re.fullmatch(r"[A-Z]{2}", country):
        raise ActionError(f"país {country!r} no válido")
    limit = _int(p, "limit") if p.get("limit") is not None else 500
    if not 1 <= limit <= SPECS_MAX_LIMIT:
        raise ActionError(f"límite: entre 1 y {SPECS_MAX_LIMIT} filas")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "plantilla.xlsx"
        counts = write_template(cur, path, make=make, country=country, limit=limit)
        data = path.read_bytes()
    name = "plantilla-captura" + "".join(f"-{compact}" for compact in (make, country) if compact) + ".xlsx"
    return {"file_name": re.sub(r"[^A-Za-z0-9._-]", "_", name), "file_b64": base64.b64encode(data).decode(),
            "generations": counts["generations"], "powertrains": counts["powertrains"]}


def _import_specs(cur, p: dict, email: str) -> dict:
    """A filled template uploaded from the portal, saved like `kb specs import` (no rebuild:
    the portal only recalculates from its button)."""
    from .specs import read_template, save_template
    try:
        data = base64.b64decode(str(p.get("file_b64") or ""), validate=True)
    except (binascii.Error, ValueError):
        raise ActionError("el archivo no llegó completo")
    if not data:
        raise ActionError("el archivo está vacío")
    if len(data) > SPECS_MAX_BYTES:
        raise ActionError(f"el archivo pesa más de {SPECS_MAX_BYTES // 1024} KB")
    file_name = Path(str(p.get("file_name") or "plantilla.xlsx")).name[:120]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "plantilla.xlsx"
        path.write_bytes(data)
        try:
            out = save_template(cur, read_template(path), email, file_name)
        except ValueError as e:
            raise ActionError(str(e))
    errors = out["errors"]
    return {"saved": out["saved"], "errors": errors[:SPECS_MAX_ERRORS], "error_count": len(errors),
            "note": "los valores se publican al recalcular"}


HANDLERS: dict[str, Callable] = {
    "decide_case": _decide_case, "set_value": _set_value, "split_generation": _split_generation,
    "merge_generations": _merge_generations, "add_evolution_note": _add_evolution_note,
    "catalog_upsert": _catalog_upsert, "user_upsert": _user_upsert,
    "export_specs": _export_specs, "import_specs": _import_specs,
}


# --- the loop -------------------------------------------------------------------------------
def _finish(cur, action_id: int, status: str, result=None, error: Optional[str] = None) -> None:
    cur.execute("UPDATE kb.web_action SET status = %s, result = %s, error = %s, applied_at = now() WHERE id = %s",
                (status, json.dumps(result, default=str) if result is not None else None, error, action_id))


def _allowed(cur, kind: str, email: str) -> Optional[str]:
    """None when allowed, else the reason."""
    role = user_role(cur, email)
    needed = REQUIRED_ROLE.get(kind, "editor")
    if role is None:
        return f"{email} no tiene acceso al portal"
    if ROLE_RANK[role] < ROLE_RANK[needed]:
        return f"{email} es {role}; esta acción necesita {needed}"
    return None


def process_one(conn) -> Optional[dict]:
    """Apply the oldest queued action. Returns {id, kind, status} or None when the queue is empty."""
    recalc = None
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SELECT id, kind, payload, requested_by FROM kb.web_action WHERE status = 'queued' "
                    "ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED")
        row = cur.fetchone()
        if not row:
            return None
        action_id, kind, payload, email = row
        denied = _allowed(cur, kind, email)
        if denied:
            _finish(cur, action_id, "failed", error=denied)
            return {"id": action_id, "kind": kind, "status": "failed", "error": denied}
        if kind == "recalculate":
            cur.execute("UPDATE kb.web_action SET status = 'running' WHERE id = %s", (action_id,))
            recalc = action_id
        else:
            take_writer_lock(cur)
            try:
                with conn.transaction():
                    result = HANDLERS[kind](cur, payload or {}, email)
                _finish(cur, action_id, "applied", result=result)
                return {"id": action_id, "kind": kind, "status": "applied", "result": result}
            except Exception as e:  # noqa: BLE001 - any error fails only this action, never the queue
                if isinstance(e, ActionError):
                    message = str(e)
                else:                                   # a database constraint or a bug: say so
                    log.exception("action %s (%s) failed", action_id, kind)
                    message = (str(e).splitlines() or [type(e).__name__])[0]
                _finish(cur, action_id, "failed", error=message)
                return {"id": action_id, "kind": kind, "status": "failed", "error": message}
    # recalculate: clean + build, each in its own transaction, outside the claim above
    from .build import build
    from .clean import clean
    try:
        summary = {"clean": clean(conn), "build": build(conn)}
        status, error = "applied", None
    except Exception as e:  # noqa: BLE001 - reported on the action, the worker keeps running
        log.exception("recalculation %s failed", recalc)
        summary, status, error = None, "failed", str(e).splitlines()[0]
    with conn.transaction(), conn.cursor() as cur:
        _finish(cur, recalc, status, result=summary, error=error)
    return {"id": recalc, "kind": "recalculate", "status": status, "error": error}


def drain(conn) -> list[dict]:
    done = []
    while True:
        r = process_one(conn)
        if r is None:
            return done
        log.info("action %s %s: %s %s", r["id"], r["kind"], r["status"], r.get("error") or "")
        done.append(r)


def run_worker(conn, once: bool = False, poll: float = 30.0) -> list[dict]:
    """``conn`` must be in autocommit mode (LISTEN). With ``once``: drain the queue and return."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("UPDATE kb.web_action SET status = 'failed', error = 'el worker se detuvo mientras corría', "
                    "applied_at = now() WHERE status = 'running'")
    conn.execute("LISTEN kb_web_action")
    done = drain(conn)
    if once:
        return done
    log.info("worker listening on kb_web_action (poll every %ss)", poll)
    while True:
        for _ in conn.notifies(timeout=poll, stop_after=1):
            pass
        done = drain(conn)
