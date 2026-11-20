"""Human review: `kb review export` -> fill the CSV in Excel -> `kb review import`.

Policy (decided):
* Individual: identity changes (unknown make, merging different models, "not a real model",
  wrong make, year outside production), cross-check flags, and CRITICAL fields that come from
  the AI without listing consensus.
* Sampled: the rest of each AI batch. A stratified random sample (fixed seed) is reviewed; if
  it reaches ``min_accuracy`` the batch's values with confidence >= ``min_confidence`` become
  ``accepted_sampled``; otherwise the whole batch is rejected (fix the prompt and re-run).

Decisions in the CSV: ``approve`` (the proposal / flagged value is right), ``reject`` (it is
wrong) or ``correct`` (wrong; ``corrected_value`` holds the right one). Nothing is applied
until import, and every decision keeps the reviewer's name.
"""
from __future__ import annotations

import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from .. import mapping as M
from .db import compact_key, jsonb
from .fields import EQUIP_FIELDS, MECH_FIELDS, coerce
from .identity import merge_make, merge_model, merge_trim, split_trim

COLUMNS = ["item_id", "level", "kind", "batch_id", "entity_type", "entity_id", "entity", "country", "field",
           "issue", "current", "proposed", "evidence", "listings_affected", "decision", "corrected_value", "note"]
DECISIONS = {"approve": "approved", "approved": "approved", "ok": "approved", "si": "approved", "sí": "approved",
             "reject": "rejected", "rejected": "rejected", "no": "rejected",
             "correct": "corrected", "corrected": "corrected", "corregir": "corrected"}


# --- sampling --------------------------------------------------------------------------------
def create_sample_batches(conn, sample_size: int, seed: int, min_accuracy: float, min_confidence: float) -> int:
    """One review_batch per applied AI run that doesn't have one yet."""
    created = 0
    for run in conn.execute("SELECT * FROM kb.ai_run WHERE status = 'applied' AND NOT EXISTS "
                            "(SELECT 1 FROM kb.review_batch b WHERE b.ai_run_id = kb.ai_run.id) ORDER BY id").fetchall():
        batch = conn.execute(
            """INSERT INTO kb.review_batch (ai_run_id, scope, seed, sample_size, threshold, min_confidence)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (run["id"], run["kind"], seed, sample_size, min_accuracy, min_confidence)).fetchone()["id"]
        rng = random.Random(f"{seed}:{run['id']}")
        if run["kind"] == "specs":
            pool = conn.execute(
                """SELECT e.id, e.variant_id, e.country, e.field, e.value, e.confidence, e.ai_decision_id
                   FROM kb.spec_evidence e JOIN kb.ai_decision d ON d.id = e.ai_decision_id
                   WHERE d.ai_run_id = %s AND e.source_kind = 'ai_knowledge' AND e.status = 'pending_review'
                     AND e.confidence >= %s
                     AND NOT EXISTS (SELECT 1 FROM kb.review_item r WHERE r.evidence_id = e.id AND r.kind = 'individual')
                   ORDER BY e.id""", (run["id"], min_confidence)).fetchall()
            by_field: dict[str, list] = defaultdict(list)
            for e in pool:
                by_field[e["field"]].append(e)
            for items in by_field.values():
                rng.shuffle(items)
            sample, fields = [], sorted(by_field)
            while len(sample) < sample_size and any(by_field[f] for f in fields):   # round-robin = stratified
                for f in fields:
                    if by_field[f] and len(sample) < sample_size:
                        sample.append(by_field[f].pop())
            conn.execute("UPDATE kb.spec_evidence SET review_batch_id = %s WHERE id = ANY(%s)",
                         (batch, [e["id"] for e in pool]))
            for e in sample:
                conn.execute(
                    """INSERT INTO kb.review_item (level, entity_type, entity_id, country, field, issue, proposed,
                                                   source, kind, review_batch_id, evidence_id, ai_decision_id)
                       VALUES (%s, 'spec', %s, %s, %s, 'ai_value_sample', %s, 'ai', 'sample', %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (5 if e["country"] == "" else 6, e["variant_id"], e["country"], e["field"],
                     jsonb({"value": e["value"], "confidence": e["confidence"]}), batch, e["id"], e["ai_decision_id"]))
        else:
            pool = conn.execute(
                """SELECT r.id FROM kb.review_item r JOIN kb.ai_decision d ON d.id = r.ai_decision_id
                   WHERE d.ai_run_id = %s AND r.kind = 'sample' AND r.status = 'pending' ORDER BY r.id""",
                (run["id"],)).fetchall()
            ids = [r["id"] for r in pool]
            rng.shuffle(ids)
            conn.execute("UPDATE kb.review_item SET review_batch_id = %s WHERE id = ANY(%s)", (batch, ids))
            conn.execute("UPDATE kb.review_item SET note = 'IN SAMPLE' WHERE id = ANY(%s)", (ids[:sample_size],))
        created += 1
    return created


# --- export ------------------------------------------------------------------------------------
# The open queue, in review order: by level, individual before sampled, most listings first.
# The review website (src/web) lists the same rows in the same order.
QUEUE_SQL = """SELECT * FROM kb.review_queue WHERE status = 'pending' AND in_queue
               ORDER BY level, (kind = 'sample'), listings_affected DESC, id"""


def export_review(conn, out: Path, sample_size: int = 50, seed: int = 20261120, min_accuracy: float = 0.95,
                  min_confidence: float = 0.8, limit: Optional[int] = None) -> int:
    create_sample_batches(conn, sample_size, seed, min_accuracy, min_confidence)
    rows = conn.execute(QUEUE_SQL).fetchall()
    if limit:
        rows = rows[:limit]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as f:      # BOM: Excel reads accents
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({"item_id": r["id"], "level": r["level"], "kind": r["kind"], "batch_id": r["review_batch_id"] or "",
                        "entity_type": r["entity_type"], "entity_id": r["entity_id"],
                        "entity": r["entity_label"] or "?", "country": r["country"],
                        "field": r["field"], "issue": r["issue"],
                        "current": json.dumps(r["current"], ensure_ascii=False) if r["current"] is not None else "",
                        "proposed": json.dumps(r["proposed"], ensure_ascii=False) if r["proposed"] is not None else "",
                        "evidence": json.dumps(r["evidence"], ensure_ascii=False) if r["evidence"] is not None else "",
                        "listings_affected": r["listings_affected"], "decision": "", "corrected_value": "", "note": ""})
    return len(rows)


# --- import ------------------------------------------------------------------------------------
def import_review(conn, path: Path, reviewer: str) -> dict:
    stats = Counter()
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        decision = DECISIONS.get((row.get("decision") or "").strip().lower())
        if not decision:
            stats["blank"] += 1
            continue
        stats[decide_item(conn, int(row["item_id"]), decision, row.get("corrected_value"), row.get("note"),
                          reviewer)] += 1
    stats.update(close_sample_batches(conn, reviewer))
    return dict(stats)


class InvalidValue(ValueError):
    """A reviewer's value that doesn't parse or is out of range for its field."""


def decide_item(conn, item_id: int, decision: str, corrected: Optional[str], note: Optional[str],
                reviewer: str) -> str:
    """Record and apply one decision ('approved' | 'rejected' | 'corrected') on a pending case.
    The only path that applies decisions: `kb review import` and the review worker both use it.
    Returns the outcome: the decision itself when applied, or 'already_decided_or_missing',
    'correct_without_value', 'invalid_value' (nothing changes in those cases)."""
    item = conn.execute("SELECT * FROM kb.review_item WHERE id = %s AND status = 'pending' FOR UPDATE",
                        (item_id,)).fetchone()
    if not item:
        return "already_decided_or_missing"
    corrected = (corrected or "").strip() or None
    if decision == "corrected" and corrected is None:
        return "correct_without_value"
    try:
        with conn.transaction():        # savepoint: an invalid value leaves the case untouched
            conn.execute("""UPDATE kb.review_item SET status = %s, reviewer = %s, decided_at = now(),
                            corrected_value = %s, note = NULLIF(%s, '') WHERE id = %s""",
                         (decision, reviewer, jsonb(corrected) if corrected else None, (note or "").strip(),
                          item["id"]))
            apply_decision(conn, item, decision, corrected, reviewer)
    except InvalidValue:
        return "invalid_value"
    return decision


def _manual(conn, variant_id: int, country: str, f: str, value, item_id: int, vehicle_class: str = "car") -> None:
    """A person's value -> 'manual' evidence (top precedence). Parsed with the scraper's
    own converters so units ("65 L", "17 in") work the same way. Raises InvalidValue when
    the value doesn't fit the field, so a bad correction is reported, never silently lost."""
    if isinstance(value, str):
        conv = (vehicle_class == "motorcycle" and M.MOTO_CONVERTERS.get(f)) or M.CONVERTERS.get(f)
        value = conv(value, f) if conv else value
    parsed = coerce(f, value)
    if parsed is None:
        raise InvalidValue(f"{f}: {value!r}")
    value = parsed
    cc = "" if f in MECH_FIELDS else country
    conn.execute(
        """INSERT INTO kb.spec_evidence (variant_id, country, field, value, source_kind, support_count, confidence,
                                         status, origin_key)
           VALUES (%s, %s, %s, %s, 'manual', 0, 1.0, 'accepted', %s)
           ON CONFLICT (variant_id, country, field, source_kind, origin_key) DO UPDATE SET value = EXCLUDED.value""",
        (variant_id, cc, f, jsonb(value), f"review:{item_id}"))
    # an older human value for the same cell is superseded by this decision
    conn.execute("""UPDATE kb.spec_evidence SET status = 'rejected' WHERE variant_id = %s AND country = %s AND field = %s
                    AND source_kind = 'manual' AND origin_key <> %s""", (variant_id, cc, f, f"review:{item_id}"))


def _class_of_variant(conn, vid: int) -> str:
    r = conn.execute("SELECT md.vehicle_class FROM kb.variant v JOIN kb.model md ON md.id = v.model_id WHERE v.id = %s",
                     (vid,)).fetchone()
    return (r and r["vehicle_class"]) or "car"


def _find_make(conn, name: str) -> Optional[int]:
    r = conn.execute("SELECT make_id FROM kb.make_alias WHERE alias_key = %s", (compact_key(name),)).fetchone()
    return r["make_id"] if r else None


def apply_decision(conn, item: dict, decision: str, corrected: Optional[str], reviewer: str,
                   verified_by: str = "human") -> None:
    et, eid, issue, f, cc = item["entity_type"], item["entity_id"], item["issue"], item["field"], item["country"]
    prop = item["proposed"] or {}

    if et == "make":
        if decision == "rejected" or (decision == "approved" and prop.get("is_vehicle_make") is False):
            conn.execute("UPDATE kb.make SET status = 'rejected', verified_by = %s WHERE id = %s", (verified_by, eid))
            return
        name = corrected or prop.get("canonical_name")
        target = _find_make(conn, corrected) if corrected else (_find_make(conn, prop["same_as_known_make"])
                                                                if prop.get("same_as_known_make") else None)
        if target and target != eid:
            merge_make(conn, eid, target, f"review {item['id']} by {reviewer}")
            return
        conn.execute("UPDATE kb.make SET name = COALESCE(%s, name), status = 'accepted', verified_by = %s, "
                     "updated_at = now() WHERE id = %s", (name, verified_by, eid))
        return

    if et == "model":
        if decision == "rejected" or (decision == "approved" and prop.get("is_real_model") is False):
            conn.execute("UPDATE kb.model SET status = 'rejected', verified_by = %s WHERE id = %s", (verified_by, eid))
            return
        model = conn.execute("SELECT * FROM kb.model WHERE id = %s", (eid,)).fetchone()
        if corrected and corrected.lower().startswith("merge:"):
            target = conn.execute("SELECT id FROM kb.model m JOIN kb.model_alias a ON a.model_id = m.id "
                                  "WHERE a.make_id = %s AND a.alias_key = %s", (model["make_id"], compact_key(corrected[6:])))
            t = target.fetchone()
            if t:
                merge_model(conn, eid, t["id"], f"review {item['id']} by {reviewer}")
                conn.execute("UPDATE kb.model SET status = 'accepted', verified_by = %s WHERE id = %s AND status = 'unresolved'",
                             (verified_by, t["id"]))
            return
        if decision == "approved" and prop.get("wrong_make"):
            mk = _find_make(conn, prop["wrong_make"])
            if mk:
                conn.execute("UPDATE kb.model SET make_id = %s WHERE id = %s", (mk, eid))
                conn.execute("UPDATE kb.listing SET make_id = %s WHERE model_id = %s", (mk, eid))
        if decision == "approved" and prop.get("merge_into_id") and prop["merge_into_id"] != eid:
            if conn.execute("SELECT 1 FROM kb.model WHERE id = %s", (prop["merge_into_id"],)).fetchone():
                merge_model(conn, eid, prop["merge_into_id"], f"review {item['id']} by {reviewer}")
                conn.execute("UPDATE kb.model SET status = 'accepted', verified_by = %s WHERE id = %s AND status = 'unresolved'",
                             (verified_by, prop["merge_into_id"]))
                return
        name = corrected or prop.get("canonical_name")
        conn.execute(
            """UPDATE kb.model SET name = COALESCE(%s, name), vehicle_class = COALESCE(%s, vehicle_class),
                   year_from = COALESCE(%s, year_from), year_to = COALESCE(%s, year_to),
                   status = 'accepted', verified_by = %s, updated_at = now() WHERE id = %s""",
            (name, prop.get("vehicle_class") if decision == "approved" else None,
             prop.get("year_from") if decision == "approved" else None,
             prop.get("year_to") if decision == "approved" else None, verified_by, eid))
        if name:
            conn.execute("INSERT INTO kb.model_alias (make_id, alias_key, model_id, source) VALUES (%s, %s, %s, %s) "
                         "ON CONFLICT DO NOTHING", (model["make_id"], compact_key(name), eid,
                                                    "manual" if verified_by == "human" else "ai"))
        if decision == "approved" and item["ai_decision_id"]:
            _apply_trim_suggestions(conn, item["ai_decision_id"], eid, reviewer)
        return

    if et == "listing":
        return    # year questions: the decision itself is read back by kb normalize

    if et == "variant":
        conn.execute("UPDATE kb.variant SET status = %s WHERE id = %s",
                     ("accepted" if decision == "approved" else "rejected", eid))
        return

    # --- spec cells ---
    vclass = _class_of_variant(conn, eid)
    if issue in ("ai_value", "ai_value_sample"):
        ev = item["evidence_id"]
        if decision == "approved" and issue == "ai_value":
            _manual(conn, eid, cc, f, prop.get("value"), item["id"], vclass)
        if decision in ("rejected", "corrected") and ev:
            conn.execute("UPDATE kb.spec_evidence SET status = 'rejected' WHERE id = %s", (ev,))
        if decision == "corrected":
            _manual(conn, eid, cc, f, corrected, item["id"], vclass)
        if decision == "approved" and issue == "ai_value" and ev:
            conn.execute("UPDATE kb.spec_evidence SET status = 'rejected', reason = 'superseded_by_review' WHERE id = %s", (ev,))
        return
    if issue == "ai_suspect_known":
        if decision == "approved" and f in MECH_FIELDS + EQUIP_FIELDS:
            _manual(conn, eid, cc, f, prop.get("expected_value"), item["id"], vclass)
        elif decision == "corrected":
            _manual(conn, eid, cc, f, corrected, item["id"], vclass)
        return
    if issue in ("conflicts_with_human", "merge_human_conflict"):
        if decision == "approved":
            _manual(conn, eid, cc, f, prop.get("value"), item["id"], vclass)
        elif decision == "corrected":
            _manual(conn, eid, cc, f, corrected, item["id"], vclass)
        return
    if issue == "listings_disagree":
        if decision == "approved":
            _manual(conn, eid, cc, f, (item["current"] or {}).get("top_value"), item["id"], vclass)
        elif decision == "corrected":
            _manual(conn, eid, cc, f, corrected, item["id"], vclass)
        return
    # rule cross-checks on a field (outlier, hp per litre, seats vs body...): approve keeps the
    # flagged value (consolidate stops flagging it), reject drops it, correct sets the right one.
    if decision == "corrected":
        _manual(conn, eid, cc, f, corrected, item["id"], vclass)


def _apply_trim_suggestions(conn, decision_id: int, model_id: int, reviewer: str) -> None:
    dec = conn.execute("SELECT response FROM kb.ai_decision WHERE id = %s", (decision_id,)).fetchone()
    resp = (dec and dec["response"]) or {}
    rows = {t["id"]: t for t in resp.get("_trim_rows") or []}
    for t in resp.get("trims") or []:
        src = rows.get(t.get("id"))
        if not src or src["model_id"] != model_id or not t.get("canonical_trim") or t.get("status") != "ok":
            continue
        label = split_trim(src["raw"])
        cur = conn.execute("SELECT trim_id FROM kb.trim_alias WHERE model_id = %s AND alias_key = %s",
                           (model_id, compact_key(label))).fetchone()
        if not cur:
            continue
        twin = conn.execute("SELECT trim_id FROM kb.trim_alias WHERE model_id = %s AND alias_key = %s",
                            (model_id, compact_key(t["canonical_trim"]))).fetchone()
        if twin and twin["trim_id"] != cur["trim_id"]:
            merge_trim(conn, cur["trim_id"], twin["trim_id"], f"ai trim suggestion approved by {reviewer}")
        else:
            conn.execute("UPDATE kb.trim SET name = %s, verified_by = 'ai' WHERE id = %s",
                         (t["canonical_trim"], cur["trim_id"]))


def close_sample_batches(conn, reviewer: str) -> Counter:
    """When every sampled item of a batch is decided: accept or reject the whole batch."""
    stats = Counter()
    for b in conn.execute("SELECT * FROM kb.review_batch WHERE decision IS NULL").fetchall():
        sampled = conn.execute(
            """SELECT status FROM kb.review_item WHERE review_batch_id = %s
               AND (issue = 'ai_value_sample' OR note = 'IN SAMPLE')""", (b["id"],)).fetchall()
        if not sampled or any(s["status"] == "pending" for s in sampled):
            continue
        correct = sum(1 for s in sampled if s["status"] == "approved")
        accuracy = correct / len(sampled)
        decision = "accepted" if accuracy >= b["threshold"] else "rejected"
        conn.execute("""UPDATE kb.review_batch SET correct = %s, accuracy = %s, decision = %s, decided_by = %s,
                        decided_at = now() WHERE id = %s""", (correct, accuracy, decision, reviewer, b["id"]))
        stats[f"batch_{decision}"] += 1
        if b["scope"] == "specs":
            if decision == "accepted":
                conn.execute("""UPDATE kb.spec_evidence SET status = 'accepted_sampled' WHERE review_batch_id = %s
                                AND status = 'pending_review' AND confidence >= %s""", (b["id"], b["min_confidence"]))
            else:
                conn.execute("UPDATE kb.spec_evidence SET status = 'rejected' WHERE review_batch_id = %s "
                             "AND status = 'pending_review'", (b["id"],))
        else:
            rest = conn.execute("SELECT * FROM kb.review_item WHERE review_batch_id = %s AND status = 'pending'",
                                (b["id"],)).fetchall()
            for item in rest:
                if decision == "accepted" and ((item["proposed"] or {}).get("confidence") or 0) >= b["min_confidence"]:
                    conn.execute("UPDATE kb.review_item SET status = 'approved', reviewer = %s, decided_at = now() "
                                 "WHERE id = %s", (f"sample:{b['id']}", item["id"]))
                    apply_decision(conn, item, "approved", None, f"sample:{b['id']}", verified_by="ai")
                elif decision == "rejected":
                    conn.execute("UPDATE kb.review_item SET kind = 'individual', review_batch_id = NULL WHERE id = %s",
                                 (item["id"],))
    return stats
