"""``kb build``: from ``kb.clean_listing`` to the three levels.

Run after ``kb clean``. In one transaction under the writer lock:

1. Apply decided cases: generation splits, corrected spec values (manual evidence) and
   approved evolution notes.
2. **Generations**: one provisional generation per accepted model and body style (observed
   years). A listing without a body joins its model's only generation for that year; with
   several, it stays unassigned (``ambiguous_body``). After a split, the year picks the half.
3. **Powertrains** per generation, keyed by fuel, transmission, drivetrain and displacement (or
   cylinders when there's no displacement). Keys are taken most complete first; a key joins the
   only compatible powertrain, opens a new one when none is, and stays unassigned
   (``ambiguous_powertrain``) when several are. Ids are stable (``match_key``). A rejected
   powertrain is never recreated: listings whose only match it is stay ``powertrain_rejected``.
4. **Commercial variants**: generation + powertrain + country + trim (``''`` = trim unknown).
   A rejected variant is never recreated nor given listings: they keep their generation and
   powertrain and stay ``variant_rejected``.
5. **Evidence from listings**, recomputed every run: mechanical numbers from one plausible
   listing (most repeated value; > 10 % spread opens ``spec_disagreement``); equipment with
   >= 2 listings and >= 70 % agreement. Other sources' evidence is never touched.
6. **Publish**: each level column gets its best accepted evidence (manual > external >
   listings > ai). Columns are derived: change a value through evidence, not by hand.
7. **Proposals** for a person: ``generation_split`` (the engine changes between years) and
   ``evolution_note`` (an equipment field flips from a year on).
8. **Final records** (``kb/final.py``): ``kb.final_listing``, what each in-scope listing
   inherits from the three levels (the base wins; the listing fills gaps), evolution notes by year.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .clean import Cases, write_cases
from .db import take_writer_lock
from .final import write_final
from .identity import compact_key
from .levels import (BOOLEAN, EQUIP_MIN_AGREEMENT, EQUIP_MIN_SUPPORT, EQUIPMENT_FIELDS, EVOLUTION_MIN_SUPPORT,
                     GENERATION_COLUMNS, GENERATION_FROM_LISTINGS, MECH_DISAGREEMENT, POWERTRAIN_COLUMNS,
                     LISTING_FIELD_OF, POWERTRAIN_FROM_LISTINGS, RANGES, SOURCE_RANK, VARIANT_COLUMNS,
                     VARIANT_FROM_LISTINGS)

BUILD_ISSUES = ("generation_split", "spec_disagreement", "evolution_note")
DISPLACEMENT_TOLERANCE = 0.1
SPLIT_MIN_LISTINGS = 3          # listings needed on each side of a proposed generation split
SPLIT_MIN_SHARE = 0.10          # an engine below this share of its side doesn't count
TRANSMISSION_COMPATIBLE = [{"Automatic", "CVT"}, {"Automatic", "DCT"}]
DRIVETRAIN_COMPATIBLE = [{"AWD", "4WD"}, {"2WD", "FWD"}, {"2WD", "RWD"}]
KEY_FIELDS = ("fuel", "trans", "drive", "disp", "cyl")
TABLES = {"generation": ("kb.generation", GENERATION_COLUMNS),
          "powertrain": ("kb.powertrain", POWERTRAIN_COLUMNS),
          "variant": ("kb.commercial_variant", VARIANT_COLUMNS)}


@dataclass
class _Listing:
    site: str
    listing_id: str
    country: str
    year: Optional[int]
    model_id: Optional[int]
    model_ok: bool
    body: Optional[str]
    key: tuple                      # (fuel, trans, drive, disp rounded, cylinders if no disp)
    trim: Optional[str]
    votes: dict                     # field -> value, for the evidence
    generation: Optional[int] = None
    powertrain: Optional[int] = None
    variant: Optional[int] = None
    reason: Optional[str] = None


@dataclass
class _Generation:
    id: int
    model_id: int
    body: Optional[str]
    year_from: Optional[int]
    year_to: Optional[int]
    status: str
    split_children: int = 0
    listings: list = field(default_factory=list)

    def covers(self, year: Optional[int]) -> bool:
        return year is None or ((self.year_from is None or year >= self.year_from)
                                and (self.year_to is None or year <= self.year_to))


def _compatible(key: tuple, pt: dict) -> bool:
    for name, a in zip(KEY_FIELDS, key):
        b = pt[name]
        if a is None or b is None:
            continue
        if name == "disp":
            if abs(float(a) - float(b)) > DISPLACEMENT_TOLERANCE:
                return False
        elif a != b and not any({a, b} <= pair for pair in (TRANSMISSION_COMPATIBLE if name == "trans"
                                                             else DRIVETRAIN_COMPATIBLE if name == "drive" else [])):
            return False
    return True


def match_key(key: tuple) -> str:
    return "|".join("" if v is None else str(v) for v in key)


def _plausible(field_name: str, value) -> bool:
    if value is None:
        return False
    if field_name in RANGES:
        try:
            lo, hi = RANGES[field_name]
            return lo <= float(value) <= hi
        except (TypeError, ValueError):
            return False
    return True


def _mechanical(values: list) -> Optional[dict]:
    """One plausible value is enough: the most repeated one (ties: closest to the median)."""
    if not values:
        return None
    nums = [float(v) for v in values]
    median = statistics.median(nums)
    counts = Counter(values)
    best = max(counts.items(), key=lambda kv: (kv[1], -abs(float(kv[0]) - median)))[0]
    spread = median and any(abs(v - median) / abs(median) > MECH_DISAGREEMENT for v in nums)
    return {"value": best, "status": "accepted", "support": len(values),
            "agreement": counts[best] / len(values), "disagree": bool(spread), "counts": counts}


def _equipment(values: list) -> Optional[dict]:
    if not values:
        return None
    counts = Counter(values)
    best, n = counts.most_common(1)[0]
    share = n / len(values)
    ok = len(values) >= EQUIP_MIN_SUPPORT and share >= EQUIP_MIN_AGREEMENT
    return {"value": best, "status": "accepted" if ok else "pending", "support": len(values),
            "agreement": share, "disagree": False, "counts": counts}


def _split_year(years: dict) -> Optional[tuple[int, dict, dict]]:
    """Year where the engines before and after don't overlap at all, or None."""
    ys = sorted(years)
    best = None
    for y in ys[1:]:
        before, after = Counter(), Counter()
        for yy, c in years.items():
            (before if yy < y else after).update(c)
        nb, na = sum(before.values()), sum(after.values())
        if nb < SPLIT_MIN_LISTINGS or na < SPLIT_MIN_LISTINGS:
            continue
        a = {v for v, c in before.items() if c / nb >= SPLIT_MIN_SHARE}
        b = {v for v, c in after.items() if c / na >= SPLIT_MIN_SHARE}
        if a and b and a.isdisjoint(b) and (best is None or min(nb, na) > best[0]):
            best = (min(nb, na), y, dict(before), dict(after))
    return best and best[1:]


def _evolution(by_year: dict) -> Optional[tuple[int, object, object, int, int]]:
    """(year, value before, value after, n before, n after) when the field flips from a year on."""
    best = None
    for y in sorted(by_year)[1:]:
        before, after = Counter(), Counter()
        for yy, c in by_year.items():
            (before if yy < y else after).update(c)
        nb, na = sum(before.values()), sum(after.values())
        if nb < EVOLUTION_MIN_SUPPORT or na < EVOLUTION_MIN_SUPPORT:
            continue
        vb, cb = before.most_common(1)[0]
        va, ca = after.most_common(1)[0]
        if vb != va and cb / nb >= EQUIP_MIN_AGREEMENT and ca / na >= EQUIP_MIN_AGREEMENT:
            if best is None or min(nb, na) > min(best[3], best[4]):
                best = (y, vb, va, nb, na)
    return best


def _load(cur, sql: str, args=None) -> list[tuple]:
    cur.execute(sql, args)
    return cur.fetchall()


# --- decisions ------------------------------------------------------------------------------
def split_generation(cur, gen_id: int, year: int) -> Optional[int]:
    """Cut a generation at ``year``: it ends the year before and a new one (``split_from``)
    starts at ``year``. Listings move on the next build. Returns the new generation's id, or
    None when the generation doesn't exist or the year isn't inside its range."""
    g = _load(cur, "SELECT model_id, body_style_code, name, year_from, year_to, observed_year_from, "
                   "observed_year_to FROM kb.generation WHERE id = %s", (gen_id,))
    if not g:
        return None
    model_id, body, name, yf, yt, oyf, oyt = g[0]
    start = yf if yf is not None else oyf
    if (start is not None and year <= start) or (yt is not None and year > yt):
        return None
    cur.execute("UPDATE kb.generation SET year_from = coalesce(year_from, %s), year_to = %s, "
                "source = 'manual', updated_at = now() WHERE id = %s", (oyf, year - 1, gen_id))
    cur.execute("INSERT INTO kb.generation (model_id, body_style_code, name, year_from, year_to, source, "
                "split_from) VALUES (%s, %s, %s, %s, %s, 'manual', %s) RETURNING id",
                (model_id, body, f"{name} ({year}+)", year, yt, gen_id))
    return cur.fetchone()[0]


def _apply_decisions(cur) -> None:
    # Generation splits: the decided year (or the corrected one) cuts the generation in two.
    for case_id, gen_id, status, proposed, corrected in _load(cur, """
SELECT r.id, r.entity_key::bigint, r.status, r.proposed_value, r.corrected_value FROM kb.review_item r
WHERE r.issue = 'generation_split' AND r.status IN ('approved', 'corrected')
  AND NOT EXISTS (SELECT 1 FROM kb.generation c WHERE c.split_from = r.entity_key::bigint)"""):
        year = int(((corrected if status == "corrected" else proposed) or {}).get("year_from"))
        split_generation(cur, gen_id, year)
    # Corrected or approved values become manual evidence, which no rule overrides.
    for etype, eid, fname, status, proposed, current, corrected, case_id in _load(cur, """
SELECT entity_type, entity_key::bigint, field, status, proposed_value, current_value, corrected_value, id
FROM kb.review_item WHERE issue = 'spec_disagreement' AND status IN ('approved', 'corrected')"""):
        value = corrected if status == "corrected" else (proposed if proposed is not None else current)
        cur.execute("""
INSERT INTO kb.spec_evidence (entity_type, entity_id, field, source_kind, value, status, detail)
VALUES (%s, %s, %s, 'manual', %s, 'accepted', %s)
ON CONFLICT (entity_type, entity_id, field, source_kind) DO NOTHING""",
                    (etype, eid, fname, json.dumps(value), json.dumps({"review_item_id": case_id})))
    # Approved evolution notes.
    for case_id, vid, fname, status, proposed, corrected in _load(cur, """
SELECT id, entity_key::bigint, field, status, proposed_value, corrected_value FROM kb.review_item
WHERE issue = 'evolution_note' AND status IN ('approved', 'corrected')"""):
        note = (corrected if status == "corrected" else proposed) or {}
        cur.execute("""
INSERT INTO kb.evolution_note (variant_id, field, value, year_from, source, review_item_id)
VALUES (%s, %s, %s, %s, 'manual', %s) ON CONFLICT DO NOTHING""",
                    (vid, fname, json.dumps(note.get("value")), int(note["year_from"]), case_id))


# --- the run --------------------------------------------------------------------------------
def build(conn) -> dict:
    with conn.transaction(), conn.cursor() as cur:
        take_writer_lock(cur)
        _apply_decisions(cur)
        cases = Cases()
        body_names = dict(_load(cur, "SELECT code, name_es FROM kb.body_style"))

        listings: list[_Listing] = []
        for (site, lid, country, year, model_id, mstatus, body, fuel, trans, drive, disp, cyl, hp, doors,
             seats, trim, specs) in _load(cur, """
SELECT l.source_site, l.listing_id, l.country_code, l.model_year, l.model_id, m.status, l.body_style_code,
       l.fuel_type_code, l.transmission_type_code, l.drivetrain_code, l.engine_displacement_l, l.engine_cylinders,
       l.horsepower_hp, l.doors, l.seats, l.trim_name, l.specs
FROM kb.clean_listing l LEFT JOIN kb.model m ON m.id = l.model_id
WHERE l.excluded_reason IS NULL ORDER BY l.source_site, l.listing_id"""):
            disp_r = round(float(disp), 1) if disp is not None else None
            votes = dict(specs or {})
            votes.update({"horsepower_hp": hp, "engine_cylinders": cyl, "doors": doors, "seats": seats})
            for column, schema_field in LISTING_FIELD_OF.items():      # vote under the column's name
                if schema_field in votes:
                    votes[column] = votes.pop(schema_field)
            listings.append(_Listing(site, lid, country, year, model_id, mstatus == "accepted", body,
                                     (fuel, trans, drive, disp_r, cyl if disp_r is None else None), trim, votes))

        # 2. generations ---------------------------------------------------------------------
        model_names = dict(_load(cur, "SELECT id, name FROM kb.model"))
        gens: dict[int, list[_Generation]] = defaultdict(list)
        for gid, mid, body, yf, yt, status in _load(cur, """
SELECT id, model_id, body_style_code, year_from, year_to, status FROM kb.generation WHERE status <> 'rejected'
ORDER BY id"""):
            gens[mid].append(_Generation(gid, mid, body, yf, yt, status))
        parents = Counter(r[0] for r in _load(cur, "SELECT split_from FROM kb.generation WHERE split_from IS NOT NULL"))
        bodies: dict[int, set] = defaultdict(set)
        models_seen: set[int] = set()
        for l in listings:
            if l.model_ok:
                models_seen.add(l.model_id)
                if l.body:
                    bodies[l.model_id].add(l.body)
        for mid in sorted(models_seen):
            wanted = sorted(bodies[mid]) or [None]
            have = {g.body for g in gens[mid]}
            for body in wanted:
                if body in have or (body is None and gens[mid]):
                    continue
                name = model_names[mid] + (f" ({body_names[body]})" if body and body != "Motorcycle" else "")
                cur.execute("INSERT INTO kb.generation (model_id, body_style_code, name) VALUES (%s, %s, %s) "
                            "RETURNING id", (mid, body, name))
                gens[mid].append(_Generation(cur.fetchone()[0], mid, body, None, None, "provisional"))
        for gl in gens.values():
            for g in gl:
                g.split_children = parents.get(g.id, 0)

        for l in listings:
            if not l.model_ok:
                l.reason = "model_not_accepted"
                continue
            cands = [g for g in gens[l.model_id] if (l.body is None or g.body == l.body) and g.covers(l.year)]
            if l.body is None and len({g.body for g in cands}) > 1:
                l.reason = "ambiguous_body"
                continue
            if not cands:
                l.reason = "no_generation_for_year"
                continue
            # a split generation's halves have ranges: the narrowest covering one wins
            g = min(cands, key=lambda g: ((g.year_to or 9999) - (g.year_from or 0), g.id))
            l.generation = g.id
            g.listings.append(l)

        # 3. powertrains ---------------------------------------------------------------------
        # Rejected powertrains (a person's decision) never get listings and are never recreated:
        # a listing whose only match is one of them stays unassigned (powertrain_rejected).
        pts: dict[int, list[dict]] = defaultdict(list)
        rejected_pts: dict[int, list[dict]] = defaultdict(list)
        for pid, gid, mk, disp, cyl, fuel, trans, drive, pstatus in _load(cur, """
SELECT id, generation_id, match_key, engine_displacement_l, engine_cylinders, fuel_type_code,
       transmission_type_code, drivetrain_code, status FROM kb.powertrain ORDER BY id"""):
            (rejected_pts if pstatus == "rejected" else pts)[gid].append(
                {"id": pid, "match_key": mk, "fuel": fuel, "trans": trans, "drive": drive,
                 "disp": float(disp) if disp is not None else None, "cyl": cyl})
        all_gens = [g for gl in gens.values() for g in gl]
        for g in all_gens:
            keys = Counter(l.key for l in g.listings)
            order = sorted(keys, key=lambda k: (-sum(v is not None for v in k), -keys[k], match_key(k)))
            resolved: dict[tuple, Optional[int]] = {}
            rejected_keys: set[tuple] = set()
            for k in order:
                mk = match_key(k)
                if any(p["match_key"] == mk for p in rejected_pts[g.id]):
                    resolved[k] = None                     # exactly the rejected one
                    rejected_keys.add(k)
                    continue
                exact = [p for p in pts[g.id] if p["match_key"] == mk]
                comp = exact or [p for p in pts[g.id] if _compatible(k, p)]
                if len(comp) == 1:
                    resolved[k] = comp[0]["id"]
                elif not comp and any(_compatible(k, p) for p in rejected_pts[g.id]):
                    resolved[k] = None                     # its only match was rejected
                    rejected_keys.add(k)
                elif not comp:
                    fuel, trans, drive, disp, cyl = k
                    cur.execute("""
INSERT INTO kb.powertrain (generation_id, match_key, fuel_type_code, transmission_type_code, drivetrain_code,
                           engine_displacement_l, engine_cylinders)
VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""", (g.id, mk, fuel, trans, drive, disp, cyl))
                    pid = cur.fetchone()[0]
                    pts[g.id].append({"id": pid, "match_key": mk, "fuel": fuel, "trans": trans, "drive": drive,
                                      "disp": disp, "cyl": cyl})
                    resolved[k] = pid
                else:
                    resolved[k] = None
            for l in g.listings:
                l.powertrain = resolved[l.key]
                if l.powertrain is None:
                    l.reason = "powertrain_rejected" if l.key in rejected_keys else "ambiguous_powertrain"

        # 4. commercial variants ---------------------------------------------------------------
        # A rejected variant is never recreated (it stays in `variants`) nor given listings:
        # they keep their generation and powertrain and stay unassigned (variant_rejected).
        variants, rejected_variants = {}, set()
        for vid, g, p, c, t, vstatus in _load(cur, """
SELECT id, generation_id, powertrain_id, country_code, trim_key, status FROM kb.commercial_variant"""):
            variants[(g, p, c, t)] = vid
            if vstatus == "rejected":
                rejected_variants.add(vid)
        trim_names: dict[tuple, Counter] = defaultdict(Counter)
        for l in listings:
            if l.powertrain:
                trim_names[(l.generation, l.powertrain, l.country, compact_key(l.trim))][l.trim] += 1
        for vkey in sorted(trim_names, key=str):
            if vkey not in variants:
                name = trim_names[vkey].most_common(1)[0][0] if vkey[3] else None
                cur.execute("""
INSERT INTO kb.commercial_variant (generation_id, powertrain_id, country_code, trim_name, trim_key)
VALUES (%s, %s, %s, %s, %s) RETURNING id""", (*vkey[:3], name, vkey[3]))
                variants[vkey] = cur.fetchone()[0]
        for l in listings:
            if l.powertrain:
                vid = variants[(l.generation, l.powertrain, l.country, compact_key(l.trim))]
                if vid in rejected_variants:
                    l.reason = "variant_rejected"
                else:
                    l.variant = vid

        # counts and observed years
        def years(ls):
            ys = [l.year for l in ls if l.year]
            return (min(ys), max(ys)) if ys else (None, None)
        by = {"generation": defaultdict(list), "powertrain": defaultdict(list), "variant": defaultdict(list)}
        for l in listings:
            for level in by:
                eid = getattr(l, level)
                if eid:
                    by[level][eid].append(l)
        cur.execute("UPDATE kb.generation SET listings = 0, observed_year_from = NULL, observed_year_to = NULL")
        cur.executemany("UPDATE kb.generation SET listings = %s, observed_year_from = %s, observed_year_to = %s "
                        "WHERE id = %s", [(len(ls), *years(ls), gid) for gid, ls in by["generation"].items()])
        cur.execute("UPDATE kb.powertrain SET listings = 0")
        cur.executemany("UPDATE kb.powertrain SET listings = %s WHERE id = %s",
                        [(len(ls), pid) for pid, ls in by["powertrain"].items()])
        cur.execute("UPDATE kb.commercial_variant SET listings = 0, sale_year_from = NULL, sale_year_to = NULL")
        cur.executemany("UPDATE kb.commercial_variant SET listings = %s, sale_year_from = %s, sale_year_to = %s "
                        "WHERE id = %s", [(len(ls), *years(ls), vid) for vid, ls in by["variant"].items()])

        # 5. evidence from listings ---------------------------------------------------------------
        evidence = []
        voting = {"generation": GENERATION_FROM_LISTINGS, "powertrain": POWERTRAIN_FROM_LISTINGS,
                  "variant": VARIANT_FROM_LISTINGS}
        for level, fields_ in voting.items():
            for eid, ls in by[level].items():
                for f in fields_:
                    vals = [l.votes.get(f) for l in ls if _plausible(f, l.votes.get(f))]
                    if f in BOOLEAN:
                        vals = [bool(v) for v in vals]
                    r = (_equipment if f in EQUIPMENT_FIELDS else _mechanical)(vals)
                    if not r:
                        continue
                    detail = {"counts": {str(k): n for k, n in r["counts"].most_common(10)}}
                    evidence.append((level, eid, f, json.dumps(r["value"]), r["status"], r["support"],
                                     round(r["agreement"], 3), json.dumps(detail)))
                    if r["disagree"]:
                        cases.add(level, eid, "spec_disagreement", field_name=f, current=r["value"],
                                  proposed=r["value"], evidence=detail, listings=r["support"])
        cur.execute("DELETE FROM kb.spec_evidence WHERE source_kind = 'listings'")
        with cur.copy("COPY kb.spec_evidence (entity_type, entity_id, field, value, status, support, agreement, "
                      "detail, source_kind) FROM STDIN") as copy:
            for row in evidence:
                copy.write_row((*row, "listings"))

        # 6. publish ------------------------------------------------------------------------------
        best: dict[tuple, tuple] = {}
        for etype, eid, fname, kind, value in _load(cur, """
SELECT entity_type, entity_id, field, source_kind, value FROM kb.spec_evidence WHERE status = 'accepted'"""):
            rank = SOURCE_RANK[kind]
            k = (etype, eid, fname)
            if k not in best or rank < best[k][0]:
                best[k] = (rank, value, kind)
        published = Counter()
        for etype, (table, columns) in TABLES.items():
            ids = [r[0] for r in _load(cur, f"SELECT id FROM {table}")]
            rows = []
            for eid in ids:
                vals = []
                for c in columns:
                    hit = best.get((etype, eid, c))
                    vals.append(hit[1] if hit else None)
                    if hit:
                        published[f"{etype}.{hit[2]}"] += 1
                rows.append((*vals, eid))
            sets = ", ".join(f"{c} = %s" for c in columns)
            cur.executemany(f"UPDATE {table} SET {sets}, updated_at = now() WHERE id = %s", rows)

        # 7. proposals ---------------------------------------------------------------------------
        for g in all_gens:
            if g.status != "provisional" or g.split_children or not g.listings:
                continue
            with_disp = [l for l in g.listings if l.key[3] is not None]
            signature, src = ("displacement", with_disp) if len(with_disp) >= 2 * SPLIT_MIN_LISTINGS else \
                ("cylinders", [l for l in g.listings if l.votes.get("engine_cylinders")])
            by_year: dict[int, Counter] = defaultdict(Counter)
            for l in src:
                if l.year:
                    by_year[l.year][str(l.key[3] if signature == "displacement" else l.votes["engine_cylinders"])] += 1
            hit = _split_year(by_year)
            if hit:
                year, before, after = hit
                cases.add("generation", g.id, "generation_split", proposed={"year_from": year},
                          evidence={"signature": signature, "before": before, "after": after,
                                    "model": model_names[g.model_id]},
                          listings=len(g.listings))
        notes = {(v, f) for v, f in _load(cur, "SELECT variant_id, field FROM kb.evolution_note")}
        for vid, ls in by["variant"].items():
            for f in VARIANT_FROM_LISTINGS:
                if f not in BOOLEAN or (vid, f) in notes:
                    continue
                by_year = defaultdict(Counter)
                for l in ls:
                    v = l.votes.get(f)
                    if v is not None and l.year:
                        by_year[l.year][bool(v)] += 1
                hit = _evolution(by_year)
                if hit:
                    year, vb, va, nb, na = hit
                    cases.add("variant", vid, "evolution_note", field_name=f, current=vb,
                              proposed={"value": va, "year_from": year},
                              evidence={"before": nb, "after": na}, listings=nb + na)

        # listing_level and cases ----------------------------------------------------------------
        cur.execute("DELETE FROM kb.listing_level")
        with cur.copy("COPY kb.listing_level (source_site, listing_id, generation_id, powertrain_id, variant_id, "
                      "unassigned_reason) FROM STDIN") as copy:
            for l in listings:
                copy.write_row((l.site, l.listing_id, l.generation, l.powertrain, l.variant,
                                None if l.variant else l.reason))
        write_cases(cur, cases, BUILD_ISSUES)
        # 8. final records: what each listing inherits, after everything above is published
        final = write_final(cur)

        summary = _summary(cur, listings, published)
        summary["final_listings"] = final
        cur.execute("INSERT INTO kb.build_run (summary) VALUES (%s) RETURNING id", (json.dumps(summary),))
        summary["run_id"] = cur.fetchone()[0]
    return summary


def _summary(cur, listings: list[_Listing], published: Counter) -> dict:
    def grouped(sql: str) -> dict:
        return {str(k): v for k, v in _load(cur, sql)}
    return {
        "listings": len(listings),
        "assigned": sum(1 for l in listings if l.variant),
        "unassigned": dict(sorted(Counter(l.reason for l in listings if not l.variant).items())),
        "generations": grouped("SELECT status, count(*) FROM kb.generation WHERE listings > 0 GROUP BY 1 ORDER BY 1"),
        "powertrains": grouped("SELECT CASE WHEN n <= 3 THEN n::text ELSE '4+' END, count(*) FROM "
                               "(SELECT g.id, count(p.id) n FROM kb.generation g JOIN kb.powertrain p "
                               "ON p.generation_id = g.id AND p.listings > 0 GROUP BY g.id) x GROUP BY 1 ORDER BY 1"),
        "variants": grouped("SELECT CASE WHEN trim_unknown THEN 'trim_unknown' ELSE 'known_trim' END, count(*) "
                            "FROM kb.commercial_variant WHERE listings > 0 GROUP BY 1 ORDER BY 1"),
        "variants_by_country": grouped("SELECT country_code, count(*) FROM kb.commercial_variant WHERE listings > 0 "
                                       "GROUP BY 1 ORDER BY 1"),
        "published_values": dict(sorted(published.items())),
        "review_pending": grouped("SELECT issue, count(*) FROM kb.review_item WHERE status = 'pending' "
                                  "GROUP BY 1 ORDER BY 1"),
    }
