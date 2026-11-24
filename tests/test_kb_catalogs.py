"""Offline checks for the knowledge base: catalogs in the migration vs models.py, row hashing,
read-only SQLite access, URL handling. No database needed."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from typing import get_args

import pytest

from vehicle_scraper import models
from vehicle_scraper.kb import db, importer
from vehicle_scraper.models import VehicleRecord
from vehicle_scraper.storage import Storage

VERSIONS = Path(__file__).resolve().parents[1] / "src" / "vehicle_scraper" / "kb" / "migrations" / "versions"


def load_migration(name: str):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M1 = load_migration("0001_catalogs_staging")


def catalog_codes(table: str) -> list[str]:
    """Codes of a catalog after every migration: 0001's seed plus later CATALOG_ADDITIONS."""
    codes = [code for code, *_ in M1.CATALOGS[table][1]]
    for path in sorted(VERSIONS.glob("*.py")):
        if path.stem != "0001_catalogs_staging":
            codes += [code for code, *_ in getattr(load_migration(path.stem), "CATALOG_ADDITIONS", {})
                      .get(table, [])]
    return codes


@pytest.mark.parametrize("table, literal", [
    ("fuel_type", models.FuelType),
    ("transmission_type", models.TransmissionType),
    ("drivetrain", models.Drivetrain),
    ("body_style", models.VehicleType),
])
def test_catalog_codes_match_scraper_schema(table, literal):
    # The scraper's values must map 1:1 to catalog codes. If models.py gains a value,
    # this fails until a new migration inserts it (as CATALOG_ADDITIONS).
    assert sorted(catalog_codes(table)) == sorted(get_args(literal))


def test_catalog_seeds_are_well_formed():
    for table, (_comment, rows) in M1.CATALOGS.items():
        codes = [r[0] for r in rows]
        assert len(codes) == len(set(codes)), table
        assert all(code.isalnum() and es and en for code, es, en in rows), table
    assert {c for c, *_ in M1.COUNTRIES} == {"CO", "US", "IN", "GT"}
    countries = {c for c, *_ in M1.COUNTRIES}
    assert all(country in countries for _code, _name, country, _url, _notes in M1.SOURCE_SITES)


def test_segments_seed():
    m2 = load_migration("0002_segments")
    classes = {c for c, *_ in M1.VEHICLE_CLASSES}
    bodies = {c for c, *_ in M1.BODY_STYLES}
    codes = [s[0] for s in m2.SEGMENTS]
    assert len(codes) == len(set(codes)) and all(c.isalnum() for c in codes)
    assert all(cls in classes and (body is None or body in bodies) for *_, cls, body in m2.SEGMENTS)
    by_code = {s[0]: s for s in m2.SEGMENTS}
    assert [c for c in "ABCDEF" if by_code[c][3] == "car" and by_code[c][4] is None] == list("ABCDEF")
    assert {c for c, *_, body in m2.SEGMENTS if body == "Pickup"} == {"PickupCompact", "PickupMidsize",
                                                                      "PickupFullsize"}
    assert {c for c, _, _, cls, _ in m2.SEGMENTS if cls == "motorcycle"} >= {"Scooter", "Street", "Sport"}


def test_cofino_is_flagged_in_the_seed():
    cofino = next(s for s in M1.SOURCE_SITES if s[0] == "cofino")
    assert "ai-train=no" in cofino[4]


def test_row_hash_ignores_scraped_at_only():
    row = {"source_site": "carroya", "listing_id": "1", "make": "Kia", "scraped_at": "2026-01-01T00:00:00"}
    same = dict(row, scraped_at="2026-11-24T10:00:00")
    changed = dict(row, make="KIA")
    assert importer.row_hash(row) == importer.row_hash(same)
    assert importer.row_hash(row) != importer.row_hash(changed)
    assert importer.row_hash(row) == importer.row_hash(dict(reversed(list(row.items()))))


def _sqlite_with(tmp_path: Path, records: list[VehicleRecord]) -> Path:
    store = Storage(tmp_path / "data dir" / "vehicles.sqlite")    # a space, like the real path
    for r in records:
        store.save(r)
    store.close()
    return tmp_path / "data dir" / "vehicles.sqlite"


def test_read_sqlite_is_read_only(tmp_path):
    path = _sqlite_with(tmp_path, [VehicleRecord(source_site="carroya", source_url="u", listing_id="1",
                                                 make="Kia", model="Picanto", abs=True)])
    rows = list(importer.read_sqlite(path))
    assert rows[0]["make"] == "Kia" and rows[0]["abs"] == 1
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM vehicles")
    con.close()


def test_urls():
    assert db.libpq_url("postgresql+psycopg://u:p@h:5432/omnibase") == "postgresql://u:p@h:5432/omnibase"
    assert db.sqlalchemy_url("postgres://u@h/omnibase") == "postgresql+psycopg://u@h/omnibase"
    assert db.sqlalchemy_url("postgresql+psycopg2://u@h/omnibase") == "postgresql+psycopg://u@h/omnibase"


def test_missing_url_is_explained(monkeypatch):
    monkeypatch.delenv(db.ENV_VAR, raising=False)
    with pytest.raises(db.MissingDatabaseUrl, match="OMNIBASE_DATABASE_URL"):
        db.database_url()
    assert db.database_url("postgresql://x/omnibase") == "postgresql://x/omnibase"
