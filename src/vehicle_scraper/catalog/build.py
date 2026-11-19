"""Stage 2: raw scraped listings -> catalog (make / model / trim / variant) with consensus specs.

``resolve()`` is pure: it canonicalizes every listing (rules + approved AI/human aliases read
from the catalog DB) and groups them. ``write()`` upserts entities by natural key so IDs stay
stable, replaces the derived tables (listing links, per-field provenance, features, markets) and
prunes rule-created entities that no listing supports any more. ``build_catalog()`` runs both.

The raw ``vehicles.sqlite`` is only ever opened read-only.
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.engine import Connection, Engine

from ..models import BOOLEAN_FIELDS
from ..normalize import to_datetime
from . import schema as S
from .canonical import MakeInfo, MakeTable, ParsedNames, display_case, key, parse_names, slugify

CURRENCY_COUNTRY = {"COP": "CO", "GTQ": "GT", "INR": "IN", "USD": "US", "CLP": "CL", "CRC": "CR",
                    "MXN": "MX", "VES": "VE", "PEN": "PE", "ARS": "AR", "HNL": "HN", "NIO": "NI"}
TRIM_AWARE_SHARE = 0.5         # a site with a trim on >= 50 % of its listings separates model and trim
CONFLICT_REVIEW_RATIO = 0.3    # > 30 % of a variant's listings disagree on a field -> review
CONFLICT_MIN_LISTINGS = 3
RULE_REVIEW_REASONS = ("unknown_make", "spec_conflict")

KEY_FIELDS = S.KEY_COLUMNS                         # model_year, fuel_type, transmission_type, displacement
SPEC_FIELDS = tuple(S.SPEC_COLUMNS)
TITLE_FIELDS = ("engine_displacement_l", "transmission_type", "fuel_type", "body_style", "drivetrain", "doors")

FEATURES = {   # code -> (category, name_es, name_en)
    "abs": ("safety", "Frenos ABS", "ABS brakes"),
    "stability_control": ("safety", "Control de estabilidad", "Stability control"),
    "traction_control": ("safety", "Control de tracción", "Traction control"),
    "adaptive_cruise_control": ("adas", "Crucero adaptativo", "Adaptive cruise control"),
    "lane_assist": ("adas", "Asistente de carril", "Lane assist"),
    "automatic_emergency_braking": ("adas", "Frenado autónomo de emergencia", "Automatic emergency braking"),
    "blind_spot_monitoring": ("adas", "Monitor de punto ciego", "Blind-spot monitoring"),
    "led_lights": ("exterior", "Luces LED", "LED lights"),
    "fog_lights": ("exterior", "Exploradoras", "Fog lights"),
    "sunroof": ("exterior", "Sunroof", "Sunroof"),
    "panoramic_roof": ("exterior", "Techo panorámico", "Panoramic roof"),
    "roof_rails": ("exterior", "Barras de techo", "Roof rails"),
    "alloy_wheels": ("exterior", "Rines de aleación", "Alloy wheels"),
    "leather_seats": ("interior", "Asientos de cuero", "Leather seats"),
    "power_seats": ("interior", "Asientos eléctricos", "Power seats"),
    "heated_seats": ("interior", "Asientos calefactados", "Heated seats"),
    "cooled_seats": ("interior", "Asientos ventilados", "Cooled seats"),
    "memory_seats": ("interior", "Asientos con memoria", "Memory seats"),
    "climate_control": ("comfort", "Climatizador", "Climate control"),
    "dual_zone_ac": ("comfort", "A/C bizona", "Dual-zone A/C"),
    "keyless_entry": ("comfort", "Acceso sin llave", "Keyless entry"),
    "push_button_start": ("comfort", "Encendido por botón", "Push-button start"),
    "bluetooth": ("infotainment", "Bluetooth", "Bluetooth"),
    "apple_carplay": ("infotainment", "Apple CarPlay", "Apple CarPlay"),
    "android_auto": ("infotainment", "Android Auto", "Android Auto"),
    "navigation": ("infotainment", "Navegador", "Navigation"),
    "reverse_camera": ("cameras", "Cámara de reversa", "Reverse camera"),
    "camera_360": ("cameras", "Cámara 360°", "360° camera"),
    "front_camera": ("cameras", "Cámara frontal", "Front camera"),
    "parking_sensors": ("parking", "Sensores de parqueo", "Parking sensors"),
    "automatic_parking": ("parking", "Parqueo automático", "Automatic parking"),
    "alarm": ("security", "Alarma", "Alarm"),
    "immobilizer": ("security", "Inmovilizador", "Immobilizer"),
    "tow_package": ("utility", "Tiro de arrastre", "Tow package"),
    "bed_liner": ("utility", "Protector de platón", "Bed liner"),
}
assert set(FEATURES) == set(BOOLEAN_FIELDS), "FEATURES must cover every boolean field of VehicleRecord"


def load_raw_rows(raw_db: Path) -> list[dict]:
    """Every row of the scraper's ``vehicles`` table, opened read-only."""
    conn = sqlite3.connect(f"{Path(raw_db).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM vehicles")]
    finally:
        conn.close()


def site_country(site: str, currency: Optional[str]) -> Optional[str]:
    from ..sites import REGISTRY
    cls = REGISTRY.get(site)
    return (getattr(cls, "country", "") or "").upper() or CURRENCY_COUNTRY.get((currency or "").upper())


def trim_alias_norm(raw_model: Any, raw_trim: Any) -> str:
    return f"{key(raw_model)}|{key(raw_trim)}"


# ---------------------------------------------------------------------------
# Overrides already decided (AI / human) and stored in the catalog DB
# ---------------------------------------------------------------------------
@dataclass
class Overrides:
    model_alias: dict = field(default_factory=dict)     # (make_slug, alias_norm) -> (target match_key, method)
    model_locked: dict = field(default_factory=dict)    # (make_slug, match_key) -> locked name
    model_trusted: set = field(default_factory=set)     # (make_slug, match_key) verified by AI/human
    model_default_body: dict = field(default_factory=dict)  # (make_slug, match_key) -> (body, source)
    trim_alias: dict = field(default_factory=dict)      # (make_slug, alias_norm) -> (model key, trim key, attrs, method)
    trim_locked: dict = field(default_factory=dict)     # (make_slug, model_key, trim_key) -> locked name

    @classmethod
    def load(cls, conn: Connection) -> "Overrides":
        o = cls()
        mk, md, tr = S.make, S.model, S.trim
        for slug, alias, target, method in conn.execute(
                select(mk.c.slug, S.model_alias.c.alias_norm, md.c.match_key, S.model_alias.c.method)
                .join(md, md.c.id == S.model_alias.c.model_id).join(mk, mk.c.id == md.c.make_id)):
            o.model_alias[(slug, alias)] = (target, method)
        for slug, mkey, name, locked, created, body, body_src in conn.execute(
                select(mk.c.slug, md.c.match_key, md.c.name, md.c.name_locked, md.c.created_by,
                       md.c.default_body_style, md.c.default_body_source).join(mk, mk.c.id == md.c.make_id)):
            if locked:
                o.model_locked[(slug, mkey)] = name
            if locked or created != "rule":
                o.model_trusted.add((slug, mkey))
            if body:
                o.model_default_body[(slug, mkey)] = (body, body_src or "human")
        for slug, mkey, alias, tkey, attrs, method in conn.execute(
                select(mk.c.slug, md.c.match_key, S.trim_alias.c.alias_norm, tr.c.match_key,
                       S.trim_alias.c.attrs, S.trim_alias.c.method)
                .join(tr, tr.c.id == S.trim_alias.c.trim_id).join(md, md.c.id == tr.c.model_id)
                .join(mk, mk.c.id == md.c.make_id)):
            o.trim_alias[(slug, alias)] = (mkey, tkey, attrs or {}, method)
        for slug, mkey, tkey, name in conn.execute(
                select(mk.c.slug, md.c.match_key, tr.c.match_key, tr.c.name)
                .join(md, md.c.id == tr.c.model_id).join(mk, mk.c.id == md.c.make_id)
                .where(tr.c.name_locked.is_(True))):
            o.trim_locked[(slug, mkey, tkey)] = name
        return o


# ---------------------------------------------------------------------------
# Resolution (pure)
# ---------------------------------------------------------------------------
@dataclass
class ResolvedListing:
    row: dict
    names: ParsedNames
    make: MakeInfo
    model_key: str
    trim_key: str
    trim_text: str
    attrs: dict
    method: str                 # rule | ai | human: who decided the model/trim mapping
    country: Optional[str]
    vehicle_class: str
    site_trim_aware: bool


@dataclass
class ModelCluster:
    make: MakeInfo
    key: str
    texts: Counter = field(default_factory=Counter)
    alias_texts: Counter = field(default_factory=Counter)   # spellings merged in by an approved alias
    raw_models: Counter = field(default_factory=Counter)
    classes: Counter = field(default_factory=Counter)
    bodies: Counter = field(default_factory=Counter)
    drives: Counter = field(default_factory=Counter)
    sites: set = field(default_factory=set)
    years: set = field(default_factory=set)
    verified: bool = False
    n: int = 0

    @property
    def name(self) -> str:
        return pick_display(self.texts or self.alias_texts)

    @property
    def vehicle_class(self) -> str:
        return self.classes.most_common(1)[0][0] if self.classes else "car"


@dataclass
class Resolution:
    listings: list[ResolvedListing]
    models: dict                 # (make_slug, model_key) -> ModelCluster
    trims: dict                  # (make_slug, model_key, trim_key) -> Counter(trim_text)
    makes: dict                  # make_slug -> MakeInfo
    overrides: Overrides
    trim_aware_sites: set


def pick_display(texts: Counter) -> str:
    """Most frequent spelling, preferring one that isn't all caps ('Compass' over 'COMPASS')."""
    if not texts:
        return ""
    best = sorted(texts.items(), key=lambda kv: (kv[0].isupper() and len(kv[0]) > 3, -kv[1], kv[0]))[0][0]
    return display_case(best) if best.isupper() or best.islower() else best


def _vehicle_class(row: dict, make: MakeInfo) -> str:
    if row.get("vehicle_type") == "Motorcycle":
        return "moto"
    if make.heavy or row.get("vehicle_type") == "Truck" or row.get("body_style") == "Truck":
        return "heavy"
    return "car"


def resolve(raw_rows: list[dict], makes: MakeTable, overrides: Optional[Overrides] = None) -> Resolution:
    o = overrides or Overrides()
    by_site: dict[str, list[dict]] = defaultdict(list)
    for r in raw_rows:
        by_site[r["source_site"]].append(r)
    trim_aware = {s for s, rs in by_site.items() if sum(bool(r.get("trim")) for r in rs) >= TRIM_AWARE_SHARE * len(rs)}

    # Models seen on a site that separates model and trim are trusted names; on other sites a
    # known model prefix is split off ("TAHOE LTZ" -> Tahoe + LTZ).
    known: dict[str, set] = defaultdict(set)
    for slug, mkey in o.model_trusted:
        known[slug].add(mkey)
    for r in raw_rows:
        if r["source_site"] in trim_aware:
            p = parse_names(r.get("make"), r.get("model"), r.get("trim"), makes)
            known[p.make.slug].add(p.model_key)

    listings, models, trims, make_infos = [], {}, defaultdict(Counter), {}
    for r in raw_rows:
        aware = r["source_site"] in trim_aware
        mk0 = makes.resolve(r.get("make"))
        p = parse_names(r.get("make"), r.get("model"), r.get("trim"), makes,
                        known_models=None if aware else known[mk0.slug])
        method, mkey = "rule", p.model_key
        if (hit := o.model_alias.get((p.make.slug, p.model_key))):
            mkey, method = hit
        tkey, ttext, attrs = p.trim_key, p.trim_text, dict(p.attrs)
        # A trim alias names the raw model+trim string exactly, so it may also move it to another model.
        if (hit := o.trim_alias.get((p.make.slug, trim_alias_norm(r.get("model"), r.get("trim"))))):
            mkey, tkey, ai_attrs, method = hit
            ttext = o.trim_locked.get((p.make.slug, mkey, tkey), ttext)
            attrs = {**ai_attrs, **attrs}
        cls = _vehicle_class(r, p.make)
        rl = ResolvedListing(r, p, p.make, mkey, tkey, ttext, attrs, method,
                             site_country(r["source_site"], r.get("currency")), cls, aware)
        listings.append(rl)
        make_infos[p.make.slug] = p.make

        mc = models.setdefault((p.make.slug, mkey), ModelCluster(p.make, mkey))
        if (p.make.slug, mkey) in o.model_locked:
            mc.texts[o.model_locked[(p.make.slug, mkey)]] += 1
        elif mkey != p.model_key:                     # merged by an alias: not a competing spelling
            mc.alias_texts[p.model_text] += 1
        else:
            mc.texts[p.model_text] += 1
        mc.raw_models[r.get("model") or ""] += 1
        mc.classes[cls] += 1
        mc.sites.add(r["source_site"])
        mc.n += 1
        if r.get("model_year"):
            mc.years.add(r["model_year"])
        if body := (r.get("body_style") or attrs.get("body_style")):
            mc.bodies[body] += 1
        if drive := (r.get("drivetrain") or attrs.get("drivetrain")):
            mc.drives[drive] += 1
        mc.verified = mc.verified or aware or (p.make.slug, mkey) in o.model_trusted
        trims[(p.make.slug, mkey, tkey)][ttext] += 1
    return Resolution(listings, models, dict(trims), make_infos, o, trim_aware)


# ---------------------------------------------------------------------------
# Variants and consensus
# ---------------------------------------------------------------------------
def _values(rl: ResolvedListing, default_body: Optional[tuple]) -> dict[str, tuple[Any, str]]:
    """field -> (value, source) for one listing: listing fields first, then title attrs."""
    out = {}
    for f in (*KEY_FIELDS, *SPEC_FIELDS):
        v = rl.row.get(f)
        if v is not None and v != "":
            out[f] = (v, "listing")
        elif f in rl.attrs:
            out[f] = (rl.attrs[f], "title")
    if "engine_displacement_l" in out:
        v, src = out["engine_displacement_l"]
        out["engine_displacement_l"] = (round(float(v), 1) if float(v) >= 0.5 else round(float(v), 3), src)
    if "body_style" not in out and default_body and rl.vehicle_class == "car":
        out["body_style"] = default_body
    return out


def variant_key(vals: dict) -> str:
    return "|".join("-" if vals.get(f) is None else str(vals[f][0]) for f in KEY_FIELDS)


@dataclass
class VariantAgg:
    trim: tuple
    key: str
    listings: list = field(default_factory=list)
    fields: dict = field(default_factory=lambda: defaultdict(Counter))    # field -> Counter((value, source))

    def consensus(self) -> dict[str, dict]:
        out = {}
        for f, counter in self.fields.items():
            by_value: Counter = Counter()
            sources: dict = defaultdict(Counter)
            for (v, src), n in counter.items():
                by_value[v] += n
                sources[v][src] += n
            value, support = by_value.most_common(1)[0]
            total = sum(by_value.values())
            src = sources[value]
            source = "listing" if src.get("listing") else src.most_common(1)[0][0]
            out[f] = {"value": value, "source": source, "n_support": support, "n_conflict": total - support,
                      "confidence": round(support / total, 3)}
        return out


def group_variants(res: Resolution) -> dict[tuple, VariantAgg]:
    per_trim_year: dict[tuple, list] = defaultdict(list)
    vals_of: dict[int, dict] = {}
    for i, rl in enumerate(res.listings):
        tkey = (rl.make.slug, rl.model_key, rl.trim_key)
        vals = _values(rl, res.overrides.model_default_body.get((rl.make.slug, rl.model_key)))
        vals_of[i] = vals
        per_trim_year[(tkey, vals.get("model_year", (None,))[0])].append(i)
    # Fill a missing key field only when every other listing of the same trim+year agrees.
    for idxs in per_trim_year.values():
        for f in KEY_FIELDS[1:]:
            known_vals = {vals_of[i][f][0] for i in idxs if f in vals_of[i]}
            if len(known_vals) == 1:
                v = next(iter(known_vals))
                for i in idxs:
                    vals_of[i].setdefault(f, (v, "consensus"))
    aggs: dict[tuple, VariantAgg] = {}
    for i, rl in enumerate(res.listings):
        vals = vals_of[i]
        tkey = (rl.make.slug, rl.model_key, rl.trim_key)
        vk = variant_key(vals)
        agg = aggs.setdefault((tkey, vk), VariantAgg(tkey, vk))
        agg.listings.append(rl)
        for f, (v, src) in vals.items():
            agg.fields[f][(v, src)] += 1
    return aggs


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def _upsert(conn: Connection, table, natural: dict, values: dict, keep_if_locked: tuple = ()) -> int:
    cond = and_(*[table.c[k] == v for k, v in natural.items()])
    row = conn.execute(select(table).where(cond)).mappings().first()
    if row is None:
        return conn.execute(insert(table).values(**natural, **values)).inserted_primary_key[0]
    if row.get("name_locked"):
        values = {k: v for k, v in values.items() if k not in keep_if_locked}
    changed = {k: v for k, v in values.items() if row.get(k) != v}
    if changed:
        conn.execute(update(table).where(table.c.id == row["id"]).values(**changed))
    return row["id"]


@dataclass
class BuildReport:
    raw_listings: int = 0
    raw_makes: int = 0
    raw_models: int = 0
    raw_trims: int = 0
    makes: int = 0
    models: int = 0
    models_unverified: int = 0
    trims: int = 0
    variants: int = 0
    listings_linked: int = 0
    review_items: int = 0
    pruned: dict = field(default_factory=dict)
    by_class: dict = field(default_factory=dict)
    resolution: Optional[Resolution] = field(default=None, repr=False)

    def text(self) -> str:
        return "\n".join([
            f"Raw listings:   {self.raw_listings}",
            f"Makes:          {self.raw_makes} raw spellings -> {self.makes} canonical",
            f"Models:         {self.raw_models} raw make+model -> {self.models} canonical "
            f"({self.models_unverified} unverified: only seen on sites without a trim field)",
            f"Trims:          {self.raw_trims} raw make+model+trim -> {self.trims} canonical",
            f"Variants:       {self.variants}  (trim + year + fuel + gearbox + engine size)",
            f"Listings linked:{self.listings_linked:>6}",
            f"Classes:        " + ", ".join(f"{k} {v}" for k, v in sorted(self.by_class.items())),
            f"Open review items: {self.review_items}  (rules + AI, see `catalog review --export`)",
            f"Pruned (no listings left): " + (", ".join(f"{k} {v}" for k, v in self.pruned.items() if v) or "none"),
        ])


def write(engine: Engine, res: Resolution) -> BuildReport:
    rep = BuildReport(raw_listings=len(res.listings), resolution=res)
    rep.raw_makes = len({rl.row.get("make") for rl in res.listings})
    rep.raw_models = len({(key(rl.row.get("make")), key(rl.row.get("model"))) for rl in res.listings})
    rep.raw_trims = len({(key(rl.row.get("make")), key(rl.row.get("model")), key(rl.row.get("trim")))
                         for rl in res.listings})
    aggs = group_variants(res)
    with engine.begin() as conn:
        for code, (cat, es, en) in FEATURES.items():
            _upsert(conn, S.feature, {"code": code}, {"category": cat, "name_es": es, "name_en": en})
        feature_ids = dict(conn.execute(select(S.feature.c.code, S.feature.c.id)).all())
        for t in (S.variant_field_source, S.variant_feature, S.variant_market, S.listing):
            conn.execute(delete(t))
        conn.execute(delete(S.review_item).where(S.review_item.c.status == "open",
                                                 S.review_item.c.reason.in_(RULE_REVIEW_REASONS)))

        make_ids = {slug: _upsert(conn, S.make, {"slug": slug},
                                  {"name": mi.name, "country_of_origin": mi.country, "in_seed": mi.in_seed})
                    for slug, mi in res.makes.items()}
        model_ids = {}
        for (slug, mkey), mc in res.models.items():
            name = mc.name
            model_ids[(slug, mkey)] = _upsert(
                conn, S.model, {"make_id": make_ids[slug], "match_key": mkey},
                {"name": name, "slug": slugify(name), "vehicle_class": mc.vehicle_class, "verified": mc.verified},
                keep_if_locked=("name", "slug"))
        trim_ids = {}
        for (slug, mkey, tkey), texts in res.trims.items():
            name = pick_display(texts)
            trim_ids[(slug, mkey, tkey)] = _upsert(
                conn, S.trim, {"model_id": model_ids[(slug, mkey)], "match_key": tkey},
                {"name": name, "slug": slugify(name) if name else "_none"}, keep_if_locked=("name", "slug"))

        human: dict = defaultdict(dict)        # (trim_id, variant_key) -> {field: value}, set in review
        for trim_id, vk, f, v in conn.execute(
                select(S.variant.c.trim_id, S.variant.c.variant_key, S.variant_override.c.field,
                       S.variant_override.c.value).join(S.variant, S.variant.c.id == S.variant_override.c.variant_id)):
            human[(trim_id, vk)][f] = v

        variant_ids, fs_rows, vf_rows, vm_rows, li_rows, reviews = {}, [], [], [], [], []
        for (tkey, vk), agg in aggs.items():
            cons = agg.consensus()
            fixed = human.get((trim_ids[tkey], vk), {})
            for f, v in fixed.items():          # a person's value beats the listing consensus
                seen = agg.fields.get(f, Counter())
                support = sum(n for (val, _), n in seen.items() if val == v)
                cons[f] = {"value": v, "source": "human", "n_support": support,
                           "n_conflict": sum(seen.values()) - support,
                           "confidence": 1.0}
            values = {f: (cons[f]["value"] if f in cons else None) for f in (*KEY_FIELDS, *SPEC_FIELDS)}
            conflicts = {f: c for f, c in cons.items()
                         if f not in fixed and c["n_support"] + c["n_conflict"] >= CONFLICT_MIN_LISTINGS
                         and c["n_conflict"] / (c["n_support"] + c["n_conflict"]) > CONFLICT_REVIEW_RATIO}
            vid = _upsert(conn, S.variant, {"trim_id": trim_ids[tkey], "variant_key": vk},
                          {**values, "n_listings": len(agg.listings), "needs_review": bool(conflicts)})
            variant_ids[(tkey, vk)] = vid
            fs_rows += [{"variant_id": vid, "field": f, "value": str(c["value"]), "source": c["source"],
                         "n_support": c["n_support"], "n_conflict": c["n_conflict"], "confidence": c["confidence"]}
                        for f, c in cons.items()]
            if conflicts:
                reviews.append({"entity_type": "variant", "entity_key": "/".join([*tkey[:2], tkey[2] or "_", vk]),
                                "reason": "spec_conflict",
                                "detail": "; ".join(f"{f}: {c['n_conflict']} of {c['n_support'] + c['n_conflict']} "
                                                    f"listings disagree with {c['value']}" for f, c in conflicts.items()),
                                "proposal": {"kind": "variant_values",
                                             "values": {f: c["value"] for f, c in conflicts.items()}}})
            for code in BOOLEAN_FIELDS:
                vals = [rl.row.get(code) for rl in agg.listings]
                n_true, n_false = sum(v == 1 for v in vals), sum(v == 0 for v in vals)
                if n_true or n_false:
                    vf_rows.append({"variant_id": vid, "feature_id": feature_ids[code], "n_true": n_true,
                                    "n_false": n_false, "n_listings": len(agg.listings)})
            markets: dict = defaultdict(list)
            for rl in agg.listings:
                when = to_datetime(rl.row.get("listed_at")) or to_datetime(rl.row.get("scraped_at"))
                markets[rl.country or "??"].append(when)
                li_rows.append({
                    "source_site": rl.row["source_site"], "listing_id": str(rl.row["listing_id"]), "variant_id": vid,
                    "country": rl.country, "source_url": rl.row.get("source_url"), "price": rl.row.get("price"),
                    "currency": rl.row.get("currency"), "mileage_km": rl.row.get("mileage_km"),
                    "model_year": rl.row.get("model_year"), "raw_make": rl.row.get("make"),
                    "raw_model": rl.row.get("model"), "raw_trim": rl.row.get("trim"), "match_method": rl.method,
                    "confidence": 1.0 if rl.method != "rule" or rl.site_trim_aware else 0.8,
                    "listed_at": to_datetime(rl.row.get("listed_at")), "scraped_at": to_datetime(rl.row.get("scraped_at")),
                    "raw": rl.row})
            for country, whens in markets.items():
                ws = [w for w in whens if w]
                vm_rows.append({"variant_id": vid, "country": country[:2], "n_listings": len(whens),
                                "first_listed": min(ws) if ws else None, "last_listed": max(ws) if ws else None})
        for t, rows in ((S.variant_field_source, fs_rows), (S.variant_feature, vf_rows),
                        (S.variant_market, vm_rows), (S.listing, li_rows)):
            for i in range(0, len(rows), 500):
                conn.execute(insert(t), rows[i:i + 500])

        for slug, mi in res.makes.items():
            if not mi.in_seed:
                reviews.append({"entity_type": "make", "entity_key": slug, "reason": "unknown_make",
                                "detail": f"'{mi.name}' is not in config/catalog/makes.yaml",
                                "proposal": {"kind": "make", "name": mi.name}})
        existing = {tuple(r) for r in conn.execute(select(S.review_item.c.entity_type, S.review_item.c.entity_key,
                                                          S.review_item.c.reason))}
        new = [r for r in reviews if (r["entity_type"], r["entity_key"], r["reason"]) not in existing]
        if new:
            conn.execute(insert(S.review_item), [{**r, "status": "open"} for r in new])

        rep.pruned = _prune(conn, set(variant_ids.values()), set(trim_ids.values()), set(model_ids.values()),
                            set(make_ids.values()))
        rep.makes, rep.models, rep.trims = len(make_ids), len(model_ids), len(trim_ids)
        rep.variants, rep.listings_linked = len(variant_ids), len(li_rows)
        rep.models_unverified = sum(not mc.verified for mc in res.models.values())
        rep.by_class = dict(Counter(mc.vehicle_class for mc in res.models.values()))
        rep.review_items = len(conn.execute(select(S.review_item.c.id).where(S.review_item.c.status == "open")).all())
    return rep


def _prune(conn: Connection, variants: set, trims: set, models: set, makes: set) -> dict:
    """Delete rule-created entities that no listing supports and nothing approved points at."""
    out = {}
    q = select(S.variant.c.id).where(S.variant.c.created_by == "rule")
    gone = [v for (v,) in conn.execute(q) if v not in variants]
    if gone:
        conn.execute(delete(S.variant).where(S.variant.c.id.in_(gone)))
    out["variants"] = len(gone)
    aliased_trims = {t for (t,) in conn.execute(select(S.trim_alias.c.trim_id))}
    gone = [t for (t,) in conn.execute(select(S.trim.c.id).where(S.trim.c.created_by == "rule"))
            if t not in trims and t not in aliased_trims]
    if gone:
        conn.execute(delete(S.trim).where(S.trim.c.id.in_(gone)))
    out["trims"] = len(gone)
    aliased_models = {m for (m,) in conn.execute(select(S.model_alias.c.model_id))}
    gone = [m for (m,) in conn.execute(select(S.model.c.id).where(S.model.c.created_by == "rule"))
            if m not in models and m not in aliased_models]
    if gone:
        conn.execute(delete(S.model).where(S.model.c.id.in_(gone)))
    out["models"] = len(gone)
    gone = [m for (m,) in conn.execute(select(S.make.c.id).where(S.make.c.created_by == "rule",
                                                                S.make.c.in_seed.is_(False)))
            if m not in makes]
    if gone:
        conn.execute(delete(S.make).where(S.make.c.id.in_(gone)))
    out["makes"] = len(gone)
    return out


def build_catalog(engine: Engine, raw_rows: list[dict], makes: Optional[MakeTable] = None) -> BuildReport:
    S.create_all(engine)
    with engine.connect() as conn:
        overrides = Overrides.load(conn)
    res = resolve(raw_rows, makes or MakeTable.load(), overrides)
    return write(engine, res)
