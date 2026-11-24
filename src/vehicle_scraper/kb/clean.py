"""``kb clean``: from ``staging.raw_listing`` (current versions) to ``kb.clean_listing``.

Per listing, in order:

1. **Make**: spelling-insensitive alias (``compact_key``) to the make list
   (``config/kb/makes.yaml``). A make not on the list is created as ``pending_review`` with an
   ``unknown_make`` case; a listing without a make gets ``missing_make``.
2. **Scope**: excluded, with a reason, when the make builds something out of scope (heavy,
   machinery, ...), the name says ATV or motocarro/mototaxi, the body is a heavy truck, or the model year is outside
   1990 .. current year + 1. Excluded listings keep their row.
3. **Model**: mechanical words leave the name (``'RAV4 HYBRID 4X4'`` -> RAV4 + Hybrid + 4WD);
   model families split by the version's number (KTM Duke + "390" = Duke 390). A new name is
   accepted with >= 5 listings or listings on >= 2 sites, else ``weak_model``. A name that is
   only attributes (``'1.3'``) gets ``model_is_attributes``.
4. **Trim**: the version without mechanical words; one spelling per model.
5. **Fields**: the listing's structured value wins; a word in the model or version only fills
   an empty field (``provenance``). When both exist and disagree the structured value stays
   and a ``field_conflict`` case is opened. Implausible values stay and get a case too.

Everything runs in one transaction under the writer lock; ``kb.clean_listing`` is rebuilt, the
identity tables only grow, and manual rows (``source = 'manual'``) are never touched.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from ..models import BOOLEAN_FIELDS, SCHEMA_FIELDS
from .db import take_writer_lock
from .identity import (EXCLUDED_CLASSES, SEED_PATH, compact_key, display_name, load_seed, slugify,
                       split_number, split_tokens)

CLEAN_ISSUES = ("unknown_make", "missing_make", "weak_model", "model_is_attributes", "field_conflict",
                "implausible_value")      # the review cases this command opens and closes
MIN_YEAR = 1990
STRONG_LISTINGS = 5             # a model name seen this often is accepted by rule ...
STRONG_SITES = 2                # ... or seen on this many sites
DISPLACEMENT_TOLERANCE = 0.1    # litres: 1.6 vs 1.65 is the same engine

ATV_RE = re.compile(r"\b(cuatrimotos?|cuadrimotos?|atv|utv|side ?by ?side|rzr|four ?trax|yfm|yfz)\b")
THREE_WHEELER_RE = re.compile(r"\b(motocarros?|mototaxis?|motocargueros?|tricimotos?|trimotos?|torito|tuk ?tuk)\b")
CHASSIS_RE = re.compile(r"\bc/c\b|cab ?/ ?chassis|chassis ?cab|\bchasis\b|\bchassis\b")

# Schema fields kept as typed, catalog-checked columns of kb.clean_listing.
COLUMNS = {"body_style": "body_style_code", "fuel_type": "fuel_type_code",
           "transmission_type": "transmission_type_code", "drivetrain": "drivetrain_code",
           "engine_displacement_l": "engine_displacement_l", "engine_cylinders": "engine_cylinders",
           "horsepower_hp": "horsepower_hp", "doors": "doors", "seats": "seats"}
IDENTITY_FIELDS = {"vehicle_type", "make", "model", "trim", "model_year"}
SPEC_FIELDS = [f for f in SCHEMA_FIELDS if f not in IDENTITY_FIELDS and f not in COLUMNS]
# Values that don't contradict each other: "4x4" vs AWD, or "4x2" vs a stated axle.
COMPATIBLE = [{"AWD", "4WD"}, {"2WD", "FWD"}, {"2WD", "RWD"}]
# A name that only adds detail to a generic structured value refines it (provenance says so):
# listing "Automatic" + version "CVT" -> CVT; listing "2WD" + version "FWD" -> FWD.
REFINES = {("transmission_type", "Automatic"): {"CVT", "DCT"}, ("drivetrain", "2WD"): {"FWD", "RWD"}}
# The CHECK ranges of kb.clean_listing's numeric columns; a value outside stays out of the
# column and gets an implausible_value case instead of failing the run.
BOUNDS = {"engine_displacement_l": (0.04, 20), "engine_cylinders": (1, 16), "horsepower_hp": (1, 2000),
          "doors": (0, 6), "seats": (1, 80)}
# A displacement read from a car's name ("1.6") is only believed in this range ("0.0", "9.9" aren't).
CAR_NAME_DISPLACEMENT = (0.6, 8.5)
CLASS_EXCLUSIONS = set(EXCLUDED_CLASSES.values()) | {"ThreeWheeler"}   # for what they are, not their year


def _same(field_name: str, a, b) -> bool:
    if field_name == "engine_displacement_l":
        return abs(float(a) - float(b)) <= DISPLACEMENT_TOLERANCE
    return a == b or any({a, b} <= pair for pair in COMPATIBLE)


@dataclass
class _Listing:
    site: str
    listing_id: str
    version: int
    country: str
    data: dict
    make_id: Optional[int] = None
    model_key: Optional[str] = None
    model_name: Optional[str] = None
    model_attrs: dict = field(default_factory=dict)
    trim_label: Optional[str] = None
    trim_attrs: dict = field(default_factory=dict)
    vehicle_class: Optional[str] = None
    excluded: Optional[str] = None

    @property
    def key(self) -> str:
        return f"{self.site}:{self.listing_id}"


class Cases:
    """Review cases found in this run: (entity_type, entity_key, field, issue) -> payload."""

    def __init__(self):
        self.items: dict[tuple, dict] = {}

    def add(self, entity_type: str, entity_key, issue: str, *, field_name: str = "", current=None,
            proposed=None, evidence: Optional[dict] = None, listings: int = 1) -> None:
        self.items[(entity_type, str(entity_key), field_name, issue)] = {
            "current": current, "proposed": proposed, "evidence": evidence or {}, "listings": listings}


def write_cases(cur, cases: Cases, issues: tuple[str, ...]) -> None:
    """Upsert this run's cases. A decided case keeps its decision (never asked again); an
    obsolete one that shows up again is pending again; a pending case of ``issues`` this run
    didn't see becomes obsolete. Cases of other commands are left alone."""
    if cases.items:
        cur.executemany("""
INSERT INTO kb.review_item (entity_type, entity_key, field, issue, current_value, proposed_value, evidence,
                            listings_affected)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (entity_type, entity_key, field, issue) DO UPDATE SET
    current_value = EXCLUDED.current_value, proposed_value = EXCLUDED.proposed_value,
    evidence = EXCLUDED.evidence, listings_affected = EXCLUDED.listings_affected, updated_at = now(),
    status = CASE WHEN kb.review_item.status = 'obsolete' THEN 'pending' ELSE kb.review_item.status END""",
                        [(etype, ekey, fname, issue, json.dumps(c["current"], default=str),
                          json.dumps(c["proposed"], default=str), json.dumps(c["evidence"], default=str),
                          c["listings"])
                         for (etype, ekey, fname, issue), c in sorted(cases.items.items())])
    cur.execute("UPDATE kb.review_item SET status = 'obsolete', updated_at = now() "
                "WHERE status = 'pending' AND updated_at < now() AND issue = ANY(%s)", (list(issues),))


# --- identity tables ------------------------------------------------------------------------
def _sync_seed(cur, seed: dict) -> None:
    """Insert seed makes and aliases that aren't there yet. Never changes an existing row."""
    for m in seed["makes"]:
        cur.execute("""
INSERT INTO kb.make (name, slug, country_of_origin, default_class, status, source)
VALUES (%s, %s, %s, %s, 'accepted', 'seed') ON CONFLICT (slug) DO NOTHING""",
                    (m["name"], slugify(m["name"]), m.get("country"), m["class"]))
        for spelling in [m["name"], *(m.get("aliases") or [])]:
            cur.execute("""
INSERT INTO kb.make_alias (alias_key, make_id, source)
SELECT %s, id, 'seed' FROM kb.make WHERE slug = %s ON CONFLICT (alias_key) DO NOTHING""",
                        (compact_key(spelling), slugify(m["name"])))


def _apply_decisions(cur) -> None:
    """Decided make/model cases fix the row for good (source becomes 'manual', which the rules
    never change). Approved make: accepted with the reviewer's class. Corrected make: merged
    into an existing make (its aliases move). Corrected model: merged into the model of that
    name in the same make, or renamed when there is none."""
    for table, issue in (("make", "unknown_make"), ("model", "weak_model")):
        cur.execute(f"""
UPDATE kb.{table} t SET status = CASE r.status WHEN 'rejected' THEN 'rejected' ELSE 'accepted' END,
       source = 'manual', updated_at = now()
FROM kb.review_item r
WHERE r.entity_type = %s AND r.issue = %s AND r.status IN ('approved', 'rejected')
  AND r.entity_key = t.id::text AND t.source <> 'manual'""", (table, issue))
    cur.execute("""
UPDATE kb.make t SET default_class = r.corrected_value->>'class'
FROM kb.review_item r
WHERE r.entity_type = 'make' AND r.issue = 'unknown_make' AND r.status = 'approved'
  AND r.corrected_value ? 'class' AND r.entity_key = t.id::text
  AND t.default_class IS DISTINCT FROM r.corrected_value->>'class'""")
    for old, target in _load(cur, """
SELECT r.entity_key::bigint, (r.corrected_value->>'merge')::bigint FROM kb.review_item r
JOIN kb.make k ON k.id::text = r.entity_key
WHERE r.entity_type = 'make' AND r.issue = 'unknown_make' AND r.status = 'corrected' AND k.status <> 'rejected'"""):
        cur.execute("UPDATE kb.make_alias SET make_id = %s, source = 'manual' WHERE make_id = %s", (target, old))
        cur.execute("UPDATE kb.make SET status = 'rejected', source = 'manual', updated_at = now() WHERE id = %s",
                    (old,))
    for old, make_id, name in _load(cur, """
SELECT m.id, m.make_id, r.corrected_value->>'name' FROM kb.review_item r JOIN kb.model m ON m.id::text = r.entity_key
WHERE r.entity_type = 'model' AND r.issue = 'weak_model' AND r.status = 'corrected'
  AND m.merged_into IS NULL AND m.status <> 'rejected'"""):
        key = compact_key(name)
        cur.execute("SELECT model_id FROM kb.model_alias WHERE make_id = %s AND alias_key = %s AND model_id <> %s",
                    (make_id, key, old))
        row = cur.fetchone()
        if row:                                   # an existing model: merge into it
            target = row[0]
            cur.execute("UPDATE kb.model_alias SET model_id = %s, source = 'manual' WHERE model_id = %s", (target, old))
            cur.execute("UPDATE kb.model SET merged_into = %s, status = 'rejected', source = 'manual', "
                        "updated_at = now() WHERE id = %s", (target, old))
            cur.execute("UPDATE kb.model SET status = 'accepted', source = 'manual', updated_at = now() "
                        "WHERE id = %s AND status <> 'accepted'", (target,))
        else:                                     # a new name: rename (idempotent)
            cur.execute("UPDATE kb.model SET name = %s, slug = %s, status = 'accepted', source = 'manual', "
                        "updated_at = now() WHERE id = %s AND (name <> %s OR source <> 'manual')",
                        (name, slugify(name), old, name))
            cur.execute("INSERT INTO kb.model_alias (make_id, alias_key, model_id, source) VALUES (%s, %s, %s, "
                        "'manual') ON CONFLICT (make_id, alias_key) DO UPDATE SET model_id = EXCLUDED.model_id, "
                        "source = 'manual'", (make_id, key, old))


DROP = object()     # a listing override that removes the field's value


def _listing_overrides(cur) -> tuple[dict, dict, dict]:
    """Decided listing cases: (make name by listing, model name by listing,
    {(listing, field): value or DROP})."""
    makes, models, fields_ = {}, {}, {}
    for key, fname, issue, status, proposed, current, corrected in _load(cur, """
SELECT entity_key, field, issue, status, proposed_value, current_value, corrected_value FROM kb.review_item
WHERE entity_type = 'listing' AND status IN ('approved', 'rejected', 'corrected')"""):
        if issue == "missing_make" and status == "corrected":
            makes[key] = corrected["make"]
        elif issue == "model_is_attributes" and status == "corrected":
            models[key] = corrected["model"]
        elif issue == "field_conflict":
            fields_[(key, fname)] = {"approved": proposed, "rejected": current, "corrected": corrected}[status]
        elif issue == "implausible_value" and status in ("rejected", "corrected"):
            fields_[(key, fname)] = DROP if status == "rejected" else corrected
    return makes, models, fields_


def _load(cur, sql: str) -> list[tuple]:
    cur.execute(sql)
    return cur.fetchall()


# --- the run --------------------------------------------------------------------------------
def clean(conn, seed_path: Path = SEED_PATH, today: Optional[date] = None) -> dict:
    today = today or date.today()
    max_year = today.year + 1
    seed = load_seed(seed_path)
    with conn.transaction(), conn.cursor() as cur:
        take_writer_lock(cur)
        _sync_seed(cur, seed)
        _apply_decisions(cur)
        over_make, over_model, over_fields = _listing_overrides(cur)
        over_by_listing: dict[str, dict] = defaultdict(dict)
        for (key, f), v in over_fields.items():
            over_by_listing[key][f] = v
        cases = Cases()

        listings = [_Listing(s, i, v, c, d) for s, i, v, c, d in _load(cur, """
SELECT source_site, listing_id, version, country_code, data FROM staging.current_listing
ORDER BY source_site, listing_id""")]

        # 1. makes ---------------------------------------------------------------------------
        make_alias = dict(_load(cur, "SELECT alias_key, make_id FROM kb.make_alias"))
        # Every spelling seen, by key: new makes are created from these, and a make still
        # pending review keeps its case open on every run (not only the run that found it).
        seen: dict[str, dict] = defaultdict(lambda: {"spellings": Counter(), "sites": Counter(),
                                                     "models": Counter()})
        for l in listings:
            raw = (l.data.get("make") or "").strip()
            k = compact_key(raw)
            if not k:
                continue
            u = seen[k]
            u["spellings"][raw] += 1
            u["sites"][l.site] += 1
            u["models"][str(l.data.get("model") or "")] += 1
        for k, u in sorted(seen.items()):
            if k in make_alias:
                continue
            name = display_name(u["spellings"])
            cur.execute("""
INSERT INTO kb.make (name, slug, status, source) VALUES (%s, %s, 'pending_review', 'rule')
ON CONFLICT (slug) DO UPDATE SET updated_at = kb.make.updated_at RETURNING id""", (name, slugify(name)))
            make_id = cur.fetchone()[0]
            cur.execute("INSERT INTO kb.make_alias (alias_key, make_id, source) VALUES (%s, %s, 'rule') "
                        "ON CONFLICT (alias_key) DO NOTHING", (k, make_id))
            make_alias[k] = make_id
        makes = {i: {"name": n, "class": c, "status": st} for i, n, c, st in _load(cur, """
SELECT id, name, default_class, status FROM kb.make""")}
        pending_makes: dict[int, dict] = defaultdict(lambda: {"spellings": Counter(), "sites": Counter(),
                                                              "models": Counter()})
        for k, u in seen.items():
            mid = make_alias[k]
            if makes[mid]["status"] == "pending_review":
                for part in ("spellings", "sites", "models"):
                    pending_makes[mid][part].update(u[part])
        for mid, u in pending_makes.items():
            cases.add("make", mid, "unknown_make", current=makes[mid]["name"],
                      evidence={"spellings": dict(u["spellings"]), "sites": dict(u["sites"]),
                                "models": dict(u["models"].most_common(10))},
                      listings=sum(u["spellings"].values()))

        families = {}
        for f in seed["split_models"]:
            mid = make_alias.get(compact_key(f["make"]))
            if mid:
                families[(mid, compact_key(f["model"]))] = f["model"]

        # 2. scope, model and trim names ----------------------------------------------------
        for l in listings:
            d = l.data
            raw_make = (d.get("make") or "").strip()
            if not raw_make:
                cases.add("listing", l.key, "missing_make", evidence={"model": d.get("model"), "trim": d.get("trim")})
            raw_make = over_make.get(l.key) or raw_make              # a reviewer's make wins
            if raw_make:
                l.make_id = make_alias.get(compact_key(raw_make))
            mclass = makes[l.make_id]["class"] if l.make_id else None
            vt = d.get("vehicle_type")
            moto = vt == "Motorcycle" or (not vt and mclass == "motorcycle")
            l.vehicle_class = "motorcycle" if moto else "car"
            names = f"{d.get('model') or ''} {d.get('trim') or ''}".lower()
            year = d.get("model_year")
            if mclass in EXCLUDED_CLASSES:
                l.excluded = EXCLUDED_CLASSES[mclass]
            elif ATV_RE.search(names):
                l.excluded = "ATV"
            elif THREE_WHEELER_RE.search(names):
                l.excluded = "ThreeWheeler"
            elif d.get("body_style") == "Truck" and not CHASSIS_RE.search(names):
                l.excluded = "Heavy"
            elif year is None or not (1900 <= int(year) <= max_year):
                l.excluded = "YearOutOfRange"
            elif int(year) < MIN_YEAR:
                l.excluded = "Classic"
            if l.excluded or not l.make_id or makes[l.make_id]["status"] == "rejected":
                continue                                   # a rejected make never gets models
            l.model_name, l.model_attrs = split_tokens(d.get("model"), model=True, moto=moto)
            if l.key in over_model:                        # a reviewer named the model
                l.model_name, l.model_attrs = over_model[l.key], {}
            l.trim_label, l.trim_attrs = split_tokens(d.get("trim"), moto=moto)
            if not l.model_name:
                cases.add("listing", l.key, "model_is_attributes", current=d.get("model"),
                          evidence={"make": raw_make, "trim": d.get("trim"), "year": year})
                continue
            fam = families.get((l.make_id, compact_key(l.model_name)))
            if fam:
                number, rest = split_number(l.trim_label)
                if number:
                    l.model_name, l.trim_label = f"{fam} {number}", rest
            l.model_key = compact_key(l.model_name)

        # 3. models --------------------------------------------------------------------------
        model_alias = {(m, k): i for m, k, i in _load(cur, "SELECT make_id, alias_key, model_id FROM kb.model_alias")}
        groups: dict[tuple, dict] = defaultdict(lambda: {"spellings": Counter(), "sites": Counter(),
                                                         "classes": Counter(), "trims": Counter(), "years": Counter()})
        for l in listings:
            if l.model_key:
                g = groups[(l.make_id, l.model_key)]
                g["spellings"][l.model_name] += 1
                g["sites"][l.site] += 1
                g["classes"][l.vehicle_class] += 1
                g["trims"][l.trim_label or ""] += 1
                g["years"][l.data.get("model_year")] += 1
        for (make_id, k), g in sorted(groups.items()):
            n_listings, n_sites = sum(g["sites"].values()), len(g["sites"])
            strong = n_listings >= STRONG_LISTINGS or n_sites >= STRONG_SITES
            vclass = g["classes"].most_common(1)[0][0]
            model_id = model_alias.get((make_id, k))
            if model_id is None:
                name = display_name(g["spellings"])
                cur.execute("""
INSERT INTO kb.model (make_id, name, slug, vehicle_class_code, status, source)
VALUES (%s, %s, %s, %s, %s, 'rule')
ON CONFLICT (make_id, slug) DO UPDATE SET updated_at = kb.model.updated_at RETURNING id""",
                            (make_id, name, slugify(name), vclass, "accepted" if strong else "pending_review"))
                model_id = cur.fetchone()[0]
                cur.execute("INSERT INTO kb.model_alias (make_id, alias_key, model_id, source) "
                            "VALUES (%s, %s, %s, 'rule') ON CONFLICT DO NOTHING", (make_id, k, model_id))
                model_alias[(make_id, k)] = model_id
            cur.execute("""
UPDATE kb.model SET listings = %s, sites = %s, updated_at = now(),
       status = CASE WHEN source = 'rule' AND status = 'pending_review' AND %s THEN 'accepted' ELSE status END
WHERE id = %s RETURNING status, name""", (n_listings, n_sites, strong, model_id))
            status, name = cur.fetchone()
            if status == "pending_review":
                cases.add("model", model_id, "weak_model", current=name,
                          evidence={"make": makes[make_id]["name"], "spellings": dict(g["spellings"]),
                                    "sites": dict(g["sites"]), "trims": dict(g["trims"].most_common(10)),
                                    "years": {str(y): n for y, n in sorted(g["years"].items(), key=str)}},
                          listings=n_listings)
        # models no longer seen keep their row; their counts go to zero
        seen_models = {model_alias[(l.make_id, l.model_key)] for l in listings if l.model_key}
        cur.execute("UPDATE kb.model SET listings = 0, sites = 0 WHERE NOT (id = ANY(%s)) AND listings > 0",
                    (list(seen_models),))

        # one spelling per trim within a model
        trim_spellings: dict[tuple, Counter] = defaultdict(Counter)
        for l in listings:
            if l.model_key and l.trim_label:
                trim_spellings[(model_alias[(l.make_id, l.model_key)], compact_key(l.trim_label))][l.trim_label] += 1
        trim_names = {key: display_name(c) for key, c in trim_spellings.items()}

        # 4. fields and rows -----------------------------------------------------------------
        filled, conflicts, excluded = Counter(), Counter(), Counter()
        rows = []
        for l in listings:
            d = l.data
            model_id = model_alias.get((l.make_id, l.model_key)) if l.model_key else None
            trim = trim_names.get((model_id, compact_key(l.trim_label))) if model_id and l.trim_label else None
            values, prov = {}, {}
            for f in COLUMNS:
                v = d.get(f)
                if v not in (None, ""):
                    values[f], prov[f] = v, "listing"
            if values.get("body_style") == "Truck" and CHASSIS_RE.search(f"{d.get('model')} {d.get('trim')}".lower()):
                values["body_style"], prov["body_style"] = "Pickup", "chassis_cab"   # chassis cab = pickup
            if l.vehicle_class == "motorcycle" and "body_style" not in values:
                values["body_style"], prov["body_style"] = "Motorcycle", "vehicle_class"
            specs = {}
            if not l.excluded:
                for source, attrs in (("model_text", l.model_attrs), ("trim_text", l.trim_attrs)):
                    for f, text_value in attrs.items():
                        if f == "turbo":
                            specs.setdefault("turbo", True)
                            prov.setdefault("turbo", source)
                            continue
                        if (f == "engine_displacement_l" and l.vehicle_class == "car"
                                and not CAR_NAME_DISPLACEMENT[0] <= text_value <= CAR_NAME_DISPLACEMENT[1]):
                            continue
                        if f not in values:
                            values[f], prov[f] = text_value, source
                            filled[f] += 1
                        elif prov[f] == "listing" and text_value in REFINES.get((f, values[f]), ()):
                            values[f], prov[f] = text_value, f"{source}_refines_listing"
                            filled[f] += 1
                        elif prov[f] == "listing" and not _same(f, values[f], text_value):
                            conflicts[f] += 1
                            cases.add("listing", l.key, "field_conflict", field_name=f, current=values[f],
                                      proposed=text_value,
                                      evidence={"model": d.get("model"), "trim": d.get("trim"), "from": source})
                if l.vehicle_class == "car":
                    disp, hp = values.get("engine_displacement_l"), values.get("horsepower_hp")
                    if values.get("fuel_type") == "EV" and disp:
                        cases.add("listing", l.key, "implausible_value", field_name="engine_displacement_l",
                                  current=disp, evidence={"reason": "EV with an engine displacement"})
                    if disp and hp and not (15 <= hp / float(disp) <= 250):
                        cases.add("listing", l.key, "implausible_value", field_name="horsepower_hp", current=hp,
                                  evidence={"reason": "hp per litre outside 15-250",
                                            "engine_displacement_l": disp})
            else:
                excluded[l.excluded] += 1
            for f, v in over_by_listing.get(l.key, {}).items():   # reviewer decisions win
                if v is DROP or v is None:
                    values.pop(f, None)
                    prov.pop(f, None)
                elif f in COLUMNS:
                    values[f], prov[f] = v, "manual"
            for f, (lo, hi) in BOUNDS.items():
                v = values.get(f)
                if v is not None and not lo <= float(v) <= hi:
                    values.pop(f)
                    prov.pop(f, None)
                    if not l.excluded:
                        cases.add("listing", l.key, "implausible_value", field_name=f, current=v,
                                  evidence={"reason": f"outside {lo}-{hi}"})
            for f in SPEC_FIELDS:
                v = d.get(f)
                if v in (None, ""):
                    continue
                specs[f] = bool(int(v)) if f in BOOLEAN_FIELDS else v
            rows.append((l.site, l.listing_id, l.version, l.country, d.get("listed_at") or None,
                         d.get("model_year"), l.make_id, model_id, trim, d.get("trim"),
                         None if l.excluded in CLASS_EXCLUSIONS else l.vehicle_class, l.excluded,
                         *(values.get(f) for f in COLUMNS),
                         json.dumps(specs, ensure_ascii=False, default=str), json.dumps(prov),
                         d.get("price"), d.get("currency"), d.get("mileage_km")))

        cur.execute("DELETE FROM kb.clean_listing")
        cols = ("source_site, listing_id, raw_version, country_code, listed_at, model_year, make_id, model_id, "
                "trim_name, trim_raw, vehicle_class_code, excluded_reason, " + ", ".join(COLUMNS.values())
                + ", specs, provenance, price, currency_code, mileage_km")
        with cur.copy(f"COPY kb.clean_listing ({cols}) FROM STDIN") as copy:
            for r in rows:
                copy.write_row(r)

        # 5. review cases ---------------------------------------------------------------------
        write_cases(cur, cases, CLEAN_ISSUES)

        summary = _summary(cur, len(listings), excluded, filled, conflicts)
        cur.execute("INSERT INTO kb.clean_run (summary) VALUES (%s) RETURNING id", (json.dumps(summary),))
        summary["run_id"] = cur.fetchone()[0]
    return summary


def _summary(cur, n_listings: int, excluded: Counter, filled: Counter, conflicts: Counter) -> dict:
    def grouped(sql: str) -> dict:
        return {str(k): v for k, v in _load(cur, sql)}
    in_scope = n_listings - sum(excluded.values())
    return {
        "listings": n_listings,
        "in_scope": in_scope,
        "excluded": dict(sorted(excluded.items())),
        "in_scope_by_model_status": grouped("""
SELECT coalesce(m.status, 'no_model'), count(*) FROM kb.clean_listing l LEFT JOIN kb.model m ON m.id = l.model_id
WHERE l.excluded_reason IS NULL GROUP BY 1 ORDER BY 1"""),
        "makes": grouped("SELECT status, count(*) FROM kb.make GROUP BY 1 ORDER BY 1"),
        "models": grouped("SELECT status, count(*) FROM kb.model WHERE listings > 0 GROUP BY 1 ORDER BY 1"),
        "filled_from_names": dict(sorted(filled.items())),
        "conflicts": dict(sorted(conflicts.items())),
        "review_pending": grouped("SELECT issue, count(*) FROM kb.review_item WHERE status = 'pending' "
                                  "GROUP BY 1 ORDER BY 1"),
    }
