"""Stage 4: validate AI answers with rules (no tokens), then apply or queue for human review.

Accepted automatically only when the answer is confident (>= 0.7), consistent with the
listings' evidence and free of spec words in names. Everything else becomes a review_item with
the full proposal, so a person can approve it later (review.py) and it is applied the same way.
Values the model took from its own knowledge (body_source = "ai_knowledge") always go to review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, ValidationError
from sqlalchemy import and_, insert, select, update
from sqlalchemy.engine import Connection

from ..models import Drivetrain, FuelType, TransmissionType, VehicleType
from . import schema as S
from .canonical import key, slugify, title_attrs

MIN_CONFIDENCE = 0.7
MERGE_CONFIDENCE = 0.85
NAME_SPEC_FIELDS = ("engine_displacement_l", "transmission_type", "drivetrain", "fuel_type")
TRIM_ATTRS = ("engine_displacement_l", "transmission_type", "fuel_type", "drivetrain", "body_style", "doors")
_EVIDENCE = {"engine_displacement_l": "cc", "fuel_type": "fuel", "transmission_type": "gear",
             "body_style": "body", "drivetrain": "drive"}


class ModelAnswer(BaseModel):
    id: str
    action: Literal["keep", "rename", "merge", "not_a_model"]
    canonical_name: str
    merge_into: Optional[str] = None
    vehicle_class: Literal["car", "moto", "heavy"]
    body_style: Optional[VehicleType] = None
    body_source: Optional[Literal["title", "ai_knowledge"]] = None
    confidence: float
    note: str = ""


class TrimAnswer(BaseModel):
    id: str
    model_id: str
    trim_name: str
    engine_displacement_l: Optional[float] = None
    transmission_type: Optional[TransmissionType] = None
    fuel_type: Optional[FuelType] = None
    drivetrain: Optional[Drivetrain] = None
    body_style: Optional[VehicleType] = None
    doors: Optional[int] = None
    confidence: float
    note: str = ""


@dataclass
class Decision:
    local_id: str
    kind: str                                  # model | trim
    item: dict                                 # the ai_decision row (request etc.)
    answer: dict
    status: str = "accepted"                   # accepted | review | rejected
    reasons: list = field(default_factory=list)
    reviews: list = field(default_factory=list)   # (reason, detail, proposal) to queue


def _missing(v) -> bool:
    return v is None or v == "-" or v == ""


def _check_model(a: ModelAnswer, item: dict) -> Decision:
    req = item["request"]
    d = Decision(a.id, "model", item, a.model_dump())
    ids = req.get("model_ids") or {}
    name = a.canonical_name.strip()
    if not name:
        d.status, d.reasons = "rejected", ["empty canonical_name"]
        return d
    review = []
    if a.confidence < MIN_CONFIDENCE:
        review.append(f"low confidence {a.confidence:.2f}")
    if a.action == "not_a_model":
        review.append("AI says this is not a model name")
    if a.action == "merge":
        if a.merge_into not in ids or a.merge_into == a.id:
            d.status, d.reasons = "rejected", [f"merge_into {a.merge_into!r} is not another model of this request"]
            return d
        if a.confidence < MERGE_CONFIDENCE:
            review.append(f"merge below {MERGE_CONFIDENCE} confidence")
    if any(f in title_attrs(name) for f in NAME_SPEC_FIELDS):
        review.append(f"canonical name '{name}' still contains spec words")
    if a.vehicle_class != req["line"].get("class"):
        review.append(f"class change {req['line'].get('class')} -> {a.vehicle_class}")
    listing_body = req["line"].get("body")
    if a.body_style and a.body_source == "title" and not _missing(listing_body) and listing_body != a.body_style:
        review.append(f"body {a.body_style} contradicts listings ({listing_body})")
    if a.body_style and a.body_source == "ai_knowledge" and _missing(listing_body) and a.vehicle_class == "car":
        d.reviews.append(("ai_knowledge_body", f"AI knowledge: {a.body_style}. {a.note}".strip(),
                          {"kind": "model_body", "make_slug": req["make_slug"], "match_key": req["match_key"],
                           "body_style": a.body_style, "source": "ai_knowledge"}))
    if review:
        d.status, d.reasons = "review", review
        d.reviews.append(("ai_model", "; ".join(review) + (f". Note: {a.note}" if a.note else ""),
                          {"kind": "model", "make_slug": req["make_slug"], "match_key": req["match_key"],
                           "model_ids": ids, "answer": d.answer}))
    return d


def _check_trim(a: TrimAnswer, item: dict) -> Decision:
    req = item["request"]
    d = Decision(a.id, "trim", item, a.model_dump())
    ids = req.get("model_ids") or {}
    if a.model_id not in ids:
        d.status, d.reasons = "rejected", [f"model_id {a.model_id!r} is not a model of this request"]
        return d
    review, line = [], req["line"]
    if a.model_id != line.get("model"):
        review.append(f"moves the string to model {a.model_id} ({ids[a.model_id]})")
    if any(f in title_attrs(a.trim_name) for f in NAME_SPEC_FIELDS):
        review.append(f"trim name '{a.trim_name}' still contains spec words")
    if a.confidence < MIN_CONFIDENCE:
        review.append(f"low confidence {a.confidence:.2f}")
    attrs = {f: getattr(a, f) for f in TRIM_ATTRS if getattr(a, f) is not None}
    if "engine_displacement_l" in attrs and not 0.05 <= attrs["engine_displacement_l"] <= 10:
        attrs.pop("engine_displacement_l")
    if "doors" in attrs and not 2 <= attrs["doors"] <= 6:
        attrs.pop("doors")
    for f, col in _EVIDENCE.items():                       # listing evidence wins over the text
        ev = line.get(col)
        if f in attrs and not _missing(ev):
            same = abs(float(ev) - attrs[f]) <= 0.1 if f == "engine_displacement_l" else str(ev) == str(attrs[f])
            if not same:
                review.append(f"{f}={attrs[f]} contradicts listings ({ev})")
                attrs.pop(f)
    d.answer["attrs"] = attrs
    if review:
        d.status, d.reasons = "review", review
        d.reviews.append(("ai_trim", "; ".join(review) + (f". Note: {a.note}" if a.note else ""),
                          {"kind": "trim", "make_slug": req["make_slug"], "model_ids": ids,
                           "alias_norm": req["alias_norm"], "raw_model": req.get("raw_model"),
                           "raw_trim": req.get("raw_trim"), "answer": d.answer}))
    return d


def validate_answer(answer: dict, items: dict[str, dict]) -> list[Decision]:
    """``items``: local_id -> pending ai_decision row of the request this answer belongs to."""
    out = []
    for kind, model_cls, check in (("model", ModelAnswer, _check_model), ("trim", TrimAnswer, _check_trim)):
        for raw in answer.get(f"{kind}s") or []:
            item = items.get(str(raw.get("id")))
            if item is None or item["item_kind"] != kind:
                continue                                 # an id we didn't ask about: ignore it
            try:
                a = model_cls.model_validate(raw)
            except ValidationError as e:
                out.append(Decision(str(raw.get("id")), kind, item, raw, "rejected", [f"invalid: {e.errors()[0]['msg']}"]))
                continue
            out.append(check(a, item))
    return out


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------
def _ids(conn: Connection, make_slug: str, match_key: Optional[str] = None):
    make_id = conn.execute(select(S.make.c.id).where(S.make.c.slug == make_slug)).scalar()
    if match_key is None or make_id is None:
        return make_id, None
    model_id = conn.execute(select(S.model.c.id).where(S.model.c.make_id == make_id,
                                                        S.model.c.match_key == match_key)).scalar()
    return make_id, model_id


def _put(conn: Connection, table, natural: dict, values: dict) -> None:
    cond = and_(*[table.c[k] == v for k, v in natural.items()])
    if conn.execute(select(table).where(cond)).first():
        conn.execute(update(table).where(cond).values(**values))
    else:
        conn.execute(insert(table).values(**natural, **values))


def apply_model(conn: Connection, make_slug: str, match_key: str, model_ids: dict, a: dict, method: str) -> None:
    make_id, model_id = _ids(conn, make_slug, match_key)
    if model_id is None:
        return                                           # the model disappeared since prepare: nothing to do
    conf = a.get("confidence")
    if a["action"] == "merge":
        _, target = _ids(conn, make_slug, model_ids[a["merge_into"]])
        if target is not None:
            _put(conn, S.model_alias, {"make_id": make_id, "alias_norm": match_key},
                 {"model_id": target, "method": method, "confidence": conf})
            conn.execute(update(S.model).where(S.model.c.id == target).values(verified=True))
        return
    if a["action"] == "not_a_model":
        return
    name = a["canonical_name"].strip()
    values = {"name": name, "slug": slugify(name), "name_locked": True, "verified": True}
    if a.get("body_style") and a.get("body_source") == "title":
        values |= {"default_body_style": a["body_style"], "default_body_source": "title"}
    conn.execute(update(S.model).where(S.model.c.id == model_id).values(**values))


def apply_model_body(conn: Connection, make_slug: str, match_key: str, body: str, source: str) -> None:
    _, model_id = _ids(conn, make_slug, match_key)
    if model_id is not None:
        conn.execute(update(S.model).where(S.model.c.id == model_id).values(
            default_body_style=body, default_body_source=source))


def apply_trim(conn: Connection, make_slug: str, model_ids: dict, alias_norm: str, a: dict, method: str) -> None:
    make_id, model_id = _ids(conn, make_slug, model_ids[a["model_id"]])
    if model_id is None:
        return
    merged = conn.execute(select(S.model_alias.c.model_id).where(        # model merged meanwhile: follow it
        S.model_alias.c.make_id == make_id, S.model_alias.c.alias_norm == model_ids[a["model_id"]])).scalar()
    model_id = merged or model_id
    name = a["trim_name"].strip()
    tkey = key(name)
    trim_id = conn.execute(select(S.trim.c.id).where(S.trim.c.model_id == model_id,
                                                      S.trim.c.match_key == tkey)).scalar()
    if trim_id is None:
        trim_id = conn.execute(insert(S.trim).values(
            model_id=model_id, name=name, slug=slugify(name) if name else "_none", match_key=tkey,
            name_locked=True, created_by=method)).inserted_primary_key[0]
    else:
        conn.execute(update(S.trim).where(S.trim.c.id == trim_id).values(
            name=name, slug=slugify(name) if name else "_none", name_locked=True))
    _put(conn, S.trim_alias, {"model_id": model_id, "alias_norm": alias_norm},
         {"trim_id": trim_id, "attrs": a.get("attrs") or {}, "method": method, "confidence": a.get("confidence")})


def apply_proposal(conn: Connection, proposal: dict, method: str = "human") -> None:
    """Apply a review item's proposal (as stored, or as corrected by a person)."""
    kind = proposal["kind"]
    if kind == "model":
        apply_model(conn, proposal["make_slug"], proposal["match_key"], proposal["model_ids"], proposal["answer"], method)
    elif kind == "model_body":
        apply_model_body(conn, proposal["make_slug"], proposal["match_key"], proposal["body_style"],
                         proposal.get("source", "human"))
    elif kind == "trim":
        apply_trim(conn, proposal["make_slug"], proposal["model_ids"], proposal["alias_norm"], proposal["answer"], method)
    elif kind in ("variant_values", "make"):
        # Spec conflicts: the consensus value is already used, approving closes the item.
        # Unknown make: approving accepts the name as is (add it to makes.yaml to give it aliases).
        pass
    else:
        raise ValueError(f"unknown proposal kind {kind!r}")


def apply_decision(conn: Connection, d: Decision, method: str = "ai") -> None:
    req = d.item["request"]
    conn.execute(update(S.ai_decision).where(S.ai_decision.c.input_hash == d.item["input_hash"]).values(
        status=d.status, response=d.answer, notes="; ".join(d.reasons) or None))
    if d.status == "accepted":
        if d.kind == "model":
            apply_model(conn, req["make_slug"], req["match_key"], req["model_ids"], d.answer, method)
        else:
            apply_trim(conn, req["make_slug"], req["model_ids"], req["alias_norm"], d.answer, method)
    for reason, detail, proposal in d.reviews:
        entity = "/".join([req["make_slug"], req.get("match_key") or req.get("alias_norm", "")])
        _put(conn, S.review_item, {"entity_type": "model" if d.kind == "model" else "trim",
                                   "entity_key": entity[:300], "reason": reason},
             {"detail": detail, "proposal": proposal, "status": "open"})
