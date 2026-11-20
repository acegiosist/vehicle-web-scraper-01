"""`kb normalize`: rule-based identity (make -> model -> trim -> year). No AI, no cost.

Everything is resolved through alias tables first, so a new spelling of something known adds
an alias instead of a duplicate. Natural keys are UNIQUE in Postgres, so a bug here can't
create duplicates either. Re-running is idempotent and never overrides a human decision
(models in ``pending_review``/``rejected`` or ``verified_by`` ai/human are left alone).
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import yaml

from .. import normalize as N
from .db import compact_key, jsonb, slugify

log = logging.getLogger(__name__)

SEED_PATH = Path(__file__).resolve().parents[3] / "config" / "kb" / "makes.yaml"
MIN_YEAR = 1950
STRONG_LISTINGS = 5           # a make+model seen this often (or on 2+ sites) is accepted by rule
TRIM_MIN_LISTINGS = 2         # a trim label seen this often is verified (multi_source)
SPELLING_SIMILARITY = 0.85    # AI merges above this are "spelling only" -> sampled review

# --- token rules ------------------------------------------------------------------------
_DISPLACEMENT_TOKEN = re.compile(r"^\d[.,]\d{1,2}[lt]?$")
_MODEL_NOISE = {
    "4x4": ("drivetrain", "4WD"), "4wd": ("drivetrain", "4WD"), "awd": ("drivetrain", "AWD"),
    "4x2": ("drivetrain", "2WD"), "2wd": ("drivetrain", "2WD"),
    "hybrid": ("fuel_type", "Hybrid"), "hibrido": ("fuel_type", "Hybrid"), "hev": ("fuel_type", "Hybrid"),
    "phev": ("fuel_type", "Hybrid"), "diesel": ("fuel_type", "Diesel"), "gasolina": ("fuel_type", "Gasoline"),
    "new": None, "nuevo": None, "nueva": None,
}
_TRIM_NOISE = set(_MODEL_NOISE) | {
    # transmission
    "aut", "auto", "automatica", "automatico", "automatic", "at", "mt", "mecanica", "mecanico", "manual",
    "cvt", "dct", "dsg", "tiptronic", "secuencial", "steptronic", "ivt", "amt",
    # fuel
    "gasolina", "gas", "petrol", "electrico", "electric", "ev", "gnv", "cng", "turbodiesel",
    # body / cab
    "pick", "up", "pickup", "dc", "cd", "cs", "doble", "cabina", "sencilla", "simple", "chasis", "estacas",
    "sedan", "hatchback", "hb", "suv", "coupe", "wagon", "van", "furgon", "3p", "4p", "5p", "puertas", "ptas",
    # drivetrain
    "fwd", "rwd", "4x2", "2x4", "4matic", "traccion",
    # comfort noise sellers add to the version
    "aa", "a/a", "aire", "acondicionado", "full", "equipo", "dh", "d.h", "d/h", "fe",
    "turbo", "cab", "sen", "platon",
}


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"\s+", str(text or "").strip()) if t]


def _tok_norm(token: str) -> str:
    return N.norm(token).strip(".,;:()[]")


def split_model(raw: Optional[str]) -> tuple[str, dict]:
    """'RAV4 HYBRID 4X4' -> ('RAV4', {fuel_type: Hybrid, drivetrain: 4WD}). Never empties a name."""
    kept, attrs = [], {}
    for tok in _tokens(raw):
        n = _tok_norm(tok)
        if n in _MODEL_NOISE:
            rule = _MODEL_NOISE[n]
            if rule:
                attrs.setdefault(rule[0], rule[1])
            continue
        if _DISPLACEMENT_TOKEN.match(n):
            attrs.setdefault("engine_displacement_l", float(n.rstrip("lt").replace(",", ".")))
            continue
        kept.append(tok)
    name = " ".join(kept).strip(" -/")
    return (name or str(raw or "").strip()), attrs


def split_trim(raw: Optional[str]) -> Optional[str]:
    """Trim label without technical tokens: '1.8 FWD LS Mecanica' -> 'LS';
    '2.8 DC 4x4 Diésel' -> None (nothing but attributes)."""
    kept = []
    for tok in _tokens(raw):
        n = _tok_norm(tok)
        if not n or n in _TRIM_NOISE or _DISPLACEMENT_TOKEN.match(n) or re.fullmatch(r"\d[.,]\d+", n):
            continue
        if re.fullmatch(r"\d{1,2}v", n):          # "16V"
            continue
        kept.append(tok)
    label = " ".join(kept).strip(" -/.,")
    return label or None


def display_name(spellings: Counter) -> str:
    """Most frequent spelling, preferring one that isn't ALL CAPS; an all-caps name is
    title-cased word by word, except short or alphanumeric tokens (GTI, CX-30, RAV4)."""
    mixed = [(n, s) for s, n in spellings.items() if s and not s.isupper()]
    if mixed:
        return max(mixed)[1].strip()
    best = max(((n, s) for s, n in spellings.items() if s), default=(0, ""))[1].strip()

    def fix(word: str) -> str:
        return word if len(word) <= 3 or any(c.isdigit() for c in word) else word.capitalize()
    return " ".join("-".join(fix(p) for p in w.split("-")) for w in best.split())


def similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, compact_key(a), compact_key(b)).ratio() >= SPELLING_SIMILARITY


# --- seed ---------------------------------------------------------------------------------
def load_seed(path: Path = SEED_PATH) -> list[dict]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("makes") or []


def seed_makes(conn, seed: list[dict]) -> dict[str, str]:
    """Upsert the curated makes; returns {make slug: default class}."""
    classes = {}
    for m in seed:
        slug = slugify(m["name"])
        classes[slug] = m.get("class", "car")
        row = conn.execute(
            """INSERT INTO kb.make (name, slug, country_of_origin, status, verified_by)
               VALUES (%s, %s, %s, 'accepted', 'seed')
               ON CONFLICT (slug) DO UPDATE SET country_of_origin = COALESCE(kb.make.country_of_origin,
                                                                           EXCLUDED.country_of_origin)
               RETURNING id, status""", (m["name"], slug, m.get("country"))).fetchone()
        for alias in [m["name"], *(m.get("aliases") or [])]:
            conn.execute("INSERT INTO kb.make_alias (alias_key, make_id, source) VALUES (%s, %s, 'seed') "
                         "ON CONFLICT (alias_key) DO NOTHING", (compact_key(alias), row["id"]))
    return classes


# --- normalize ----------------------------------------------------------------------------
@dataclass
class _Listing:
    site: str
    listing_id: str
    raw_make: Optional[str]
    raw_model: Optional[str]
    raw_trim: Optional[str]
    year: Optional[int]
    vehicle_type: Optional[str]
    displacement: Optional[float]
    fuel: Optional[str]
    make_id: Optional[int] = None
    model_id: Optional[int] = None
    trim_id: Optional[int] = None
    excluded: Optional[str] = None
    model_name: str = ""
    trim_label: Optional[str] = None


@dataclass
class NormalizeStats:
    listings: int = 0
    makes_new: int = 0
    models_new: int = 0
    trims_new: int = 0
    excluded: Counter = field(default_factory=Counter)
    review_items: int = 0


def _load_listings(conn) -> list[_Listing]:
    rows = conn.execute(
        """SELECT l.source_site, l.listing_id, l.raw_make, l.raw_model, l.raw_trim, l.raw_year,
                  r.row->>'vehicle_type' AS vehicle_type,
                  (r.row->>'engine_displacement_l')::float AS displacement, r.row->>'fuel_type' AS fuel
           FROM kb.listing l JOIN staging.raw_listing r
             ON r.source_site = l.source_site AND r.listing_id = l.listing_id AND r.version = l.current_version
           ORDER BY l.source_site, l.listing_id""").fetchall()
    return [_Listing(r["source_site"], r["listing_id"], r["raw_make"], r["raw_model"], r["raw_trim"],
                     r["raw_year"], r["vehicle_type"], r["displacement"], r["fuel"]) for r in rows]


def open_review(conn, *, level: int, entity_type: str, entity_id: int, issue: str, source: str,
                kind: str = "individual", field_: str = "", country: str = "", proposed=None,
                current=None, evidence=None, listings: int = 0, ai_decision_id=None,
                evidence_id=None) -> bool:
    """Open a review case unless the same one is already open (re-runs never duplicate).
    An open case gets its proposal/evidence refreshed."""
    row = conn.execute(
        """INSERT INTO kb.review_item (level, entity_type, entity_id, country, field, issue, proposed,
                                       current, evidence, source, kind, listings_affected,
                                       ai_decision_id, evidence_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (entity_type, entity_id, country, field, issue) WHERE status = 'pending'
           DO UPDATE SET proposed = COALESCE(EXCLUDED.proposed, kb.review_item.proposed),
                         evidence = EXCLUDED.evidence, listings_affected = EXCLUDED.listings_affected,
                         kind = EXCLUDED.kind, source = EXCLUDED.source,
                         ai_decision_id = COALESCE(EXCLUDED.ai_decision_id, kb.review_item.ai_decision_id),
                         evidence_id = COALESCE(EXCLUDED.evidence_id, kb.review_item.evidence_id)
           RETURNING (xmax = 0) AS inserted""",
        (level, entity_type, entity_id, country, field_, issue,
         jsonb(proposed) if proposed is not None else None, jsonb(current) if current is not None else None,
         jsonb(evidence) if evidence is not None else None, source, kind, listings, ai_decision_id,
         evidence_id)).fetchone()
    return bool(row and row["inserted"])


def _decided(conn, entity_type: str, entity_id: int, issue: str) -> bool:
    """A person already answered this exact question: don't ask again."""
    return conn.execute("SELECT 1 FROM kb.review_item WHERE entity_type = %s AND entity_id = %s AND issue = %s "
                        "AND status <> 'pending'", (entity_type, entity_id, issue)).fetchone() is not None


def _vehicle_class(listings: list[_Listing], make_class: str) -> str:
    if sum(1 for l in listings if l.vehicle_type == "Motorcycle") * 2 >= len(listings):
        return "motorcycle"
    if make_class == "heavy":
        return "heavy"
    disp = sorted(l.displacement for l in listings if l.displacement)
    diesel = sum(1 for l in listings if l.fuel == "Diesel")
    if disp and disp[len(disp) // 2] > 7.0 and diesel * 2 > len(listings):
        return "heavy"                                   # 7.2 L Mercedes Atego, 10.8 L Kenworth
    return "motorcycle" if make_class == "motorcycle" else "car"


def normalize(conn, seed_path: Path = SEED_PATH, now_year: Optional[int] = None) -> NormalizeStats:
    now_year = now_year or datetime.now().year
    stats = NormalizeStats()
    classes = seed_makes(conn, load_seed(seed_path))
    ai_sites = {r["site"] for r in conn.execute("SELECT site FROM kb.source_site WHERE ai_allowed")}
    listings = _load_listings(conn)
    stats.listings = len(listings)

    # ---- 1. makes ----------------------------------------------------------------------
    make_alias = {r["alias_key"]: r["make_id"] for r in conn.execute("SELECT alias_key, make_id FROM kb.make_alias")}
    by_make_key: dict[str, list[_Listing]] = defaultdict(list)
    for l in listings:
        key = compact_key(l.raw_make)
        if not key:
            l.excluded = "no_make"
            continue
        by_make_key[key].append(l)
    for key, group in by_make_key.items():
        make_id = make_alias.get(key)
        if make_id is None:
            name = display_name(Counter(l.raw_make for l in group))
            slug = slugify(name)
            row = conn.execute(
                "INSERT INTO kb.make (name, slug) VALUES (%s, %s) ON CONFLICT (slug) DO UPDATE SET slug = EXCLUDED.slug "
                "RETURNING id, (xmax = 0) AS inserted", (name, slug)).fetchone()
            make_id = row["id"]
            stats.makes_new += int(row["inserted"])
            conn.execute("INSERT INTO kb.make_alias (alias_key, make_id, source) VALUES (%s, %s, 'rule') "
                         "ON CONFLICT (alias_key) DO NOTHING", (key, make_id))
            make_alias[key] = make_id
        for l in group:
            l.make_id = make_id

    makes = {r["id"]: r for r in conn.execute("SELECT id, name, slug, status, verified_by FROM kb.make")}
    for make_id, mk in makes.items():
        group = [l for l in listings if l.make_id == make_id]
        if mk["status"] == "unresolved" and group and not _decided(conn, "make", make_id, "unresolved_make"):
            stats.review_items += open_review(
                conn, level=1, entity_type="make", entity_id=make_id, issue="unresolved_make", source="rule",
                current={"name": mk["name"]}, listings=len(group),
                evidence={"spellings": dict(Counter(l.raw_make for l in group)),
                          "sites": sorted({l.site for l in group}),
                          "sample_models": [m for m, _ in Counter(l.raw_model for l in group).most_common(8)],
                          "ai_allowed": any(l.site in ai_sites for l in group)})

    # ---- 2. models -----------------------------------------------------------------------
    model_alias = {(r["make_id"], r["alias_key"]): r["model_id"]
                   for r in conn.execute("SELECT make_id, alias_key, model_id FROM kb.model_alias")}
    groups: dict[tuple[int, str], list[_Listing]] = defaultdict(list)
    for l in listings:
        if l.make_id is None:
            continue
        clean, _ = split_model(l.raw_model)
        l.model_name = clean
        if not compact_key(clean):
            l.excluded = "no_model"
            continue
        groups[(l.make_id, compact_key(clean))].append(l)

    for (make_id, key), group in groups.items():
        model_id = model_alias.get((make_id, key))
        if model_id is None:                      # a raw spelling may already be an alias
            for raw_key in {compact_key(l.raw_model) for l in group}:
                model_id = model_alias.get((make_id, raw_key)) or model_id
        if model_id is None:
            name = display_name(Counter(l.model_name for l in group))
            slug = slugify(name)
            if conn.execute("SELECT 1 FROM kb.model WHERE make_id = %s AND slug = %s", (make_id, slug)).fetchone():
                slug = f"{slug}-{key}"
            mk_class = classes.get(makes[make_id]["slug"], "car")
            model_id = conn.execute(
                """INSERT INTO kb.model (make_id, name, slug, vehicle_class) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (make_id, slug) DO UPDATE SET slug = EXCLUDED.slug RETURNING id""",
                (make_id, name, slug, _vehicle_class(group, mk_class))).fetchone()["id"]
            stats.models_new += 1
        for alias in {key} | {compact_key(l.raw_model) for l in group}:
            if alias and (make_id, alias) not in model_alias:
                conn.execute("INSERT INTO kb.model_alias (make_id, alias_key, model_id, source) "
                             "VALUES (%s, %s, %s, 'rule') ON CONFLICT DO NOTHING", (make_id, alias, model_id))
                model_alias[(make_id, alias)] = model_id
        for l in group:
            l.model_id = model_id

    # Follow merges made by review (model.merged_into) so listings land on the surviving model.
    merged = {r["id"]: r["merged_into"] for r in conn.execute("SELECT id, merged_into FROM kb.model WHERE merged_into IS NOT NULL")}
    for l in listings:
        while l.model_id in merged:
            l.model_id = merged[l.model_id]

    models = {r["id"]: r for r in conn.execute("SELECT * FROM kb.model")}
    by_model: dict[int, list[_Listing]] = defaultdict(list)
    for l in listings:
        if l.model_id:
            by_model[l.model_id].append(l)
    for model_id, group in by_model.items():
        md = models[model_id]
        strong = len(group) >= STRONG_LISTINGS or len({l.site for l in group}) >= 2
        make_ok = makes[md["make_id"]]["status"] == "accepted"
        if md["status"] == "unresolved" and md["verified_by"] == "unverified" and strong and make_ok:
            conn.execute("UPDATE kb.model SET status = 'accepted', verified_by = 'multi_source', updated_at = now() "
                         "WHERE id = %s", (model_id,))
        elif md["status"] == "unresolved" and not _decided(conn, "model", model_id, "unresolved_model"):
            years = sorted(l.year for l in group if l.year)
            stats.review_items += open_review(
                conn, level=2, entity_type="model", entity_id=model_id, issue="unresolved_model", source="rule",
                current={"make": makes[md["make_id"]]["name"], "name": md["name"],
                         "vehicle_class": md["vehicle_class"]},
                listings=len(group),
                evidence={"spellings": dict(Counter(l.raw_model for l in group)),
                          "sites": sorted({l.site for l in group}), "listings": len(group),
                          "years": [years[0], years[-1]] if years else None,
                          "sample_trims": [t for t, _ in Counter(l.raw_trim for l in group if l.raw_trim).most_common(6)],
                          "ai_allowed": any(l.site in ai_sites for l in group)})

    # ---- 3. trims ------------------------------------------------------------------------
    trim_alias = {(r["model_id"], r["alias_key"]): r["trim_id"]
                  for r in conn.execute("SELECT model_id, alias_key, trim_id FROM kb.trim_alias")}
    tgroups: dict[tuple[int, str], list[_Listing]] = defaultdict(list)
    for l in listings:
        if l.model_id:
            l.trim_label = split_trim(l.raw_trim)
            if l.trim_label and compact_key(l.trim_label):
                tgroups[(l.model_id, compact_key(l.trim_label))].append(l)
    for (model_id, key), group in tgroups.items():
        trim_id = trim_alias.get((model_id, key))
        if trim_id is None:
            name = display_name(Counter(l.trim_label for l in group))
            row = conn.execute(
                """INSERT INTO kb.trim (model_id, name, slug, status, verified_by) VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (model_id, slug) DO UPDATE SET slug = EXCLUDED.slug RETURNING id, (xmax = 0) AS inserted""",
                (model_id, name, key,
                 "accepted" if len(group) >= TRIM_MIN_LISTINGS else "unresolved",
                 "multi_source" if len(group) >= TRIM_MIN_LISTINGS else "unverified")).fetchone()
            trim_id = row["id"]
            stats.trims_new += int(row["inserted"])
            conn.execute("INSERT INTO kb.trim_alias (model_id, alias_key, trim_id, source) VALUES (%s, %s, %s, 'rule') "
                         "ON CONFLICT DO NOTHING", (model_id, key, trim_id))
            trim_alias[(model_id, key)] = trim_id
        elif len(group) >= TRIM_MIN_LISTINGS:
            conn.execute("UPDATE kb.trim SET status = 'accepted', verified_by = 'multi_source' "
                         "WHERE id = %s AND status = 'unresolved' AND verified_by = 'unverified'", (trim_id,))
        for l in group:
            l.trim_id = trim_id

    # ---- 4. years ------------------------------------------------------------------------
    for l in listings:
        if l.excluded or not l.model_id:
            continue
        md = models[l.model_id]
        if l.year is None:
            l.excluded = "no_year"
        elif not MIN_YEAR <= l.year <= now_year + 1:
            l.excluded = "year_out_of_range"
            stats.review_items += open_review(conn, level=3, entity_type="listing", entity_id=listing_number(l.site, l.listing_id),
                                              issue="year_out_of_range", source="rule", listings=1,
                                              current={"year": l.year, "model": md["name"]})
        elif md["year_from"] and md["year_to"] and not (md["year_from"] - 1 <= l.year <= md["year_to"] + 1):
            if not _listing_year_approved(conn, l):
                l.excluded = "year_review"
                stats.review_items += open_review(
                    conn, level=3, entity_type="listing", entity_id=listing_number(l.site, l.listing_id), issue="year_outside_production",
                    source="rule", listings=1,
                    current={"year": l.year, "model": md["name"],
                             "production_years": [md["year_from"], md["year_to"]]})

    # ---- 5. write back -------------------------------------------------------------------
    with conn.cursor() as cur:
        cur.executemany(
            """UPDATE kb.listing SET make_id = %s, model_id = %s, trim_id = %s, excluded_reason = %s,
                      match_method = COALESCE(match_method, 'rule')
               WHERE source_site = %s AND listing_id = %s""",
            [(l.make_id, l.model_id, l.trim_id, l.excluded, l.site, l.listing_id) for l in listings])
    for l in listings:
        if l.excluded:
            stats.excluded[l.excluded] += 1
    return stats


def listing_number(site: str, listing_id: str) -> int:
    """Stable integer id for a listing, used as review_item.entity_id. SQL computes the same
    number with ``kb.listing_number()`` (migration 0002), so keep both in sync."""
    import hashlib
    return int(hashlib.sha256(f"{site}|{listing_id}".encode()).hexdigest()[:15], 16)


def _listing_year_approved(conn, l: _Listing) -> bool:
    return conn.execute("SELECT 1 FROM kb.review_item WHERE entity_type = 'listing' AND entity_id = %s "
                        "AND issue = 'year_outside_production' AND status IN ('approved', 'corrected')",
                        (listing_number(l.site, l.listing_id),)).fetchone() is not None


# --- merges (cascade, run inside the caller's transaction) --------------------------------
def merge_model(conn, src: int, dst: int, reason: str) -> None:
    """Fold model ``src`` into ``dst``: aliases, trims, listings and variants move over;
    ``src`` stays as a tombstone (merged_into) so old aliases keep resolving."""
    if src == dst:
        return
    conn.execute("UPDATE kb.model_alias SET model_id = %s WHERE model_id = %s", (dst, src))
    for t in conn.execute("SELECT id, slug FROM kb.trim WHERE model_id = %s", (src,)).fetchall():
        twin = conn.execute("SELECT id FROM kb.trim WHERE model_id = %s AND slug = %s", (dst, t["slug"])).fetchone()
        if twin:
            merge_trim(conn, t["id"], twin["id"], reason)
        else:
            conn.execute("UPDATE kb.trim SET model_id = %s WHERE id = %s", (dst, t["id"]))
            conn.execute("UPDATE kb.trim_alias SET model_id = %s WHERE trim_id = %s", (dst, t["id"]))
    conn.execute("UPDATE kb.listing SET model_id = %s WHERE model_id = %s", (dst, src))
    from .consensus import merge_variants_of_model
    merge_variants_of_model(conn, src, dst, reason)
    conn.execute("UPDATE kb.model SET merged_into = %s, status = 'rejected', updated_at = now() WHERE id = %s",
                 (dst, src))


def merge_trim(conn, src: int, dst: int, reason: str) -> None:
    if src == dst:
        return
    conn.execute("""INSERT INTO kb.trim_alias (model_id, alias_key, trim_id, source)
                    SELECT t.model_id, a.alias_key, %s, a.source FROM kb.trim_alias a
                    JOIN kb.trim t ON t.id = %s WHERE a.trim_id = %s
                    ON CONFLICT (model_id, alias_key) DO UPDATE SET trim_id = EXCLUDED.trim_id""", (dst, dst, src))
    conn.execute("DELETE FROM kb.trim_alias WHERE trim_id = %s", (src,))
    conn.execute("UPDATE kb.listing SET trim_id = %s WHERE trim_id = %s", (dst, src))
    from .consensus import merge_variants_of_trim
    merge_variants_of_trim(conn, src, dst, reason)
    conn.execute("UPDATE kb.trim SET merged_into = %s, status = 'rejected' WHERE id = %s", (dst, src))


def merge_make(conn, src: int, dst: int, reason: str) -> None:
    if src == dst:
        return
    conn.execute("UPDATE kb.make_alias SET make_id = %s WHERE make_id = %s", (dst, src))
    for m in conn.execute("SELECT id, slug FROM kb.model WHERE make_id = %s AND merged_into IS NULL", (src,)).fetchall():
        twin = conn.execute("SELECT id FROM kb.model WHERE make_id = %s AND slug = %s", (dst, m["slug"])).fetchone()
        if twin:
            merge_model(conn, m["id"], twin["id"], reason)
        else:
            conn.execute("UPDATE kb.model SET make_id = %s WHERE id = %s", (dst, m["id"]))
            conn.execute("""INSERT INTO kb.model_alias (make_id, alias_key, model_id, source)
                            SELECT %s, alias_key, model_id, source FROM kb.model_alias WHERE model_id = %s
                            ON CONFLICT DO NOTHING""", (dst, m["id"]))
    conn.execute("UPDATE kb.listing SET make_id = %s WHERE make_id = %s", (dst, src))
    conn.execute("UPDATE kb.make SET status = 'rejected', updated_at = now() WHERE id = %s", (src,))
