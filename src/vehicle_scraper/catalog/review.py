"""Human review loop for the catalog: export open review items, import decisions.

    catalog review --export data/catalog_review.xlsx     # open it in Excel, fill `decision`
    catalog review --import data/catalog_review.xlsx     # applies approve / reject / correct

decision: approve  -> apply the stored proposal (method "human")
          reject   -> close the item, nothing applied
          correct  -> apply `correction` instead. Short forms, by reason:
                        ai_knowledge_body   SUV                      (a body style)
                        ai_model            merge: Cerato | rename: Cerato Forte | keep
                        ai_trim             Attraction               (the trim name)
                        spec_conflict       drivetrain=AWD, doors=4  (stored as a human override)
                      A JSON object with the same shape as `proposal` still works.
Rows with an empty decision stay open; rows that fail are reported and stay open too.
A .csv (UTF-8) works too in both directions.
"""
from __future__ import annotations

import copy
import csv
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args
from xml.etree import ElementTree as ET

from sqlalchemy import Float, Integer, select, update
from sqlalchemy.engine import Connection, Engine

from ..models import Drivetrain, VehicleType
from ..xlsx import write_xlsx
from . import schema as S
from .canonical import key, model_key
from .validate import apply_proposal

APPROVE = ("approve", "approved", "aprobar", "si", "sí", "yes")
REJECT = ("reject", "rejected", "rechazar", "no")
CORRECT = ("correct", "corrected", "corregir")
ENUMS = {"body_style": get_args(VehicleType), "drivetrain": get_args(Drivetrain)}
MODEL_ACTIONS = {"merge": "merge", "unir": "merge", "rename": "rename", "renombrar": "rename",
                 "keep": "keep", "mantener": "keep"}

COLUMNS = ["id", "entity_type", "entity_key", "reason", "detail", "proposal", "decision", "correction"]


def export_review(engine: Engine, path: Path) -> int:
    with engine.connect() as conn:
        rows = conn.execute(select(S.review_item).where(S.review_item.c.status == "open")
                            .order_by(S.review_item.c.reason, S.review_item.c.entity_key)).mappings().all()
    data = [[r["id"], r["entity_type"], r["entity_key"], r["reason"], r["detail"],
             json.dumps(r["proposal"], ensure_ascii=False) if r["proposal"] is not None else "", "", ""] for r in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            w.writerows(data)
    else:
        write_xlsx(path, COLUMNS, data, sheet_name="review")
    return len(data)


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(path: Path) -> list[dict]:
    """First sheet as dicts (header row = keys). Handles shared and inline strings, which covers
    files written by xlsx.py and files saved again by Excel / LibreOffice."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        sheet = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))[0]
        root = ET.fromstring(z.read(sheet))
    table = []
    for row in root.iter(f"{{{_NS['m']}}}row"):
        cells: dict[int, str] = {}
        for c in row.findall("m:c", _NS):
            t, v = c.get("t"), c.find("m:v", _NS)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{_NS['m']}}}t"))
            else:
                val = v.text if v is not None else ""
            cells[_col_index(c.get("r"))] = val or ""
        if cells:
            table.append([cells.get(i, "") for i in range(max(cells) + 1)])
    if not table:
        return []
    header = [h.strip() for h in table[0]]
    return [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in table[1:]]


def _read(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    return read_xlsx(path)


def import_review(engine: Engine, path: Path, reviewer: str = "human") -> dict:
    counts = {"approved": 0, "rejected": 0, "corrected": 0, "open": 0, "errors": []}
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        for r in _read(path):
            decision = (r.get("decision") or "").strip().lower()
            if not decision or not str(r.get("id", "")).strip():
                counts["open"] += 1
                continue
            item_id = int(float(r["id"]))
            item = conn.execute(select(S.review_item).where(S.review_item.c.id == item_id)).mappings().first()
            if item is None or item["status"] != "open":
                continue
            try:
                with conn.begin_nested():         # a failing row leaves nothing half-applied
                    if decision in APPROVE:
                        _approve(conn, item)
                        status = "approved"
                    elif decision in REJECT:
                        status = "rejected"
                    elif decision in CORRECT:
                        _correct(conn, item, (r.get("correction") or "").strip(), reviewer, now)
                        status = "corrected"
                    else:
                        raise ValueError(f"unknown decision {decision!r} (approve / reject / correct)")
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                counts["errors"].append(f"item {item_id} ({item['entity_key']}): {e}")
                continue
            conn.execute(update(S.review_item).where(S.review_item.c.id == item_id).values(
                status=status, decided_by=reviewer, decided_at=now))
            counts[status] += 1
    return counts


def _approve(conn: Connection, item) -> None:
    p = item["proposal"]
    if not p:
        return
    if p["kind"] == "model" and p["answer"].get("action") == "not_a_model":
        raise ValueError("the AI says this is not a model, so approving changes nothing. Use decision=correct "
                         "with 'merge: <existing model>' or 'rename: <name>', or reject it to keep it as is")
    apply_proposal(conn, p, method="human")


def _correct(conn: Connection, item, text: str, reviewer: str, now: datetime) -> None:
    if not text:
        raise ValueError("decision=correct needs a value in the `correction` column")
    p = item["proposal"] or {}
    if text.startswith("{"):
        proposal = json.loads(text)
        if proposal.get("kind") == "variant_values":
            _override_variant(conn, item["entity_key"], proposal.get("values") or {}, reviewer, now)
        else:
            apply_proposal(conn, proposal, method="human")
        return
    kind = p.get("kind")
    if kind == "model_body":
        apply_proposal(conn, p | {"body_style": _enum("body_style", text), "source": "human"}, method="human")
    elif kind == "model":
        apply_proposal(conn, _model_correction(conn, p, text), method="human")
    elif kind == "trim":
        proposal = copy.deepcopy(p)
        proposal["answer"]["trim_name"] = text
        apply_proposal(conn, proposal, method="human")
    elif kind == "variant_values":
        _override_variant(conn, item["entity_key"], _parse_values(text), reviewer, now)
    elif kind == "make":
        raise ValueError("makes are corrected in config/catalog/makes.yaml (add it, or add it as an alias)")
    else:
        raise ValueError(f"no short correction for {kind!r}: paste a JSON proposal instead")


def _model_correction(conn: Connection, p: dict, text: str) -> dict:
    verb, _, arg = text.partition(":")
    action = MODEL_ACTIONS.get(verb.strip().lower())
    arg = arg.strip()
    if action is None or (action != "keep" and not arg):
        raise ValueError("model corrections are 'merge: <existing model>', 'rename: <name>' or 'keep'")
    proposal = copy.deepcopy(p)
    a = proposal["answer"]
    a["action"] = action
    if action == "rename":
        a["canonical_name"] = arg
    elif action == "keep":                       # keep the name the catalog shows today, and lock it
        a["canonical_name"] = conn.execute(
            select(S.model.c.name).join(S.make, S.make.c.id == S.model.c.make_id)
            .where(S.make.c.slug == p["make_slug"], S.model.c.match_key == p["match_key"])).scalar() \
            or a["canonical_name"]
    else:
        target = _find_model(conn, p["make_slug"], arg)
        if target == p["match_key"]:
            raise ValueError(f"'{arg}' is this same model")
        proposal["model_ids"] = dict(proposal["model_ids"], _target=target)
        a["merge_into"] = "_target"
    return proposal


def _find_model(conn: Connection, make_slug: str, name: str) -> str:
    rows = conn.execute(select(S.model.c.match_key, S.model.c.name).join(S.make, S.make.c.id == S.model.c.make_id)
                        .where(S.make.c.slug == make_slug)).all()
    for wanted in (model_key(name), key(name)):
        for mkey, mname in rows:
            if wanted in (mkey, key(mname)):
                return mkey
    raise ValueError(f"no model '{name}' for make '{make_slug}' (use 'rename: {name}' to keep it under a new name)")


def _enum(field: str, text: str) -> str:
    allowed = ENUMS[field]
    match = next((v for v in allowed if v.lower() == text.strip().lower()), None)
    if match is None:
        raise ValueError(f"{field} must be one of {', '.join(allowed)} (got {text!r})")
    return match


def _parse_values(text: str) -> dict:
    out = {}
    for part in re.split(r"[;,]\s*", text):
        if part.strip():
            f, sep, v = part.partition("=")
            if not sep:
                raise ValueError(f"expected field=value, got {part!r}")
            out[f.strip()] = v.strip()
    return out


def _spec_value(field: str, value):
    if field not in S.SPEC_COLUMNS:
        raise ValueError(f"'{field}' can't be overridden; allowed: {', '.join(S.SPEC_COLUMNS)}")
    if field in ENUMS:
        return _enum(field, str(value))
    type_ = S.SPEC_COLUMNS[field]
    try:
        if isinstance(type_, Integer):
            return int(float(str(value).replace(",", ".")))
        if isinstance(type_, Float):
            return float(str(value).replace(",", "."))
    except ValueError:
        raise ValueError(f"{field} must be a number (got {value!r})") from None
    return str(value).strip()


def _override_variant(conn: Connection, entity_key: str, values: dict, reviewer: str, now: datetime) -> None:
    """Store a person's spec values for the variant named by a spec_conflict item's entity_key
    ("make/model/trim/year|fuel|gearbox|engine", trim "_" when the listings state none)."""
    if not values:
        raise ValueError("no field=value pairs to apply")
    parts = entity_key.split("/", 3)
    if len(parts) != 4:
        raise ValueError(f"not a variant key: {entity_key!r}")
    make_slug, mkey, tkey, vk = parts
    vid = conn.execute(
        select(S.variant.c.id).join(S.trim, S.trim.c.id == S.variant.c.trim_id)
        .join(S.model, S.model.c.id == S.trim.c.model_id).join(S.make, S.make.c.id == S.model.c.make_id)
        .where(S.make.c.slug == make_slug, S.model.c.match_key == mkey,
               S.trim.c.match_key == ("" if tkey == "_" else tkey), S.variant.c.variant_key == vk)).scalar()
    if vid is None:
        raise ValueError("the variant no longer exists (rebuild the catalog and export the queue again)")
    clean = {f.strip(): _spec_value(f.strip(), v) for f, v in values.items()}
    for f, v in clean.items():
        conn.execute(S.variant_override.delete().where(S.variant_override.c.variant_id == vid,
                                                       S.variant_override.c.field == f))
        conn.execute(S.variant_override.insert().values(variant_id=vid, field=f, value=v,
                                                        decided_by=reviewer, decided_at=now))
    conn.execute(update(S.variant).where(S.variant.c.id == vid).values(**clean))
