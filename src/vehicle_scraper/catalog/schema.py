"""Relational schema of the vehicle catalog (knowledge base).

    make ─< model ─< trim ─< variant ─< variant_market / variant_feature / variant_field_source / variant_override
                                  └─< listing (marketplace evidence, no personal data)

Defined with SQLAlchemy Core so one definition serves PostgreSQL (production: JSONB) and SQLite
(dev/tests: JSON). ``ddl()`` renders the PostgreSQL DDL (``catalog export-ddl``).

IDs are stable across rebuilds: ``build.py`` upserts entities by their natural key
(make slug, model slug within make, trim slug within model, variant_key within trim), so
listings and approved aliases keep pointing at the same rows when the catalog is recomputed.
"""
from __future__ import annotations

from typing import get_args

from sqlalchemy import (JSON, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Integer,
                        MetaData, PrimaryKeyConstraint, String, Table, Text, UniqueConstraint, create_engine)
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateIndex, CreateTable

from ..models import Drivetrain, FuelType, TransmissionType, VehicleType

JSONType = JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = DateTime(timezone=True)

VEHICLE_CLASSES = ("car", "moto", "heavy")
METHODS = ("rule", "ai", "human")                       # who decided an alias / created an entity
SOURCES = ("listing", "title", "consensus", "ai_knowledge", "human")   # where a value comes from
DECISION_STATUSES = ("pending", "accepted", "review", "rejected")
REVIEW_STATUSES = ("open", "approved", "rejected", "corrected")

metadata = MetaData(naming_convention={
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
})


def _in(col: str, values, nullable: bool = True) -> CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    expr = f"{col} IN ({allowed})"
    return CheckConstraint(f"{col} IS NULL OR {expr}" if nullable else expr, name=col)


def _confidence() -> Column:
    return Column("confidence", Float, CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
                                                       name="confidence_range"))


make = Table(
    "make", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(80), nullable=False),
    Column("slug", String(80), nullable=False, unique=True),
    Column("country_of_origin", String(60)),
    Column("in_seed", Boolean, nullable=False, default=False),     # listed in config/catalog/makes.yaml
    Column("created_by", String(10), nullable=False, default="rule"),
    _in("created_by", METHODS, nullable=False),
)

make_alias = Table(
    "make_alias", metadata,
    Column("alias_norm", String(120), primary_key=True),
    Column("make_id", Integer, ForeignKey("make.id", ondelete="CASCADE"), nullable=False),
    Column("method", String(10), nullable=False),
    _confidence(),
    _in("method", METHODS, nullable=False),
)

model = Table(
    "model", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("make_id", Integer, ForeignKey("make.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(120), nullable=False),
    Column("slug", String(120), nullable=False, index=True),
    Column("match_key", String(160), nullable=False),      # canonical.model_key: "Rav 4" / "RAV4" -> "rav4"
    Column("name_locked", Boolean, nullable=False, default=False),   # name set by AI/human: rebuilds keep it
    Column("vehicle_class", String(10), nullable=False, default="car"),
    # Model-level body style for variants whose listings don't state one (approved enrichment).
    Column("default_body_style", String(20)),
    Column("default_body_source", String(20)),
    Column("verified", Boolean, nullable=False, default=False),  # seen with a separate trim field / approved
    Column("created_by", String(10), nullable=False, default="rule"),
    UniqueConstraint("make_id", "match_key"),
    _in("vehicle_class", VEHICLE_CLASSES, nullable=False),
    _in("default_body_style", get_args(VehicleType)),
    _in("default_body_source", SOURCES),
    _in("created_by", METHODS, nullable=False),
)

model_alias = Table(
    "model_alias", metadata,
    Column("make_id", Integer, ForeignKey("make.id", ondelete="CASCADE"), nullable=False),
    Column("alias_norm", String(160), nullable=False),
    Column("model_id", Integer, ForeignKey("model.id", ondelete="CASCADE"), nullable=False),
    Column("method", String(10), nullable=False),
    _confidence(),
    PrimaryKeyConstraint("make_id", "alias_norm"),
    _in("method", METHODS, nullable=False),
)

trim = Table(
    "trim", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("model_id", Integer, ForeignKey("model.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(160), nullable=False),          # "" = trim not stated in the listings
    Column("slug", String(160), nullable=False),
    Column("match_key", String(160), nullable=False),
    Column("name_locked", Boolean, nullable=False, default=False),
    Column("created_by", String(10), nullable=False, default="rule"),
    UniqueConstraint("model_id", "match_key"),
    _in("created_by", METHODS, nullable=False),
)

trim_alias = Table(
    "trim_alias", metadata,
    Column("model_id", Integer, ForeignKey("model.id", ondelete="CASCADE"), nullable=False),
    Column("alias_norm", String(240), nullable=False),     # key(raw model) + "|" + key(raw trim)
    Column("trim_id", Integer, ForeignKey("trim.id", ondelete="CASCADE"), nullable=False),
    Column("attrs", JSONType),                             # specs read from the text (AI), fill gaps only
    Column("method", String(10), nullable=False),
    _confidence(),
    PrimaryKeyConstraint("model_id", "alias_norm"),
    _in("method", METHODS, nullable=False),
)

SPEC_COLUMNS = {   # variant spec column -> SQL type (same names as VehicleRecord)
    "body_style": String(20), "drivetrain": String(10), "engine_cylinders": Integer, "horsepower_hp": Integer,
    "doors": Integer, "seats": Integer, "fuel_tank_capacity_l": Float, "cargo_capacity_l": Integer,
    "wheel_size_in": Integer, "tire_size": String(20), "fuel_economy_kml": Float, "ev_range_km": Integer,
    "ev_charging_speed_kw": Float, "airbags_count": Integer, "screen_size_in": Float,
    "country_of_manufacture": String(60),
}
KEY_COLUMNS = ("model_year", "fuel_type", "transmission_type", "engine_displacement_l")

variant = Table(
    "variant", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("trim_id", Integer, ForeignKey("trim.id", ondelete="CASCADE"), nullable=False),
    Column("variant_key", String(120), nullable=False),    # "2019|Gasoline|Automatic|2.0" ("-" = unknown)
    Column("model_year", Integer),
    Column("fuel_type", String(10)),
    Column("transmission_type", String(10)),
    Column("engine_displacement_l", Float),
    *[Column(name, type_) for name, type_ in SPEC_COLUMNS.items()],
    Column("n_listings", Integer, nullable=False, default=0),
    Column("needs_review", Boolean, nullable=False, default=False),
    Column("created_by", String(10), nullable=False, default="rule"),
    UniqueConstraint("trim_id", "variant_key"),
    _in("body_style", get_args(VehicleType)),
    _in("fuel_type", get_args(FuelType)),
    _in("transmission_type", get_args(TransmissionType)),
    _in("drivetrain", get_args(Drivetrain)),
    CheckConstraint("model_year IS NULL OR model_year BETWEEN 1900 AND 2100", name="model_year_range"),
    _in("created_by", METHODS, nullable=False),
)

variant_market = Table(
    "variant_market", metadata,
    Column("variant_id", Integer, ForeignKey("variant.id", ondelete="CASCADE"), nullable=False),
    Column("country", String(2), nullable=False),
    Column("first_listed", TS),
    Column("last_listed", TS),
    Column("n_listings", Integer, nullable=False, default=0),
    PrimaryKeyConstraint("variant_id", "country"),
)

feature = Table(
    "feature", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("code", String(40), nullable=False, unique=True),   # = VehicleRecord boolean field name
    Column("category", String(20), nullable=False),
    Column("name_es", String(80), nullable=False),
    Column("name_en", String(80), nullable=False),
)

variant_feature = Table(
    "variant_feature", metadata,
    Column("variant_id", Integer, ForeignKey("variant.id", ondelete="CASCADE"), nullable=False),
    Column("feature_id", Integer, ForeignKey("feature.id", ondelete="CASCADE"), nullable=False),
    Column("n_true", Integer, nullable=False, default=0),
    Column("n_false", Integer, nullable=False, default=0),
    Column("n_listings", Integer, nullable=False, default=0),
    PrimaryKeyConstraint("variant_id", "feature_id"),
)

variant_field_source = Table(
    "variant_field_source", metadata,
    Column("variant_id", Integer, ForeignKey("variant.id", ondelete="CASCADE"), nullable=False),
    Column("field", String(40), nullable=False),
    Column("value", Text),
    Column("source", String(20), nullable=False),
    Column("n_support", Integer, nullable=False, default=0),
    Column("n_conflict", Integer, nullable=False, default=0),
    _confidence(),
    PrimaryKeyConstraint("variant_id", "field"),
    _in("source", SOURCES, nullable=False),
)

# A person's value for a spec, set from the review queue. `build` applies it over the listing consensus on
# every rebuild (source "human"). Key fields (year, fuel, gearbox, engine size) can't be overridden: they
# define the variant itself.
variant_override = Table(
    "variant_override", metadata,
    Column("variant_id", Integer, ForeignKey("variant.id", ondelete="CASCADE"), nullable=False),
    Column("field", String(40), nullable=False),
    Column("value", JSONType, nullable=False),
    Column("decided_by", String(80)),
    Column("decided_at", TS),
    PrimaryKeyConstraint("variant_id", "field"),
    _in("field", SPEC_COLUMNS, nullable=False),
)

listing = Table(
    "listing", metadata,
    Column("source_site", String(40), nullable=False),
    Column("listing_id", String(120), nullable=False),
    Column("variant_id", Integer, ForeignKey("variant.id", ondelete="SET NULL"), index=True),
    Column("country", String(2)),
    Column("source_url", Text),
    Column("price", Float),
    Column("currency", String(3)),
    Column("mileage_km", Integer),
    Column("model_year", Integer),
    Column("raw_make", String(120)),
    Column("raw_model", String(160)),
    Column("raw_trim", String(240)),
    Column("match_method", String(10)),
    _confidence(),
    Column("listed_at", TS),
    Column("scraped_at", TS),
    Column("raw", JSONType),                               # the scraped row (the schema holds no personal data)
    PrimaryKeyConstraint("source_site", "listing_id"),
    _in("match_method", METHODS),
)

ai_run = Table(
    "ai_run", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("batch_id", String(80), unique=True),
    Column("model", String(40), nullable=False),
    Column("prompt_version", String(20), nullable=False),
    Column("status", String(20), nullable=False),          # prepared | submitted | ended | ingested
    Column("n_requests", Integer, nullable=False, default=0),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("cache_read_tokens", Integer, nullable=False, default=0),
    Column("cache_write_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("cost_usd", Float),
    Column("created_at", TS, nullable=False),
    Column("ended_at", TS),
)

ai_decision = Table(
    "ai_decision", metadata,
    Column("input_hash", String(64), primary_key=True),    # ai_batch.item_hash: sha256(prompt_version|kind|make|key)
    # key = model match_key for models; raw trim alias for trims (no model, so a model merge doesn't re-ask)
    Column("ai_run_id", Integer, ForeignKey("ai_run.id", ondelete="SET NULL")),
    Column("custom_id", String(64), nullable=False),
    Column("item_kind", String(10), nullable=False),       # model | trim
    Column("request", JSONType, nullable=False),           # the line sent (TSV fields as a dict)
    Column("response", JSONType),                          # the validated item returned
    Column("status", String(10), nullable=False, default="pending"),
    Column("notes", Text),
    Column("created_at", TS, nullable=False),
    _in("status", DECISION_STATUSES, nullable=False),
)

review_item = Table(
    "review_item", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("entity_type", String(20), nullable=False),     # make | model | trim | variant
    Column("entity_key", String(300), nullable=False),     # natural key, e.g. "toyota/rav4"
    Column("reason", String(40), nullable=False),
    Column("detail", Text),
    Column("proposal", JSONType),                          # what to apply if approved
    Column("status", String(10), nullable=False, default="open"),
    Column("decided_by", String(80)),
    Column("decided_at", TS),
    UniqueConstraint("entity_type", "entity_key", "reason"),
    _in("status", REVIEW_STATUSES, nullable=False),
)


def get_engine(url: str) -> Engine:
    engine = create_engine(url, future=True)
    if engine.dialect.name == "sqlite":
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):                         # SQLite enforces FKs only when asked
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
            # pysqlite opens transactions on its own and breaks SAVEPOINT (a RELEASE can commit
            # everything): let SQLAlchemy emit BEGIN itself, as its SQLite docs recommend.
            dbapi_conn.isolation_level = None

        @event.listens_for(engine, "begin")
        def _begin(conn):
            conn.exec_driver_sql("BEGIN")
    return engine


def create_all(engine: Engine) -> None:
    metadata.create_all(engine)


def ddl(dialect: str = "postgresql") -> str:
    """CREATE TABLE / CREATE INDEX statements for ``dialect`` (default PostgreSQL)."""
    d = {"postgresql": postgresql.dialect()}.get(dialect)
    if d is None:
        from sqlalchemy.dialects import sqlite
        d = sqlite.dialect()
    out = []
    for t in metadata.sorted_tables:
        out.append(str(CreateTable(t).compile(dialect=d)).strip() + ";")
        out += [str(CreateIndex(ix).compile(dialect=d)).strip() + ";" for ix in t.indexes]
    return "\n\n".join(out) + "\n"
