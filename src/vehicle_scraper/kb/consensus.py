"""`kb consolidate`: variants, listing consensus, cross-checks and the published sheets.

Only listings whose make and model are accepted (and whose trim isn't under review) take part:
a model with open identity questions waits without holding the others back.

Evidence derived from listings is recomputed on every run (idempotent). AI and human evidence
is never touched here. The published value of each field is the best accepted evidence:
manual (human) > listing_consensus > listing_single > sibling_inference > ai_knowledge.
A human value is never replaced automatically: contradicting evidence opens a review case.
"""
from __future__ import annotations

import hashlib
import logging
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from .. import normalize as N
from .db import jsonb
from .fields import (EQUIP_FIELDS, GENERATION_CONSTANT, KEY_FIELDS, MECH_FIELDS, coerce, field_kind)
from .identity import listing_number, open_review, split_model, split_trim

log = logging.getLogger(__name__)

MIN_SUPPORT = 2
MIN_AGREEMENT = 0.7
SINGLE_CONFIDENCE = 0.6
SIBLING_CONFIDENCE = 0.5
SIBLING_YEARS = 2
REL_TOLERANCE = {"horsepower_hp": 0.05, "fuel_tank_capacity_l": 0.05, "cargo_capacity_l": 0.05,
                 "fuel_economy_kml": 0.05, "ev_range_km": 0.05, "ev_charging_speed_kw": 0.05,
                 "screen_size_in": 0.05}
RANK = {"manual": 5, "listing_consensus": 4, "listing_single": 3, "sibling_inference": 2, "ai_knowledge": 1}
LISTING_KINDS = ("listing_consensus", "listing_single", "sibling_inference")
PUBLISHED = ("accepted", "accepted_sampled")
NAME_CC_TOLERANCE = 0.15
TITLE_L_TOLERANCE = 0.15
HP_PER_L = (15, 260)
MAD_Z = 3.5
MAD_MIN_GROUP = 5
OUTLIER_REL = 0.25
OUTLIER_FIELDS = {"horsepower_hp", "engine_cylinders", "fuel_tank_capacity_l", "seats", "cargo_capacity_l",
                  "wheel_size_in"}


@dataclass
class Settings:
    min_support: int = MIN_SUPPORT
    min_agreement: float = MIN_AGREEMENT


@dataclass
class ConsolidateStats:
    listings: int = 0
    waiting: int = 0
    variants: int = 0
    partial_matches: int = 0
    clusters: int = 0
    evidence: Counter = field(default_factory=Counter)
    flagged: Counter = field(default_factory=Counter)
    published_mech: int = 0
    published_equip: int = 0
    changes: int = 0


# --- helpers ------------------------------------------------------------------------------
def _num(v):
    return float(v) if isinstance(v, Decimal) else v


def round_displacement(value, moto: bool) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 3 if moto else 1)


def same_value(f: str, a, b) -> bool:
    if a is None or b is None:
        return a is b
    if f in REL_TOLERANCE and isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= REL_TOLERANCE[f] * max(abs(a), abs(b))
    return a == b


def vote(f: str, values: list) -> tuple[object, int, int]:
    """(value, support, total) for the most supported value, tolerance-aware."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None, 0, 0
    exact = Counter(vals)
    support = {v: sum(1 for w in vals if same_value(f, v, w)) for v in exact}
    top = max((support[v], exact[v]) for v in exact)
    tied = sorted((v for v in exact if (support[v], exact[v]) == top), key=_sort_key)
    best = tied[(len(tied) - 1) // 2]            # several equally supported values: the middle one
    return best, support[best], len(vals)


def _sort_key(v) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


@dataclass
class _L:
    site: str
    listing_id: str
    country: str
    model_id: int
    trim_id: Optional[int]
    year: int
    row: dict
    vehicle_class: str
    model_name: str
    raw_model: Optional[str]
    raw_trim: Optional[str]
    last_seen: datetime
    listed_at: Optional[datetime]
    cluster_id: Optional[int] = None
    key: tuple = ()
    variant_id: Optional[int] = None
    partial: bool = False


def _load(conn) -> tuple[list[_L], int]:
    rows = conn.execute(
        """SELECT l.source_site, l.listing_id, l.country, l.model_id, l.trim_id, l.raw_year, l.raw_model,
                  l.raw_trim, l.last_seen, l.listed_at, r.row, md.vehicle_class, md.name AS model_name,
                  (mk.status = 'accepted' AND md.status = 'accepted' AND md.merged_into IS NULL
                   AND (t.id IS NULL OR t.status NOT IN ('pending_review', 'rejected'))
                   AND l.excluded_reason IS NULL) AS ready
           FROM kb.listing l
           JOIN staging.raw_listing r ON r.source_site = l.source_site AND r.listing_id = l.listing_id
                                     AND r.version = l.current_version
           LEFT JOIN kb.make mk ON mk.id = l.make_id
           LEFT JOIN kb.model md ON md.id = l.model_id
           LEFT JOIN kb.trim t ON t.id = l.trim_id
           ORDER BY l.source_site, l.listing_id""").fetchall()
    ready = [_L(r["source_site"], r["listing_id"], r["country"], r["model_id"], r["trim_id"], r["raw_year"],
                r["row"], r["vehicle_class"] or "car", r["model_name"], r["raw_model"], r["raw_trim"],
                r["last_seen"], r["listed_at"]) for r in rows if r["ready"]]
    return ready, len(rows) - len(ready)


def _listing_key(l: _L) -> tuple:
    row, moto = l.row, l.vehicle_class == "motorcycle"
    _, attrs = split_model(l.raw_model)
    title = f"{l.raw_model or ''} {l.raw_trim or ''}"
    disp = row.get("engine_displacement_l") or attrs.get("engine_displacement_l")
    fuel = row.get("fuel_type") or attrs.get("fuel_type")
    trans = row.get("transmission_type") or N.to_transmission(l.raw_trim)
    drive = row.get("drivetrain") or attrs.get("drivetrain") or N.drivetrain_from_title(title)
    return (round_displacement(disp, moto), fuel, trans, drive)


# --- variants -------------------------------------------------------------------------------
def build_variants(conn, listings: list[_L], stats: ConsolidateStats) -> None:
    for l in listings:
        l.key = _listing_key(l)
    # A listing missing some key attributes joins the one more specific sibling it's
    # compatible with (same model/trim/year); if there are several, it keeps its own variant.
    groups: dict[tuple, list[_L]] = defaultdict(list)
    for l in listings:
        groups[(l.model_id, l.trim_id, l.year)].append(l)
    for group in groups.values():
        keys = Counter(l.key for l in group)
        for l in group:
            if None not in l.key:
                continue
            known = sum(v is not None for v in l.key)
            cands = {k for k in keys if k != l.key and sum(v is not None for v in k) > known
                     and all(a is None or a == b for a, b in zip(l.key, k))}
            if cands:
                top = max(sum(v is not None for v in k) for k in cands)
                best = {k for k in cands if sum(v is not None for v in k) == top}
                if len(best) == 1:
                    l.key, l.partial = best.pop(), True
                    stats.partial_matches += 1

    existing = {}
    for v in conn.execute("SELECT id, model_id, trim_id, model_year, engine_displacement_l, fuel_type, "
                          "transmission_type, drivetrain FROM kb.variant").fetchall():
        existing[(v["model_id"], v["trim_id"], v["model_year"], _num(v["engine_displacement_l"]), v["fuel_type"],
                  v["transmission_type"], v["drivetrain"])] = v["id"]
    for l in listings:
        full = (l.model_id, l.trim_id, l.year) + l.key
        vid = existing.get(full)
        if vid is None:
            vid = conn.execute(
                """INSERT INTO kb.variant (model_id, trim_id, model_year, engine_displacement_l, fuel_type,
                                           transmission_type, drivetrain, verified_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'multi_source') RETURNING id""", full).fetchone()["id"]
            existing[full] = vid
        l.variant_id = vid
    stats.variants = len({l.variant_id for l in listings})
    with conn.cursor() as cur:
        cur.execute("UPDATE kb.listing SET variant_id = NULL WHERE variant_id IS NOT NULL")
        cur.executemany("UPDATE kb.listing SET variant_id = %s, match_method = %s WHERE source_site = %s AND listing_id = %s",
                        [(l.variant_id, "rule_partial" if l.partial else "rule", l.site, l.listing_id) for l in listings])
        cur.execute("DELETE FROM kb.variant_market")
        counts = Counter((l.variant_id, l.country) for l in listings)
        cur.executemany("INSERT INTO kb.variant_market (variant_id, country, listings_seen) VALUES (%s, %s, %s)",
                        [(v, c, n) for (v, c), n in counts.items()])


# --- same car on several portals (or reposted) ---------------------------------------------
def build_clusters(conn, listings: list[_L], stats: ConsolidateStats) -> None:
    """Heuristic: same model and year, mileage within 2 %, price within 5 % (same currency),
    listing dates within 30 days. Grouped listings count as ONE vote. Never deletes anything;
    a cluster marked ``undone`` by a person is not re-applied."""
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    buckets: dict[tuple, list[_L]] = defaultdict(list)
    for l in listings:
        km, price, cur = l.row.get("mileage_km"), l.row.get("price"), l.row.get("currency")
        if km and km > 0 and price and l.listed_at:
            buckets[(l.model_id, l.year, cur)].append(l)
    for group in buckets.values():
        group.sort(key=lambda l: l.row["mileage_km"])
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if b.row["mileage_km"] > a.row["mileage_km"] * 1.02:
                    break
                if (abs(a.row["price"] - b.row["price"]) <= 0.05 * max(a.row["price"], b.row["price"])
                        and abs((a.listed_at - b.listed_at).days) <= 30):
                    parent[find((a.site, a.listing_id))] = find((b.site, b.listing_id))
    members: dict[tuple, list[tuple]] = defaultdict(list)
    for key in list(parent):
        members[find(key)].append(key)
    by_key = {(l.site, l.listing_id): l for l in listings}
    undone = {r["member_hash"] for r in conn.execute("SELECT member_hash FROM kb.listing_cluster WHERE undone")}
    conn.execute("UPDATE kb.listing SET cluster_id = NULL WHERE cluster_id IS NOT NULL")
    for keys in members.values():
        if len(keys) < 2:
            continue
        h = hashlib.sha1("|".join(sorted(f"{s}:{i}" for s, i in keys)).encode()).hexdigest()
        if h in undone:
            continue
        cid = conn.execute("""INSERT INTO kb.listing_cluster (member_hash, method, members) VALUES (%s, 'heuristic', %s)
                              ON CONFLICT (member_hash) DO UPDATE SET members = EXCLUDED.members RETURNING id""",
                           (h, len(keys))).fetchone()["id"]
        for k in keys:
            by_key[k].cluster_id = cid
        conn.execute("UPDATE kb.listing SET cluster_id = %s WHERE (source_site, listing_id) IN (%s)"
                     % ("%s", ", ".join(["(%s, %s)"] * len(keys))), [cid, *[x for k in keys for x in k]])
        stats.clusters += 1


def _votes(listings: list[_L]) -> list[_L]:
    """One vote per cluster (its most recently seen listing), one per lone listing."""
    out, seen = [], {}
    for l in sorted(listings, key=lambda l: l.last_seen, reverse=True):
        if l.cluster_id is None:
            out.append(l)
        elif l.cluster_id not in seen:
            seen[l.cluster_id] = l
            out.append(l)
    return out


# --- evidence -------------------------------------------------------------------------------
@dataclass
class _Ev:
    variant_id: int
    country: str
    field: str
    value: object
    kind: str
    support: int
    agreement: float
    confidence: float
    status: str
    sites: list
    reason: Optional[str] = None


def listing_evidence(by_variant: dict[int, list[_L]], cfg: Settings) -> list[_Ev]:
    out = []
    for vid, ls in by_variant.items():
        votes = _votes(ls)
        for f in MECH_FIELDS:
            vals = [(coerce(f, l.row.get(f)), l.site) for l in votes]
            vals = [(v, s) for v, s in vals if v is not None]
            if not vals:
                continue
            value, support, total = vote(f, [v for v, _ in vals])
            sites = sorted({s for v, s in vals if same_value(f, v, value)})
            if total == 1:
                out.append(_Ev(vid, "", f, value, "listing_single", 1, 1.0, SINGLE_CONFIDENCE, "accepted", sites))
            elif support >= cfg.min_support and support / total >= cfg.min_agreement:
                out.append(_Ev(vid, "", f, value, "listing_consensus", support, support / total,
                               round(min(0.95, 0.7 + 0.05 * support), 2), "accepted", sites))
            else:
                out.append(_Ev(vid, "", f, value, "listing_consensus", support, support / total, 0.3,
                               "pending_review", sites, reason="listings_disagree"))
        by_country: dict[str, list[_L]] = defaultdict(list)
        for l in votes:
            by_country[l.country].append(l)
        for country, cls in by_country.items():
            for f in EQUIP_FIELDS:
                vals = [(coerce(f, l.row.get(f)), l.site) for l in cls]
                vals = [(v, s) for v, s in vals if v is not None]
                if len(vals) < cfg.min_support:
                    continue                    # one listing never sets a version's equipment
                value, support, total = vote(f, [v for v, _ in vals])
                if support >= cfg.min_support and support / total >= cfg.min_agreement:
                    out.append(_Ev(vid, country, f, value, "listing_consensus", support, support / total,
                                   round(min(0.95, 0.7 + 0.05 * support), 2), "accepted",
                                   sorted({s for v, s in vals if same_value(f, v, value)})))
    return out


def sibling_evidence(evs: list[_Ev], variants: dict[int, dict]) -> list[_Ev]:
    """Doors, seats, tank, cargo from the same trim + engine in neighbouring years (±2) when
    every such sibling that knows the value agrees."""
    known: dict[tuple, dict[int, object]] = defaultdict(dict)
    have = set()
    for e in evs:
        if e.status == "accepted" and e.country == "":
            have.add((e.variant_id, e.field))
            if e.field in GENERATION_CONSTANT:
                v = variants[e.variant_id]
                known[(v["model_id"], v["trim_id"], _num(v["engine_displacement_l"]), v["fuel_type"], e.field)][v["model_year"]] = (e.value, e.sites)
    out = []
    for vid, v in variants.items():
        for f in GENERATION_CONSTANT:
            if (vid, f) in have:
                continue
            years = known.get((v["model_id"], v["trim_id"], _num(v["engine_displacement_l"]), v["fuel_type"], f), {})
            near = [val for y, val in years.items() if y != v["model_year"] and abs(y - v["model_year"]) <= SIBLING_YEARS]
            if near and all(same_value(f, near[0][0], x[0]) for x in near):
                out.append(_Ev(vid, "", f, near[0][0], "sibling_inference", len(near), 1.0, SIBLING_CONFIDENCE,
                               "accepted", sorted({s for x in near for s in x[1]}), reason="neighbouring_years"))
    return out


# --- cross-checks (flag for review, never correct) ---------------------------------------------
_NAME_CC = re.compile(r"(?<!\d)(\d{3,4})(?!\d)")


def name_cc(text: str) -> Optional[int]:
    m = _NAME_CC.search(text or "")
    if m and 50 <= int(m.group(1)) <= 1900:
        return int(m.group(1))
    return None


def crosscheck_variants(conn, by_variant: dict[int, list[_L]], variants: dict[int, dict],
                        stats: ConsolidateStats) -> set[int]:
    """Variant-level checks on the key itself. Returns variants put on hold."""
    held = set()
    for vid, ls in by_variant.items():
        v = variants[vid]
        disp = _num(v["engine_displacement_l"])
        cls = ls[0].vehicle_class
        issue, detail = None, None
        if disp is not None and v["fuel_type"] == "EV":
            issue, detail = "ev_with_displacement", {"engine_displacement_l": disp}
        elif disp is not None and cls == "motorcycle":
            cc = name_cc(f"{ls[0].model_name} {split_trim(ls[0].raw_trim) or ''}")
            if cc and abs(disp * 1000 - cc) / cc > NAME_CC_TOLERANCE:
                issue, detail = "name_vs_displacement", {"name_number": cc, "engine_displacement_l": disp}
        elif disp is not None:
            tokens = {N.parse_number(t) for t in (N.displacement_from_title(l.raw_trim) for l in ls) if t}
            tokens.discard(None)
            if tokens and all(abs(t - disp) > TITLE_L_TOLERANCE for t in tokens):
                issue, detail = "title_vs_displacement", {"title_litres": sorted(tokens), "engine_displacement_l": disp}
        decision = _decision(conn, "variant", vid, issue, "engine_displacement_l") if issue else None
        if decision == "rejected":                 # a person said this variant's key is wrong
            held.add(vid)
            conn.execute("UPDATE kb.variant SET status = 'rejected' WHERE id = %s", (vid,))
        elif issue and decision is None:
            held.add(vid)
            stats.flagged[issue] += 1
            open_review(conn, level=4, entity_type="variant", entity_id=vid, field_="engine_displacement_l",
                        issue=issue, source="rule", current=detail, listings=len(ls),
                        evidence={"model": ls[0].model_name, "year": v["model_year"],
                                  "listings": [f"{l.site}:{l.listing_id}" for l in ls[:10]]})
    if held:
        conn.execute("UPDATE kb.variant SET status = 'pending_review' WHERE id = ANY(%s) AND status = 'accepted'",
                     (list(held),))
    released = [vid for vid in variants if vid not in held and variants[vid]["status"] == "pending_review"
                and not _open(conn, "variant", vid)]
    if released:
        conn.execute("UPDATE kb.variant SET status = 'accepted' WHERE id = ANY(%s)", (released,))
    return held | {vid for vid, v in variants.items() if v["status"] == "rejected"}


def crosscheck_evidence(evs: list[_Ev], variants: dict[int, dict], classes: dict[int, str]) -> list[tuple[_Ev, str, dict]]:
    """Field-level checks: hp per litre, seats/doors vs body, outliers within the model (MAD)."""
    flags = []
    by_vf = {(e.variant_id, e.field): e for e in evs if e.country == "" and e.status == "accepted"}
    for (vid, f), e in by_vf.items():
        v, cls = variants[vid], classes.get(vid, "car")
        disp = _num(v["engine_displacement_l"])
        if f == "horsepower_hp" and disp and v["fuel_type"] != "EV":
            hpl = e.value / disp
            if not HP_PER_L[0] <= hpl <= HP_PER_L[1]:
                flags.append((e, "hp_per_litre", {"hp_per_litre": round(hpl, 1)}))
        if f == "seats" and cls == "car" and e.value > 9:
            body = by_vf.get((vid, "body_style"))
            if not body or body.value not in ("Van", "Minivan", "Truck"):
                flags.append((e, "seats_vs_body", {"seats": e.value, "body_style": body.value if body else None}))
        if f == "doors" and cls == "motorcycle" and e.value:
            flags.append((e, "doors_on_motorcycle", {"doors": e.value}))
    # Outliers within comparable variants: hp/cylinders per model + engine, cargo per model +
    # body (sedan vs hatchback legitimately differ), tank/seats/rim per model. Doors are left
    # out: 3/5-door and 2/4-door versions of one model are normal. A value must be both a
    # robust outlier (MAD) and > OUTLIER_REL away from the median, so tiny spreads don't fire.
    groups: dict[tuple, list[_Ev]] = defaultdict(list)
    for (vid, f), e in by_vf.items():
        if f not in OUTLIER_FIELDS:
            continue
        v = variants[vid]
        if f in ("horsepower_hp", "engine_cylinders"):
            g = (v["model_id"], _num(v["engine_displacement_l"]), v["fuel_type"])
        elif f == "cargo_capacity_l":
            body = by_vf.get((vid, "body_style"))
            g = (v["model_id"], body.value if body else None)
        else:
            g = (v["model_id"],)
        groups[g + (f,)].append(e)
    for g, items in groups.items():
        if len(items) < MAD_MIN_GROUP:
            continue
        vals = [float(e.value) for e in items]
        med = statistics.median(vals)
        mad = statistics.median(abs(x - med) for x in vals)
        for e in items:
            x = float(e.value)
            far = bool(med) and abs(x - med) / abs(med) > OUTLIER_REL
            if far and (mad == 0 or 0.6745 * abs(x - med) / mad > MAD_Z):
                flags.append((e, "outlier_in_model", {"value": e.value, "model_median": med}))
    return flags


def _open(conn, entity_type: str, entity_id: int) -> bool:
    return conn.execute("SELECT 1 FROM kb.review_item WHERE entity_type = %s AND entity_id = %s AND status = 'pending'",
                        (entity_type, entity_id)).fetchone() is not None


def _decision(conn, entity_type: str, entity_id: int, issue: str, field_: str = "") -> Optional[str]:
    """What a person last decided on this exact question: 'approved' (the value is right),
    'rejected' (it's wrong), or None (never asked/answered). A decided question is not
    asked again; 'corrected' counts as rejected here (the correction is a manual value)."""
    row = conn.execute("SELECT status FROM kb.review_item WHERE entity_type = %s AND entity_id = %s AND issue = %s "
                       "AND field = %s AND status <> 'pending' ORDER BY decided_at DESC NULLS LAST, id DESC LIMIT 1",
                       (entity_type, entity_id, issue, field_)).fetchone()
    if not row:
        return None
    return "approved" if row["status"] == "approved" else "rejected"


# --- write evidence + publish ---------------------------------------------------------------
def write_listing_evidence(conn, evs: list[_Ev]) -> None:
    """Replace listing-derived evidence with this run's (AI and manual rows untouched)."""
    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE _ev (LIKE kb.spec_evidence INCLUDING DEFAULTS) ON COMMIT DROP")
        cur.executemany(
            """INSERT INTO _ev (variant_id, country, field, value, source_kind, support_count, agreement,
                                confidence, status, sites, reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            [(e.variant_id, e.country, e.field, jsonb(e.value), e.kind, e.support, e.agreement, e.confidence,
              e.status, e.sites, e.reason) for e in evs])
        cur.execute("""DELETE FROM kb.spec_evidence e WHERE e.source_kind = ANY(%s) AND NOT EXISTS (
                           SELECT 1 FROM _ev n WHERE n.variant_id = e.variant_id AND n.country = e.country
                             AND n.field = e.field AND n.source_kind = e.source_kind)""", (list(LISTING_KINDS),))
        cur.execute("""INSERT INTO kb.spec_evidence (variant_id, country, field, value, source_kind, support_count,
                                                     agreement, confidence, status, sites, reason)
                       SELECT variant_id, country, field, value, source_kind, support_count, agreement, confidence,
                              status, sites, reason FROM _ev
                       ON CONFLICT (variant_id, country, field, source_kind, origin_key) DO UPDATE SET
                           value = EXCLUDED.value, support_count = EXCLUDED.support_count,
                           agreement = EXCLUDED.agreement, confidence = EXCLUDED.confidence,
                           status = EXCLUDED.status, sites = EXCLUDED.sites, reason = EXCLUDED.reason,
                           updated_at = now()
                       WHERE (kb.spec_evidence.value, kb.spec_evidence.status, kb.spec_evidence.support_count)
                             IS DISTINCT FROM (EXCLUDED.value, EXCLUDED.status, EXCLUDED.support_count)""")


def publish(conn, held: set[int], stats: ConsolidateStats) -> None:
    """Best accepted evidence per field -> variant_spec / variant_market_spec, with history.
    A human value always stays; disagreeing accepted listing evidence opens a review case."""
    rows = conn.execute(
        f"""SELECT id, variant_id, country, field, value, source_kind, confidence, status
            FROM kb.spec_evidence WHERE status = ANY(%s)""", (list(PUBLISHED),)).fetchall()
    best: dict[tuple, dict] = {}
    by_cell: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["variant_id"] in held:
            continue
        key = (r["variant_id"], r["country"], r["field"])
        by_cell[key].append(r)
        cur = best.get(key)
        if cur is None or (RANK[r["source_kind"]], r["confidence"] or 0) > (RANK[cur["source_kind"]], cur["confidence"] or 0):
            best[key] = r
    for key, cands in by_cell.items():
        top = best[key]
        if top["source_kind"] != "manual":
            continue
        for c in cands:
            if c["source_kind"] in ("listing_consensus",) and not same_value(key[2], c["value"], top["value"]):
                open_review(conn, level=5 if key[1] == "" else 6, entity_type="spec", entity_id=key[0],
                            country=key[1], field_=key[2], issue="conflicts_with_human", source="rule",
                            current={"published": top["value"], "source": "manual"},
                            proposed={"value": c["value"], "support": None}, evidence_id=c["id"])

    current_mech = {r["variant_id"]: r for r in conn.execute("SELECT * FROM kb.variant_spec").fetchall()}
    current_eq = {(r["variant_id"], r["country"]): r for r in conn.execute("SELECT * FROM kb.variant_market_spec").fetchall()}
    mech: dict[int, dict] = defaultdict(dict)
    equip: dict[tuple, dict] = defaultdict(dict)
    sources: dict[tuple, str] = {}
    for (vid, country, f), r in best.items():
        (mech[vid] if country == "" else equip[(vid, country)])[f] = r["value"]
        sources[(vid, country, f)] = r["source_kind"]

    history = []
    for vid in set(mech) | set(current_mech):
        new, old = mech.get(vid, {}), current_mech.get(vid) or {}
        for f in MECH_FIELDS:
            if not same_value(f, _num(old.get(f)), new.get(f)) or (old.get(f) is None) != (new.get(f) is None):
                history.append((vid, "", f, old.get(f), new.get(f), sources.get((vid, "", f))))
    for key in set(equip) | set(current_eq):
        new, old = equip.get(key, {}), current_eq.get(key) or {}
        for f in EQUIP_FIELDS:
            if not same_value(f, _num(old.get(f)), new.get(f)) or (old.get(f) is None) != (new.get(f) is None):
                history.append((key[0], key[1], f, old.get(f), new.get(f), sources.get((key[0], key[1], f))))
    stats.changes = len(history)

    with conn.cursor() as cur:
        cur.execute("DELETE FROM kb.variant_spec")
        cur.execute("DELETE FROM kb.variant_market_spec")
        cols = ", ".join(MECH_FIELDS)
        cur.executemany(f"INSERT INTO kb.variant_spec (variant_id, {cols}) VALUES (%s, {', '.join(['%s'] * len(MECH_FIELDS))})",
                        [(vid, *[vals.get(f) for f in MECH_FIELDS]) for vid, vals in mech.items()])
        ecols = ", ".join(EQUIP_FIELDS)
        cur.executemany(f"INSERT INTO kb.variant_market_spec (variant_id, country, {ecols}) "
                        f"VALUES (%s, %s, {', '.join(['%s'] * len(EQUIP_FIELDS))})",
                        [(k[0], k[1], *[vals.get(f) for f in EQUIP_FIELDS]) for k, vals in equip.items()])
        cur.executemany("""INSERT INTO kb.spec_history (variant_id, country, field, old_value, new_value, new_source, reason)
                           VALUES (%s, %s, %s, %s, %s, %s, 'consolidate')""",
                        [(v, c, f, jsonb(_num(o)), jsonb(n), s) for v, c, f, o, n, s in history])
    stats.published_mech = len(mech)
    stats.published_equip = len(equip)


# --- entry point ----------------------------------------------------------------------------
def consolidate(conn, cfg: Settings = Settings()) -> ConsolidateStats:
    stats = ConsolidateStats()
    listings, stats.waiting = _load(conn)
    stats.listings = len(listings)
    build_variants(conn, listings, stats)
    build_clusters(conn, listings, stats)

    variants = {r["id"]: r for r in conn.execute("SELECT * FROM kb.variant").fetchall()}
    by_variant: dict[int, list[_L]] = defaultdict(list)
    for l in listings:
        by_variant[l.variant_id].append(l)
    classes = {vid: ls[0].vehicle_class for vid, ls in by_variant.items()}

    held = crosscheck_variants(conn, by_variant, variants, stats)
    evs = listing_evidence(by_variant, cfg)
    evs += sibling_evidence(evs, {vid: variants[vid] for vid in by_variant})
    for e, issue, detail in crosscheck_evidence(evs, variants, classes):
        decision = _decision(conn, "spec", e.variant_id, issue, e.field)
        if decision == "approved":
            continue
        if decision == "rejected":
            e.status, e.reason = "rejected", issue
            continue
        e.status, e.reason = "pending_review", issue
        stats.flagged[issue] += 1
        open_review(conn, level=5, entity_type="spec", entity_id=e.variant_id, field_=e.field, issue=issue,
                    source="rule", current={"value": e.value, "source": e.kind, **detail},
                    listings=len(by_variant.get(e.variant_id, [])))
    for e in evs:
        if e.reason == "listings_disagree" and _decision(conn, "spec", e.variant_id, "listings_disagree", e.field):
            e.status = "rejected"                  # answered: the reviewer's value is a manual row
        elif e.reason == "listings_disagree":
            stats.flagged["listings_disagree"] += 1
            open_review(conn, level=5, entity_type="spec", entity_id=e.variant_id, field_=e.field,
                        issue="listings_disagree", source="rule",
                        current={"top_value": e.value, "support": e.support, "agreement": round(e.agreement, 2)},
                        listings=len(by_variant.get(e.variant_id, [])))
        stats.evidence[f"{e.kind}:{e.status}"] += 1
    write_listing_evidence(conn, evs)
    publish(conn, held, stats)
    return stats


# --- merges (called from identity.merge_model / merge_trim) -----------------------------------
def _rekey(conn, variant_rows: list[dict], new_model: Optional[int], new_trim: Optional[int], reason: str,
           trim_map: Optional[dict] = None) -> None:
    for v in variant_rows:
        model_id = new_model if new_model is not None else v["model_id"]
        trim_id = (trim_map or {}).get(v["trim_id"], new_trim if new_trim is not None else v["trim_id"])
        twin = conn.execute(
            """SELECT id FROM kb.variant WHERE id <> %s AND model_id = %s AND trim_id IS NOT DISTINCT FROM %s
               AND model_year = %s AND engine_displacement_l IS NOT DISTINCT FROM %s
               AND fuel_type IS NOT DISTINCT FROM %s AND transmission_type IS NOT DISTINCT FROM %s
               AND drivetrain IS NOT DISTINCT FROM %s""",
            (v["id"], model_id, trim_id, v["model_year"], v["engine_displacement_l"], v["fuel_type"],
             v["transmission_type"], v["drivetrain"])).fetchone()
        if not twin:
            conn.execute("UPDATE kb.variant SET model_id = %s, trim_id = %s WHERE id = %s", (model_id, trim_id, v["id"]))
            continue
        dst = twin["id"]
        # Human/AI evidence moves to the twin; if both sides hold a human value that disagrees,
        # keep the twin's and open a case instead of choosing.
        for e in conn.execute("SELECT * FROM kb.spec_evidence WHERE variant_id = %s AND source_kind IN ('manual', 'ai_knowledge')",
                              (v["id"],)).fetchall():
            clash = conn.execute("SELECT id, value FROM kb.spec_evidence WHERE variant_id = %s AND country = %s AND field = %s "
                                 "AND source_kind = %s AND origin_key = %s", (dst, e["country"], e["field"],
                                                                            e["source_kind"], e["origin_key"])).fetchone()
            if clash is None:
                conn.execute("UPDATE kb.spec_evidence SET variant_id = %s WHERE id = %s", (dst, e["id"]))
            elif e["source_kind"] == "manual" and clash["value"] != e["value"]:
                open_review(conn, level=5, entity_type="spec", entity_id=dst, country=e["country"], field_=e["field"],
                            issue="merge_human_conflict", source="merge",
                            current={"kept": clash["value"]}, proposed={"value": e["value"]},
                            evidence={"merged_variant": v["id"], "reason": reason})
        conn.execute("UPDATE kb.listing SET variant_id = %s WHERE variant_id = %s", (dst, v["id"]))
        conn.execute("UPDATE kb.review_item SET entity_id = %s WHERE entity_type IN ('variant', 'spec') AND entity_id = %s "
                     "AND status <> 'pending'", (dst, v["id"]))
        conn.execute("DELETE FROM kb.variant WHERE id = %s", (v["id"],))


def merge_variants_of_model(conn, src: int, dst: int, reason: str) -> None:
    rows = conn.execute("SELECT * FROM kb.variant WHERE model_id = %s", (src,)).fetchall()
    trim_map = {r["id"]: r["merged_into"] for r in conn.execute("SELECT id, merged_into FROM kb.trim WHERE merged_into IS NOT NULL")}
    _rekey(conn, rows, dst, None, reason, trim_map)


def merge_variants_of_trim(conn, src: int, dst: int, reason: str) -> None:
    rows = conn.execute("SELECT * FROM kb.variant WHERE trim_id = %s", (src,)).fetchall()
    model = conn.execute("SELECT model_id FROM kb.trim WHERE id = %s", (dst,)).fetchone()["model_id"]
    _rekey(conn, rows, model, dst, reason)
