"""Knowledge base against a real PostgreSQL. Skipped unless OMNIBASE_TEST_DATABASE_URL points at
a throwaway database (never omnibase itself: the tests drop and recreate the schemas), e.g.

    docker run -d --name omnibase-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=omnibase_test \
        -p 55441:5432 postgres:16-alpine
    OMNIBASE_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55441/omnibase_test python -m pytest tests/test_kb_pg.py
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("alembic")

from alembic import command  # noqa: E402

from vehicle_scraper.cli import main  # noqa: E402
from vehicle_scraper.kb.cli import alembic_config  # noqa: E402
from vehicle_scraper.kb.importer import import_sqlite  # noqa: E402
from vehicle_scraper.models import VehicleRecord  # noqa: E402
from vehicle_scraper.storage import Storage  # noqa: E402

URL = os.getenv("OMNIBASE_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="OMNIBASE_TEST_DATABASE_URL not set")


@pytest.fixture
def conn(monkeypatch):
    # Set (empty) so migration 0008 never picks the developer's own address from .env.
    monkeypatch.setenv("KB_FIRST_EDITOR_EMAIL", "")
    cfg = alembic_config(URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    # autocommit: a test's SELECT must not hold locks that a migration run by the same test
    # (or the next test's downgrade) would wait on. import_sqlite opens its own transaction.
    with psycopg.connect(URL, autocommit=True) as c:
        yield c


def rec(site="carroya", listing_id="1", **kw) -> VehicleRecord:
    base = dict(source_site=site, source_url=f"https://example/{listing_id}", listing_id=listing_id,
                make="Hyundai", model="Creta", trim="Advance 1.6 Suv Automatico 4x2", model_year=2022)
    return VehicleRecord(**(base | kw))


def write_sqlite(path: Path, records) -> Path:
    path.unlink(missing_ok=True)
    store = Storage(path)
    for r in records:
        store.save(r)
    store.close()
    return path


def q(conn, sql, *args):
    with conn.cursor() as cur:
        cur.execute(sql, args or None)
        return cur.fetchall()


def test_migration_seeds_catalogs(conn):
    assert q(conn, "SELECT code FROM kb.fuel_type ORDER BY sort_order") == [
        ("Gasoline",), ("Diesel",), ("Hybrid",), ("EV",), ("CNG",), ("Flex",)]
    assert q(conn, "SELECT count(*) FROM kb.body_style") == [(11,)]
    assert q(conn, "SELECT vehicle_class_code, count(*) FROM kb.segment GROUP BY 1 ORDER BY 1") \
        == [("car", 9), ("motorcycle", 7)]
    assert q(conn, "SELECT code FROM kb.segment WHERE body_style_code = 'Pickup' ORDER BY sort_order") \
        == [("PickupCompact",), ("PickupMidsize",), ("PickupFullsize",)]
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        q(conn, "INSERT INTO kb.segment VALUES ('X', 'x', 'x', 0, true, 'truck', NULL)")
    assert q(conn, "SELECT country_code, ai_allowed, training_allowed FROM kb.source_site WHERE code='cofino'") \
        == [("GT", False, False)]
    with pytest.raises(psycopg.errors.CheckViolation):
        q(conn, "INSERT INTO kb.country VALUES ('col', 'x', 'x', 'COP', true)")


def test_segments_downgrade_and_upgrade_again(conn):
    cfg = alembic_config(URL)
    command.downgrade(cfg, "0001_catalogs_staging")
    assert q(conn, "SELECT count(*) FROM kb.segment") == [(0,)]
    assert q(conn, "SELECT count(*) FROM kb.fuel_type WHERE code = 'Flex'") == [(0,)]
    command.upgrade(cfg, "head")
    assert q(conn, "SELECT count(*) FROM kb.segment") == [(16,)]


def test_import_versions_and_idempotency(conn, tmp_path):
    db = tmp_path / "vehicles.sqlite"
    write_sqlite(db, [rec(listing_id="1"), rec(listing_id="2", model_year=2024),
                      rec(site="tucarro", listing_id="9")])
    s1 = import_sqlite(conn, db)
    assert (s1["new_listings"], s1["new_versions"], s1["unchanged"]) == (2, 0, 0)
    assert s1["skipped"] == {"tucarro": 1}                      # site not registered: not guessed

    # Same file again: still re-read, because the first import skipped rows; nothing new.
    s2 = import_sqlite(conn, db)
    assert (s2["status"], s2["new_listings"], s2["new_versions"], s2["unchanged"]) == ("imported", 0, 0, 2)

    # Re-scrape: listing 1 unchanged except scraped_at, listing 2 changed, listing 3 new.
    write_sqlite(db, [rec(listing_id="1"), rec(listing_id="2", model_year=2025), rec(listing_id="3")])
    s3 = import_sqlite(conn, db)
    assert (s3["new_listings"], s3["new_versions"], s3["unchanged"]) == (1, 1, 1)
    assert q(conn, "SELECT version, valid_to IS NULL, (data->>'model_year')::int FROM staging.raw_listing "
                   "WHERE listing_id='2' ORDER BY version") == [(1, False, 2024), (2, True, 2025)]
    assert q(conn, "SELECT count(*), min(country_code) FROM staging.current_listing") == [(3, "CO")]

    # A fully imported file is skipped by its sha256, unless forced.
    assert import_sqlite(conn, db)["status"] == "already_imported"
    assert import_sqlite(conn, db, force=True)["unchanged"] == 3


def test_raw_row_is_kept_as_read(conn, tmp_path):
    db = write_sqlite(tmp_path / "v.sqlite", [rec(abs=True, parse_warnings=["could not parse x from 'y'"])])
    import_sqlite(conn, db)
    data = q(conn, "SELECT data FROM staging.raw_listing")[0][0]
    assert data["abs"] == 1 and data["trim"] == "Advance 1.6 Suv Automatico 4x2"
    assert data["parse_warnings"] == "could not parse x from 'y'"


def test_cli_migrate_import_status(conn, tmp_path, capsys):
    db = write_sqlite(tmp_path / "v.sqlite", [rec()])
    assert main(["kb", "--database-url", URL, "migrate"]) == 0
    assert main(["kb", "--database-url", URL, "import", "--sqlite", str(db)]) == 0
    assert main(["kb", "--database-url", URL, "status"]) == 0
    out = capsys.readouterr().out
    assert "1 new listings" in out and "carroya" in out and "fuel_type=6" in out


# --- kb clean ---------------------------------------------------------------------------------
from vehicle_scraper.kb.clean import clean  # noqa: E402


def cleaned(conn, tmp_path, records, today=None):
    db = write_sqlite(tmp_path / "c.sqlite", records)
    import_sqlite(conn, db, force=True)
    from datetime import date
    return clean(conn, today=today or date(2026, 11, 24))


def test_clean_identity_scope_and_fields(conn, tmp_path):
    recs = [rec(listing_id=str(i), make="HYUNDAI" if i % 2 else "Hyundai", model="CRETA",
                trim="Advance 1.6 Suv Automatico 4x2", transmission_type="Automatic") for i in range(5)]
    recs += [
        rec(listing_id="w1", make="Kia", model="Rarito", trim="LX"),                  # weak model
        rec(listing_id="u1", make="Zorgmobil", model="Z1", trim=None),                 # unknown make
        rec(listing_id="h1", make="Kenworth", model="T800", trim=None),                # heavy make
        rec(listing_id="c1", make="Ford", model="Mustang", trim="GT", model_year=1967),  # classic
        rec(listing_id="a1", make="Yamaha", model="Raptor", trim="700 Cuatrimoto", vehicle_type="Motorcycle"),
        rec(listing_id="t1", make="Bajaj", model="Motocarro", trim="Torito", vehicle_type="Motorcycle"),
        rec(listing_id="x1", make="Chevrolet", model="1.3", trim="LS"),                # model is attributes
        rec(listing_id="k1", make="Toyota", model="Hilux", trim="2.8 4x4 Aut", drivetrain="2WD",
            engine_displacement_l=2.4),                                                # conflicts
        rec(listing_id="v1", make="Renault", model="Duster", trim="Intens 4x2 CVT", transmission_type="Automatic",
            drivetrain="2WD"),                                                         # CVT refines Automatic
    ]
    s = cleaned(conn, tmp_path, recs)
    assert s["excluded"] == {"ATV": 1, "Classic": 1, "Heavy": 1, "ThreeWheeler": 1}
    # One model for all spellings, accepted (5 listings), with the trim cleaned once.
    rows = q(conn, """SELECT m.name, m.status, l.trim_name, l.engine_displacement_l::float, l.body_style_code,
                             l.transmission_type_code, l.drivetrain_code, l.provenance->>'body_style'
                      FROM kb.clean_listing l JOIN kb.model m ON m.id = l.model_id
                      WHERE l.listing_id = '0'""")
    assert rows == [("Creta", "accepted", "Advance", 1.6, "SUV", "Automatic", "2WD", "trim_text")]
    assert q(conn, "SELECT count(DISTINCT model_id) FROM kb.clean_listing WHERE listing_id ~ '^[0-4]$'") == [(1,)]
    pending = dict(q(conn, "SELECT issue, count(*) FROM kb.review_item WHERE status='pending' GROUP BY 1"))
    assert pending == {"weak_model": 4, "unknown_make": 1, "model_is_attributes": 1, "field_conflict": 2}
    # Hilux: structured values stay, the name's go to the case.
    assert q(conn, "SELECT drivetrain_code, engine_displacement_l::float FROM kb.clean_listing "
                   "WHERE listing_id='k1'") == [("2WD", 2.4)]
    assert q(conn, "SELECT field, current_value, proposed_value FROM kb.review_item "
                   "WHERE issue='field_conflict' ORDER BY field") == [
        ("drivetrain", "2WD", "4WD"), ("engine_displacement_l", 2.4, 2.8)]
    assert q(conn, "SELECT status FROM kb.make WHERE name='Zorgmobil'") == [("pending_review",)]
    assert q(conn, "SELECT transmission_type_code, provenance->>'transmission_type', drivetrain_code "
                   "FROM kb.clean_listing WHERE listing_id='v1'") == [("CVT", "trim_text_refines_listing", "2WD")]
    assert q(conn, "SELECT listing_id, vehicle_class_code FROM kb.clean_listing WHERE listing_id IN ('h1', 't1') "
                   "ORDER BY 1") == [("h1", None), ("t1", None)]


def test_clean_is_idempotent_and_keeps_decisions(conn, tmp_path):
    recs = [rec(listing_id="w1", make="Kia", model="Rarito", trim="LX")]
    cleaned(conn, tmp_path, recs)
    conn.execute("UPDATE kb.review_item SET status='approved', decided_by='test', decided_at=now() "
                 "WHERE issue='weak_model'")
    s = cleaned(conn, tmp_path, recs)
    assert q(conn, "SELECT status, source FROM kb.model WHERE name='Rarito'") == [("accepted", "manual")]
    assert q(conn, "SELECT status FROM kb.review_item") == [("approved",)]          # not asked again
    assert s["review_pending"] == {}
    assert q(conn, "SELECT count(*) FROM kb.model") == [(1,)] and q(conn, "SELECT count(*) FROM kb.clean_listing") == [(1,)]


def test_clean_obsoletes_cases_that_went_away(conn, tmp_path):
    cleaned(conn, tmp_path, [rec(listing_id="w1", make="Kia", model="Rarito", trim="LX")])
    more = [rec(listing_id=f"w{i}", make="Kia", model="Rarito", trim="LX") for i in range(1, 6)]
    cleaned(conn, tmp_path, more)                                   # now 5 listings: accepted by rule
    assert q(conn, "SELECT status FROM kb.model WHERE name='Rarito'") == [("accepted",)]
    assert q(conn, "SELECT status FROM kb.review_item WHERE issue='weak_model'") == [("obsolete",)]


def test_clean_model_family_and_chassis_cab(conn, tmp_path):
    recs = [rec(listing_id=f"d{i}", make="KTM", model="Duke", trim="390 NG", vehicle_type="Motorcycle",
                engine_displacement_l=0.373) for i in range(5)]
    recs += [rec(site="driveway", listing_id=f"r{i}", make="Ram", model="3500 Cab/Chassis", trim="Tradesman",
                 body_style="Truck", vehicle_type="Truck", model_year=2025) for i in range(5)]
    cleaned(conn, tmp_path, recs)
    assert q(conn, "SELECT DISTINCT m.name, l.trim_name, l.body_style_code, l.vehicle_class_code FROM kb.clean_listing l "
                   "JOIN kb.model m ON m.id=l.model_id WHERE l.listing_id LIKE 'd%'") == [
        ("Duke 390", "NG", "Motorcycle", "motorcycle")]
    assert q(conn, "SELECT DISTINCT excluded_reason, body_style_code, provenance->>'body_style' "
                   "FROM kb.clean_listing WHERE listing_id LIKE 'r%'") == [(None, "Pickup", "chassis_cab")]


# --- kb build ---------------------------------------------------------------------------------
from vehicle_scraper.kb.build import build  # noqa: E402


def built(conn, tmp_path, records):
    cleaned(conn, tmp_path, records)
    return build(conn)


def creta(listing_id, year, disp, *, site="carroya", trim="Advance", **kw):
    return rec(site=site, listing_id=listing_id, **({"make": "Hyundai", "model": "Creta", "trim": trim,
               "model_year": year, "engine_displacement_l": disp, "fuel_type": "Gasoline",
               "transmission_type": "Automatic", "body_style": "SUV"} | kw))


def test_build_levels_and_publishing(conn, tmp_path):
    recs = [creta(f"a{i}", 2017, 1.6, drivetrain="FWD", horsepower_hp=121, sunroof=True) for i in range(4)]
    recs += [creta(f"b{i}", 2021, 1.5, drivetrain="FWD", sunroof=i < 3) for i in range(4)]
    recs += [creta("n1", 2021, 1.5)]                                  # no drivetrain: joins the only 1.5
    recs += [creta("u1", 2021, None, site="cars24", trim=None, body_style=None)]   # no body, no trim, IN
    s = built(conn, tmp_path, recs)
    # u1 has no displacement and no drivetrain: compatible with both engines, so it isn't guessed.
    assert s["assigned"] == 9 and s["unassigned"] == {"ambiguous_powertrain": 1}
    assert q(conn, "SELECT count(*), min(status) FROM kb.generation WHERE listings > 0") == [(1, "provisional")]
    assert q(conn, "SELECT engine_displacement_l::float, drivetrain_code, horsepower_hp, listings FROM kb.powertrain "
                   "WHERE listings > 0 ORDER BY 1") == [(1.5, "FWD", None, 5), (1.6, "FWD", 121, 4)]
    assert q(conn, "SELECT generation_id IS NOT NULL FROM kb.listing_level WHERE listing_id = 'u1'") == [(True,)]
    # equipment: 4/4 sunroof on the 1.6, 3/4 (75 %) on the 1.5 -> both published True
    assert q(conn, "SELECT DISTINCT sunroof FROM kb.commercial_variant WHERE trim_key = 'advance'") == [(True,)]
    # The engine changes between 2017 and 2021: a split is proposed, not made.
    split = q(conn, "SELECT proposed_value FROM kb.review_item WHERE issue = 'generation_split'")
    assert split == [({"year_from": 2021},)]


def test_build_ambiguous_powertrain_is_not_guessed(conn, tmp_path):
    recs = [creta(f"a{i}", 2017, 1.6, drivetrain="FWD") for i in range(3)]
    recs += [creta(f"b{i}", 2017, 2.0, drivetrain="FWD") for i in range(3)]
    recs += [creta("x1", 2017, None, drivetrain="FWD")]               # 1.6 or 2.0? unknown
    s = built(conn, tmp_path, recs)
    assert s["unassigned"] == {"ambiguous_powertrain": 1}
    assert q(conn, "SELECT generation_id IS NOT NULL, powertrain_id, unassigned_reason FROM kb.listing_level "
                   "WHERE listing_id = 'x1'") == [(True, None, "ambiguous_powertrain")]


def test_build_never_recreates_a_rejected_powertrain(conn, tmp_path):
    recs = [creta(f"a{i}", 2017, 1.6, drivetrain="FWD") for i in range(3)]
    recs += [creta(f"b{i}", 2017, 2.0, drivetrain="FWD") for i in range(3)]
    recs += [creta("y1", 2017, 1.6)]                                  # no drivetrain: only the 1.6 fits
    built(conn, tmp_path, recs)
    pid = q(conn, "SELECT id FROM kb.powertrain WHERE engine_displacement_l = 1.6")[0][0]
    conn.execute("UPDATE kb.powertrain SET status = 'rejected' WHERE id = %s", (pid,))
    s = build(conn)                       # used to fail: UNIQUE (generation_id, match_key)
    assert s["unassigned"] == {"powertrain_rejected": 4}
    assert q(conn, "SELECT listing_id, powertrain_id, unassigned_reason FROM kb.listing_level "
                   "WHERE listing_id IN ('a0', 'y1', 'b0') ORDER BY 1") == [
        ("a0", None, "powertrain_rejected"), ("b0", q(conn, "SELECT id FROM kb.powertrain WHERE "
                                                           "engine_displacement_l = 2.0")[0][0], None),
        ("y1", None, "powertrain_rejected")]
    assert q(conn, "SELECT count(*), max(listings) FROM kb.powertrain WHERE engine_displacement_l = 1.6") == [(1, 0)]
    # Taking the rejection back brings the listings back on the next build.
    conn.execute("UPDATE kb.powertrain SET status = 'provisional' WHERE id = %s", (pid,))
    assert build(conn)["unassigned"] == {}


def test_build_gives_no_listings_to_a_rejected_variant(conn, tmp_path):
    recs = [creta(f"a{i}", 2017, 1.6, drivetrain="FWD", horsepower_hp=121) for i in range(3)]
    recs += [creta(f"s{i}", 2017, 1.6, drivetrain="FWD", trim="Limited") for i in range(2)]
    built(conn, tmp_path, recs)
    vid = q(conn, "SELECT id FROM kb.commercial_variant WHERE trim_key = 'advance'")[0][0]
    pid = q(conn, "SELECT id FROM kb.powertrain")[0][0]
    conn.execute("UPDATE kb.commercial_variant SET status = 'rejected' WHERE id = %s", (vid,))
    s = build(conn)
    assert s["assigned"] == 2 and s["unassigned"] == {"variant_rejected": 3}
    # they keep their generation and powertrain; the variant isn't recreated and has no listings
    assert q(conn, "SELECT generation_id IS NOT NULL, powertrain_id, variant_id, unassigned_reason "
                   "FROM kb.listing_level WHERE listing_id = 'a0'") == [(True, pid, None, "variant_rejected")]
    assert q(conn, "SELECT count(*), max(listings) FROM kb.commercial_variant WHERE trim_key = 'advance'") == [(1, 0)]
    assert q(conn, "SELECT listings FROM kb.powertrain") == [(5,)]
    # the final record inherits the powertrain and keeps the reason
    assert q(conn, "SELECT powertrain_id, variant_id, horsepower_hp, unassigned_reason FROM kb.final_listing "
                   "WHERE listing_id = 'a0'") == [(pid, None, 121, "variant_rejected")]
    # Taking the rejection back brings the listings back on the next build.
    conn.execute("UPDATE kb.commercial_variant SET status = 'provisional' WHERE id = %s", (vid,))
    assert build(conn)["unassigned"] == {}
    assert q(conn, "SELECT variant_id FROM kb.listing_level WHERE listing_id = 'a0'") == [(vid,)]


def decide_now(conn, case, decision, corrected=None):
    from vehicle_scraper.kb.review import record_decision
    with conn.transaction(), conn.cursor() as cur:
        return record_decision(cur, case, decision, corrected, None, None, "test")


def outside_case(conn, field):
    return q(conn, "SELECT id, status, current_value, proposed_value, listings_affected, evidence "
                   "FROM kb.review_item WHERE issue = 'year_outside_generation' AND field = %s", field)[0]


def test_years_outside_the_cycle_propose_extending_it(conn, tmp_path):
    from vehicle_scraper.kb.review import InvalidDecision
    recs = [creta(f"a{i}", 2017, 1.6, drivetrain="FWD") for i in range(5)]      # 5: an accepted model
    built(conn, tmp_path, recs)
    gid = q(conn, "SELECT id FROM kb.generation")[0][0]
    conn.execute("UPDATE kb.generation SET year_from = 2016, year_to = 2019 WHERE id = %s", (gid,))
    # a reimport brings years after and before the official cycle
    recs += [creta("n1", 2021, 1.6, drivetrain="FWD"), creta("n2", 2021, 1.6, drivetrain="FWD"),
             creta("n3", 2022, 1.6, drivetrain="FWD"), creta("o1", 2014, 1.6, drivetrain="FWD")]
    s = built(conn, tmp_path, recs)
    assert s["unassigned"] == {"no_generation_for_year": 4}
    to_id, status, current, proposed, n, evidence = outside_case(conn, "year_to")
    assert (status, current, proposed, n) == ("pending", 2019, 2022, 3)
    assert evidence["years"] == {"2021": 2, "2022": 1} and evidence["boundary"] == 2019
    from_id, status, current, proposed, n, _ = outside_case(conn, "year_from")
    assert (status, current, proposed, n) == ("pending", 2016, 2014, 1)

    # a correction must extend the cycle
    with pytest.raises(InvalidDecision, match="no extiende"):
        decide_now(conn, from_id, "corregir", 2017)
    assert decide_now(conn, to_id, "aprobar") == "approved"
    assert decide_now(conn, from_id, "rechazar") == "rejected"
    # nothing moves until the recalculation, which extends the end and assigns those listings
    assert q(conn, "SELECT year_from, year_to FROM kb.generation WHERE id = %s", gid) == [(2016, 2019)]
    recs += [creta("o2", 2015, 1.6, drivetrain="FWD")]       # older, but within the rejected proposal
    s = built(conn, tmp_path, recs)
    assert q(conn, "SELECT year_from, year_to, source FROM kb.generation WHERE id = %s", gid) == [(2016, 2022, "manual")]
    assert s["unassigned"] == {"no_generation_for_year": 2}
    assert s["review_pending"].get("year_outside_generation") is None    # decided years aren't asked again
    assert outside_case(conn, "year_from")[1] == "rejected"

    # years beyond both decisions ask again, keeping the earlier decision
    recs += [creta("n4", 2023, 1.6, drivetrain="FWD"), creta("o3", 2013, 1.6, drivetrain="FWD")]
    built(conn, tmp_path, recs)
    _, status, current, proposed, n, evidence = outside_case(conn, "year_to")
    assert (status, current, proposed, n) == ("pending", 2022, 2023, 1)
    assert evidence["previous"]["status"] == "approved" and evidence["previous"]["proposed"] == 2022
    _, status, current, proposed, _, evidence = outside_case(conn, "year_from")
    assert (status, current, proposed) == ("pending", 2016, 2013)
    assert evidence["previous"]["status"] == "rejected"


def test_years_of_a_rejected_generation_propose_nothing(conn, tmp_path):
    recs = [creta(f"a{i}", 2017, 1.6, drivetrain="FWD") for i in range(4)]
    recs += [creta(f"b{i}", 2021, 1.5, drivetrain="FWD") for i in range(4)]
    built(conn, tmp_path, recs)
    gid = q(conn, "SELECT id FROM kb.generation")[0][0]
    with conn.cursor() as cur:
        from vehicle_scraper.kb.build import split_generation
        new = split_generation(cur, gid, 2021)
    conn.execute("UPDATE kb.generation SET status = 'rejected' WHERE id = %s", (new,))
    s = build(conn)
    assert s["unassigned"] == {"no_generation_for_year": 4}
    assert q(conn, "SELECT count(*) FROM kb.review_item WHERE issue = 'year_outside_generation'") == [(0,)]


def test_specs_template_round_trip(conn, tmp_path):
    from vehicle_scraper.kb.specs import GENERATIONS, POWERTRAINS, export_specs, import_specs
    from vehicle_scraper.xlsx import Sheet, read_sheet, write_workbook
    built(conn, tmp_path, [creta(f"a{i}", 2017, 1.6, drivetrain="FWD", horsepower_hp=121) for i in range(5)])
    gid = q(conn, "SELECT id FROM kb.generation")[0][0]
    pid = q(conn, "SELECT id FROM kb.powertrain")[0][0]
    out = tmp_path / "specs.xlsx"
    assert export_specs(conn, out) == {"file": str(out), "generations": 1, "powertrains": 1}
    gens, pts = read_sheet(out, GENERATIONS), read_sheet(out, POWERTRAINS)
    gh, ph = gens[0], pts[0]
    assert gens[1][gh.index("id")] == gid and pts[1][ph.index("potencia hp")] == 121   # what the base has now

    def row(header, base, **cells):
        r = list(base) + [None] * (len(header) - len(base))
        for k, v in cells.items():
            r[header.index(k)] = v
        return r
    gens_rows = [row(gh, gens[1], **{"largo mm": 4300, "segmento": "B", "año inicio": 2015, "año fin": 2020,
                                     "fuente": "Ficha Hyundai 2017", "nota": "versión colombiana"}),
                 row(gh, gens[1], **{"largo mm": 4400}),                       # no source
                 row(gh, gens[1], **{"segmento": "PickupMidsize", "fuente": "x"}),   # not for an SUV
                 row(gh, [999999], **{"largo mm": 4300, "fuente": "x"})]
    pts_rows = [row(ph, pts[1], **{"torque Nm": 151, "potencia hp": 140, "velocidades": 6, "fuente": "Ficha"}),
                row(ph, pts[1], **{"velocidades": 40, "fuente": "x"})]       # out of range
    filled = tmp_path / "filled.xlsx"
    write_workbook(filled, [Sheet(GENERATIONS, gh, gens_rows), Sheet(POWERTRAINS, ph, pts_rows)])

    s = import_specs(conn, filled, "Ana")
    assert s["saved"] == {"generation_values": 2, "cycle_opened": 1, "generation_rows": 1, "powertrain_values": 3,
                          "powertrain_rows": 1}
    assert [(e["sheet"], e["row"], e["error"]) for e in s["errors"]] == [
        (GENERATIONS, 3, "falta la fuente"),
        (GENERATIONS, 4, "el segmento PickupMidsize solo aplica a carrocería Pickup"),
        (GENERATIONS, 5, "no existe"),
        (POWERTRAINS, 3, "40 está fuera del rango 1-12 de gears")]
    # published at once (the import ran build): the source beats the listings
    assert q(conn, "SELECT length_mm, segment_code, year_from, year_to FROM kb.generation") == [(4300, "B", None, None)]
    assert q(conn, "SELECT torque_nm, horsepower_hp, gears FROM kb.powertrain") == [(151, 140, 6)]
    assert q(conn, "SELECT detail->>'source', detail->>'captured_by', detail->>'note' FROM kb.spec_evidence "
                   "WHERE source_kind = 'external' AND field = 'length_mm'") == [
        ("Ficha Hyundai 2017", "Ana", "versión colombiana")]
    # the listings say 121 hp, more than 10 % from the source: a case, the source's value stays
    assert q(conn, "SELECT current_value, proposed_value, evidence->'external' FROM kb.review_item "
                   "WHERE issue = 'spec_disagreement' AND field = 'horsepower_hp'") == [(140, 121, 140)]
    # the cycle waits for a person
    case, current, proposed = q(conn, "SELECT id, current_value, proposed_value FROM kb.review_item "
                                      "WHERE issue = 'generation_cycle'")[0]
    assert (current, proposed) == ({"year_from": None, "year_to": None}, {"year_from": 2015, "year_to": 2020})
    assert decide_now(conn, case, "aprobar") == "approved"
    build(conn)
    assert q(conn, "SELECT year_from, year_to, source FROM kb.generation") == [(2015, 2020, "external")]
    assert q(conn, "SELECT count(*) FROM kb.listing_level WHERE generation_id = %s", gid) == [(5,)]
    # importing the same file again changes nothing and asks nothing
    s = import_specs(conn, filled, "Ana")
    assert s["saved"] == {} and "build" not in s
    assert pid == q(conn, "SELECT id FROM kb.powertrain")[0][0]


def test_cycle_corrections_are_validated():
    from vehicle_scraper.kb.review import InvalidDecision, parse_cycle
    assert parse_cycle("2017-2022") == {"year_from": 2017, "year_to": 2022}
    assert parse_cycle(" 2017 - ") == {"year_from": 2017, "year_to": None}
    for bad in ("2022-2017", "2017", "abc", None):
        with pytest.raises(InvalidDecision):
            parse_cycle(bad)


def test_a_verified_variant_keeps_its_values(conn, tmp_path):
    recs = [creta(f"a{i}", 2017, 1.6, drivetrain="FWD", sunroof=True) for i in range(5)]
    built(conn, tmp_path, recs)
    vid = q(conn, "SELECT id FROM kb.commercial_variant")[0][0]
    assert q(conn, "SELECT sunroof, leather_seats FROM kb.commercial_variant") == [(True, None)]
    conn.execute("UPDATE kb.commercial_variant SET status = 'verified' WHERE id = %s", (vid,))
    # new listings say otherwise (12 of 17 without sunroof) and bring a value the variant lacked
    recs += [creta(f"b{i}", 2017, 1.6, drivetrain="FWD", sunroof=False) for i in range(12)]
    recs = [r.model_copy(update={"leather_seats": True}) for r in recs]
    built(conn, tmp_path, recs)
    assert q(conn, "SELECT sunroof, leather_seats FROM kb.commercial_variant") == [(True, True)]
    case, current, proposed, evidence = q(conn, "SELECT id, current_value, proposed_value, evidence FROM kb.review_item "
                                                "WHERE issue = 'spec_disagreement' AND field = 'sunroof'")[0]
    assert (current, proposed, evidence["verified"]) == (True, False, True)
    # the frozen value stays run after run, until a person decides
    build(conn)
    assert q(conn, "SELECT sunroof FROM kb.commercial_variant") == [(True,)]
    assert decide_now(conn, case, "aprobar") == "approved"
    build(conn)
    assert q(conn, "SELECT sunroof FROM kb.commercial_variant") == [(False,)]
    # a provisional variant just follows its listings
    conn.execute("UPDATE kb.commercial_variant SET status = 'provisional' WHERE id = %s", (vid,))
    conn.execute("DELETE FROM kb.spec_evidence WHERE source_kind = 'manual'")
    build(conn)
    assert q(conn, "SELECT sunroof FROM kb.commercial_variant") == [(False,)]


def test_build_is_stable_and_applies_decisions(conn, tmp_path):
    recs = [creta(f"a{i}", 2017, 1.6, drivetrain="FWD") for i in range(4)]
    recs += [creta(f"b{i}", 2021, 1.5, drivetrain="FWD") for i in range(4)]
    built(conn, tmp_path, recs)
    ids = q(conn, "SELECT id FROM kb.powertrain ORDER BY id")
    built(conn, tmp_path, recs)
    assert q(conn, "SELECT id FROM kb.powertrain ORDER BY id") == ids             # same ids on re-run
    conn.execute("UPDATE kb.review_item SET status = 'approved', decided_by = 't', decided_at = now() "
                 "WHERE issue = 'generation_split'")
    s = build(conn)
    gens = q(conn, "SELECT name, year_from, year_to, listings FROM kb.generation ORDER BY id")
    assert gens == [("Creta (SUV)", 2017, 2020, 4), ("Creta (SUV) (2021+)", 2021, None, 4)]
    assert s["review_pending"].get("generation_split") is None


def test_build_manual_evidence_wins_and_segment_trigger(conn, tmp_path):
    built(conn, tmp_path, [creta(f"a{i}", 2017, 1.6, drivetrain="FWD", horsepower_hp=121) for i in range(5)])
    pid = q(conn, "SELECT id FROM kb.powertrain")[0][0]
    conn.execute("INSERT INTO kb.spec_evidence (entity_type, entity_id, field, source_kind, value, status) "
                 "VALUES ('powertrain', %s, 'horsepower_hp', 'manual', '123', 'accepted')", (pid,))
    build(conn)
    assert q(conn, "SELECT horsepower_hp FROM kb.powertrain") == [(123,)]
    gid = q(conn, "SELECT id FROM kb.generation")[0][0]
    conn.execute("UPDATE kb.generation SET segment_code = 'B' WHERE id = %s", (gid,))
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE kb.generation SET segment_code = 'PickupMidsize' WHERE id = %s", (gid,))
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE kb.generation SET segment_code = 'Scooter' WHERE id = %s", (gid,))


def test_clean_keeps_unknown_make_case_open_on_rerun(conn, tmp_path):
    recs = [rec(listing_id="u1", make="Zorgmobil", model="Z1", trim=None)]
    cleaned(conn, tmp_path, recs)
    s = cleaned(conn, tmp_path, recs)                       # the make now has an alias
    assert s["review_pending"].get("unknown_make") == 1
    assert q(conn, "SELECT status FROM kb.review_item WHERE issue = 'unknown_make'") == [("pending",)]


# --- kb review export / import --------------------------------------------------------------
from vehicle_scraper.kb.review import export_review, import_review  # noqa: E402
from vehicle_scraper.xlsx import Sheet, read_sheet, write_workbook  # noqa: E402


def fill(path, decisions: dict):
    """Write decisions into an exported review file, like a reviewer in Excel.
    decisions: case id -> (decision, corrected value, class)."""
    rows = read_sheet(path, "Casos")
    header, body = rows[0], rows[1:]
    i = {h: n for n, h in enumerate(header)}
    for r in body:
        r += [None] * (len(header) - len(r))
        if r[i["id"]] in decisions:
            d, v, c = decisions[r[i["id"]]]
            r[i["decisión"]], r[i["valor corregido"]], r[i["clase"]] = d, v, c
    write_workbook(path, [Sheet("Casos", header, body)])


def case_id(conn, issue, **where):
    extra = "".join(f" AND {k} = %s" for k in where)
    return q(conn, f"SELECT id FROM kb.review_item WHERE issue = %s{extra}", issue, *where.values())[0][0]


def test_review_round_trip(conn, tmp_path):
    recs = [creta(f"a{i}", 2017, 1.6, drivetrain="FWD") for i in range(4)]
    recs += [creta(f"b{i}", 2021, 1.5, drivetrain="FWD") for i in range(4)]
    recs += [rec(listing_id="z1", make="Chana", model="Benni", trim=None),
             rec(listing_id="z2", make="Zorgmobil", model="Z1", trim=None),
             rec(listing_id="w1", make="Kia", model="Picanto Ion", trim="LX"),
             rec(listing_id="k1", make="Toyota", model="Hilux", trim="2.8 4x4 Aut", drivetrain="2WD")]
    recs += [rec(listing_id=f"p{i}", make="Kia", model="Picanto", trim="LX") for i in range(5)]
    recs += [rec(listing_id=f"c{i}", make="Changan", model="Benni", trim=None) for i in range(5)]
    built(conn, tmp_path, recs)
    out = tmp_path / "review.xlsx"
    s = export_review(conn, out)
    assert s["cases"] == q(conn, "SELECT count(*) FROM kb.review_item WHERE status = 'pending'")[0][0]
    assert read_sheet(out, "Instrucciones")[0][0] == "tipo"

    chana = case_id(conn, "unknown_make", entity_key=str(q(conn, "SELECT id FROM kb.make WHERE name='Chana'")[0][0]))
    zorg = case_id(conn, "unknown_make", entity_key=str(q(conn, "SELECT id FROM kb.make WHERE name='Zorgmobil'")[0][0]))
    ion = case_id(conn, "weak_model", entity_key=str(q(conn, "SELECT id FROM kb.model WHERE name='Picanto Ion'")[0][0]))
    hilux = case_id(conn, "field_conflict", entity_key="carroya:k1")
    split = case_id(conn, "generation_split")
    fill(out, {chana: ("corregir", "Changan", None),          # Chana = Changan
               zorg: ("aprobar", None, None),                 # missing class -> error, stays pending
               ion: ("corregir", "Picanto", None),            # merge into the existing model
               hilux: ("aprobar", None, None),                # the name's 4WD wins
               split: ("corregir", 2020, None)})              # cut a year earlier than proposed
    r = import_review(conn, out, reviewer="Ana")
    assert r["decided"] == {"corrected": 3, "approved": 1} and len(r["errors"]) == 1
    assert "clase" in r["errors"][0]["error"]
    assert q(conn, "SELECT status FROM kb.review_item WHERE id = %s", zorg) == [("pending",)]

    # Effects, after the automatic clean + build:
    assert q(conn, "SELECT k.name FROM kb.clean_listing l JOIN kb.make k ON k.id = l.make_id "
                   "WHERE listing_id = 'z1'") == [("Changan",)]
    assert q(conn, "SELECT m.name FROM kb.clean_listing l JOIN kb.model m ON m.id = l.model_id "
                   "WHERE listing_id = 'w1'") == [("Picanto",)]
    assert q(conn, "SELECT drivetrain_code, provenance->>'drivetrain' FROM kb.clean_listing "
                   "WHERE listing_id = 'k1'") == [("4WD", "manual")]
    assert q(conn, "SELECT year_from, year_to FROM kb.generation WHERE name LIKE 'Creta%%' ORDER BY id") == [
        (2017, 2019), (2020, None)]
    assert q(conn, "SELECT decided_by FROM kb.review_item WHERE id = %s", chana) == [("Ana",)]

    # Importing the same file again changes nothing: decided cases are never overwritten.
    again = import_review(conn, out, reviewer="Otro", rebuild=False)
    assert again["decided"].get("already_decided") == 4 and "clean" not in again
    assert q(conn, "SELECT decided_by FROM kb.review_item WHERE id = %s", chana) == [("Ana",)]


def test_review_make_class_and_value_validation(conn, tmp_path):
    recs = [rec(listing_id=f"m{i}", make="Kenbo", model="Rider", trim=None, vehicle_type="Motorcycle")
            for i in range(5)]
    recs += [rec(listing_id="e1", make="Toyota", model="Corolla", trim="1.8 Hybrid", fuel_type="Gasoline")]
    recs += [rec(listing_id=f"c{i}", make="Toyota", model="Corolla", trim="XEi") for i in range(5)]
    built(conn, tmp_path, recs)
    out = tmp_path / "r.xlsx"
    export_review(conn, out, issues=["unknown_make", "field_conflict"])
    kenbo = case_id(conn, "unknown_make")
    fuel = case_id(conn, "field_conflict", field="fuel_type")
    fill(out, {kenbo: ("aprobar", None, "moto"), fuel: ("corregir", "Volador", None)})
    r = import_review(conn, out, reviewer="Ana")
    assert r["decided"] == {"approved": 1} and "catálogo" in r["errors"][0]["error"]
    assert q(conn, "SELECT status, default_class FROM kb.make WHERE name = 'Kenbo'") == [("accepted", "motorcycle")]
    fill(out, {fuel: ("corregir", "híbrido", None)})                 # Spanish catalog name works
    import_review(conn, out, reviewer="Ana")
    assert q(conn, "SELECT fuel_type_code FROM kb.clean_listing WHERE listing_id = 'e1'") == [("Hybrid",)]


def test_build_publishes_headlights_brakes_and_charger(conn, tmp_path):
    recs = [creta(f"a{i}", 2024, 1.5, drivetrain="FWD", headlight_type="LED", brake_front="Disc",
                  brake_rear="Drum", wireless_charger=True) for i in range(5)]
    built(conn, tmp_path, recs)
    assert q(conn, "SELECT headlight_type_code, brake_front_code, brake_rear_code, wireless_charger "
                   "FROM kb.commercial_variant WHERE listings > 0") == [("LED", "Disc", "Drum", True)]
    assert q(conn, "SELECT specs->>'headlight_type', specs->>'wireless_charger' FROM kb.clean_listing "
                   "WHERE listing_id = 'a0'") == [("LED", "true")]


# --- kb worker (portal inbox) -----------------------------------------------------------------
import json  # noqa: E402
import re  # noqa: E402

from vehicle_scraper.kb.worker import drain, run_worker  # noqa: E402

ROLE_SQL = Path(__file__).resolve().parents[1] / "docs" / "sql" / "portal_role.sql"


def users(conn, **roles):
    for email, role in roles.items():
        conn.execute("INSERT INTO kb.app_user (email, role) VALUES (%s, %s) ON CONFLICT (email) DO UPDATE "
                     "SET role = EXCLUDED.role", (email.replace("_", ".") + "@x.co", role))


def request(conn, kind, payload, by):
    return q(conn, "INSERT INTO kb.web_action (kind, payload, requested_by) VALUES (%s, %s, %s) RETURNING id",
             kind, json.dumps(payload), by)[0][0]


def action(conn, action_id):
    return q(conn, "SELECT status, error, result FROM kb.web_action WHERE id = %s", action_id)[0]


def test_worker_roles_and_decisions(conn, tmp_path):
    recs = [creta(f"a{i}", 2017, 1.6, drivetrain="FWD") for i in range(4)]
    recs += [creta(f"b{i}", 2021, 1.5, drivetrain="FWD") for i in range(4)]
    built(conn, tmp_path, recs)
    users(conn, ana="revisor", eva="editor", leo="lector")
    split = case_id(conn, "generation_split")
    a1 = request(conn, "decide_case", {"case_id": split, "decision": "corregir", "corrected_value": 2020},
                 "leo@x.co")                                                       # lector: refused
    a2 = request(conn, "decide_case", {"case_id": split, "decision": "corregir", "corrected_value": "dos mil"},
                 "ana@x.co")                                                       # invalid year
    a3 = request(conn, "decide_case", {"case_id": split, "decision": "corregir", "corrected_value": 2020},
                 "ana@x.co")
    a4 = request(conn, "decide_case", {"case_id": split, "decision": "aprobar"}, "ana@x.co")   # already decided
    a5 = request(conn, "recalculate", {}, "ana@x.co")                              # revisor can't recalculate
    a6 = request(conn, "recalculate", {}, "nadie@x.co")
    done = drain(conn)
    assert [d["status"] for d in done] == ["failed", "failed", "applied", "failed", "failed", "failed"]
    assert "lector" in action(conn, a1)[1] and "año" in action(conn, a2)[1]
    assert action(conn, a3)[0] == "applied" and "ya estaba decidido" in action(conn, a4)[1]
    assert "editor" in action(conn, a5)[1] and "no tiene acceso" in action(conn, a6)[1]
    assert q(conn, "SELECT decided_by FROM kb.review_item WHERE id = %s", split) == [("ana@x.co",)]
    # Nothing moves until an editor recalculates.
    assert q(conn, "SELECT count(*) FROM kb.generation") == [(1,)]
    a7 = request(conn, "recalculate", {}, "eva@x.co")
    drain(conn)
    status, error, result = action(conn, a7)
    assert status == "applied" and result["build"]["assigned"] == 8
    assert q(conn, "SELECT year_from, year_to FROM kb.generation ORDER BY id") == [(2017, 2019), (2020, None)]


def test_worker_capture_template(conn, tmp_path):
    import base64
    from vehicle_scraper.kb.specs import GENERATIONS, POWERTRAINS
    from vehicle_scraper.xlsx import Sheet, read_sheet, write_workbook
    built(conn, tmp_path, [creta(f"a{i}", 2017, 1.6, drivetrain="FWD") for i in range(5)])
    users(conn, ana="revisor", leo="lector")
    a1 = request(conn, "export_specs", {"limit": 500}, "leo@x.co")                     # lector: refused
    a2 = request(conn, "export_specs", {"country": "Colombia", "limit": 500}, "ana@x.co")
    a3 = request(conn, "export_specs", {"make": "Hyundai", "country": "co", "limit": 500}, "ana@x.co")
    drain(conn)
    assert "revisor" in action(conn, a1)[1] and "país" in action(conn, a2)[1]
    status, _, result = action(conn, a3)
    assert status == "applied" and (result["generations"], result["powertrains"]) == (1, 1)
    assert result["file_name"] == "plantilla-captura-Hyundai-CO.xlsx"
    template = tmp_path / "t.xlsx"
    template.write_bytes(base64.b64decode(result["file_b64"]))
    gens, pts = read_sheet(template, GENERATIONS), read_sheet(template, POWERTRAINS)
    gens[1] += [None] * (len(gens[0]) - len(gens[1]))
    gens[1][gens[0].index("largo mm")] = 4300
    gens[1][gens[0].index("fuente")] = "Ficha Hyundai"
    filled = tmp_path / "f.xlsx"
    write_workbook(filled, [Sheet(GENERATIONS, gens[0], gens[1:]), Sheet(POWERTRAINS, pts[0], pts[1:])])

    def upload(path, name="f.xlsx"):
        return request(conn, "import_specs", {"file_name": name, "file_b64": base64.b64encode(path.read_bytes()).decode()},
                       "ana@x.co")
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"not a zip")
    a4, a5 = upload(filled), upload(bad, "bad.xlsx")
    drain(conn)
    status, _, result = action(conn, a4)
    assert status == "applied" and result["saved"] == {"generation_values": 1, "generation_rows": 1}
    assert result["errors"] == [] and "recalcular" in result["note"]
    assert action(conn, a5)[:2] == ("failed", "no es un archivo .xlsx válido")
    # saved as the uploader's external evidence; published on the next recalculation, not before
    assert q(conn, "SELECT detail->>'captured_by', detail->>'file' FROM kb.spec_evidence WHERE source_kind = 'external'") \
        == [("ana@x.co", "f.xlsx")]
    assert q(conn, "SELECT length_mm FROM kb.generation") == [(None,)]
    build(conn)
    assert q(conn, "SELECT length_mm FROM kb.generation") == [(4300,)]


def test_worker_edits(conn, tmp_path):
    built(conn, tmp_path, [creta(f"a{i}", 2017, 1.6, drivetrain="FWD", horsepower_hp=121) for i in range(5)])
    users(conn, eva="editor")
    gid = q(conn, "SELECT id FROM kb.generation")[0][0]
    pid = q(conn, "SELECT id FROM kb.powertrain")[0][0]
    vid = q(conn, "SELECT id FROM kb.commercial_variant")[0][0]
    ids = [
        request(conn, "set_value", {"entity_type": "powertrain", "entity_id": pid, "field": "horsepower_hp",
                                    "value": "123"}, "eva@x.co"),
        request(conn, "set_value", {"entity_type": "generation", "entity_id": gid, "field": "length_mm",
                                    "value": "4300"}, "eva@x.co"),
        request(conn, "set_value", {"entity_type": "generation", "entity_id": gid, "field": "segment_code",
                                    "value": "Scooter"}, "eva@x.co"),               # trigger: wrong class
        request(conn, "set_value", {"entity_type": "generation", "entity_id": gid, "field": "segment_code",
                                    "value": "Segmento B (pequeño)"}, "eva@x.co"),  # by its Spanish name
        request(conn, "set_value", {"entity_type": "variant", "entity_id": vid, "field": "headlight_type_code",
                                    "value": "led"}, "eva@x.co"),
        request(conn, "set_value", {"entity_type": "variant", "entity_id": vid, "field": "listings",
                                    "value": "9"}, "eva@x.co"),                      # not editable
        request(conn, "add_evolution_note", {"variant_id": vid, "field": "wireless_charger", "value": "sí",
                                             "year_from": 2026}, "eva@x.co"),
        request(conn, "catalog_upsert", {"table": "segment", "code": "Crossover", "name_es": "Crossover",
                                         "name_en": "Crossover", "vehicle_class_code": "car"}, "eva@x.co"),
        request(conn, "catalog_upsert", {"table": "fuel_type", "code": "Hydrogen", "name_es": "Hidrógeno",
                                         "name_en": "Hydrogen"}, "eva@x.co"),        # tied to the scraper
        request(conn, "user_upsert", {"email": "Ana@X.co", "role": "revisor"}, "eva@x.co"),
        request(conn, "user_upsert", {"email": "eva@x.co", "role": "lector"}, "eva@x.co"),   # self-demotion
    ]
    drain(conn)
    got = [action(conn, i)[0] for i in ids]
    assert got == ["applied", "applied", "failed", "applied", "applied", "failed", "applied", "applied", "failed",
                   "applied", "failed"]
    assert "Scooter" in action(conn, ids[2])[1]
    assert q(conn, "SELECT horsepower_hp FROM kb.powertrain") == [(123,)]
    assert q(conn, "SELECT length_mm, segment_code FROM kb.generation") == [(4300, "B")]
    build(conn)                                   # manual evidence survives a rebuild
    assert q(conn, "SELECT horsepower_hp FROM kb.powertrain") == [(123,)]
    assert q(conn, "SELECT headlight_type_code FROM kb.commercial_variant") == [("LED",)]
    assert q(conn, "SELECT field, value, year_from FROM kb.evolution_note") == [("wireless_charger", True, 2026)]
    assert q(conn, "SELECT role FROM kb.app_user WHERE email = 'ana@x.co'") == [("revisor",)]


def test_portal_role_can_only_read_and_request(conn):
    conn.execute("DROP ROLE IF EXISTS omnibase_portal_test")
    conn.execute("CREATE ROLE omnibase_portal_test LOGIN PASSWORD 'pt'")
    db = q(conn, "SELECT current_database()")[0][0]
    sql = ROLE_SQL.read_text(encoding="utf-8").replace("omnibase_portal", "omnibase_portal_test") \
        .replace("DATABASE omnibase ", f"DATABASE {db} ")
    body = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    for stmt in (s.strip() for s in body.split(";")):
        if stmt:
            conn.execute(stmt)
    portal_url = re.sub(r"//[^@]+@", "//omnibase_portal_test:pt@", URL)
    try:
        with psycopg.connect(portal_url, autocommit=True) as pc:
            assert pc.execute("SELECT count(*) FROM kb.fuel_type").fetchone()[0] == 6
            pc.execute("SELECT count(*) FROM staging.raw_listing")
            pc.execute("INSERT INTO kb.web_action (kind, payload, requested_by) VALUES ('recalculate', '{}', 'a@x.co')")
            for forbidden in ["UPDATE kb.web_action SET status = 'applied'",
                              "INSERT INTO kb.web_action (kind, requested_by, status) VALUES ('recalculate', 'a@x.co', 'applied')",
                              "INSERT INTO kb.app_user (email, role) VALUES ('me@x.co', 'editor')",
                              "DELETE FROM kb.review_item"]:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    pc.execute(forbidden)
    finally:
        conn.execute("REASSIGN OWNED BY omnibase_portal_test TO CURRENT_USER")
        conn.execute("DROP OWNED BY omnibase_portal_test")
        conn.execute("DROP ROLE omnibase_portal_test")


def test_worker_listens_and_marks_stale_runs(conn):
    users(conn, eva="editor")
    conn.execute("INSERT INTO kb.web_action (kind, requested_by) VALUES ('recalculate', 'eva@x.co')")
    conn.execute("UPDATE kb.web_action SET status = 'running'")
    with psycopg.connect(URL, autocommit=True) as wc:
        assert run_worker(wc, once=True) == []
    assert q(conn, "SELECT status, error FROM kb.web_action") == [("failed", "el worker se detuvo mientras corría")]


def test_first_editor_migration(conn, monkeypatch):
    cfg = alembic_config(URL)
    # The fixture ran the migrations without the variable: nobody was created.
    assert q(conn, "SELECT count(*) FROM kb.app_user") == [(0,)]
    command.downgrade(cfg, "0007_portal")
    monkeypatch.setenv("KB_FIRST_EDITOR_EMAIL", "  Primera.Editora@Empresa.com ")
    monkeypatch.setenv("KB_FIRST_EDITOR_NAME", "Primera Editora")
    command.upgrade(cfg, "head")
    assert q(conn, "SELECT email, name, role, active FROM kb.app_user") == [
        ("primera.editora@empresa.com", "Primera Editora", "editor", True)]
    # Running it again never changes an existing user.
    conn.execute("UPDATE kb.app_user SET name = 'Cambiado'")
    command.downgrade(cfg, "0007_portal")            # still marked as created by the migration: removed
    assert q(conn, "SELECT count(*) FROM kb.app_user") == [(0,)]
    command.upgrade(cfg, "head")
    conn.execute("UPDATE kb.app_user SET updated_by = 'otra@empresa.com'")    # edited from the portal
    command.downgrade(cfg, "0007_portal")
    assert q(conn, "SELECT count(*) FROM kb.app_user") == [(1,)]               # kept
    monkeypatch.setenv("KB_FIRST_EDITOR_EMAIL", "primera.editora@empresa.com")
    conn.execute("UPDATE kb.app_user SET role = 'lector'")
    command.upgrade(cfg, "head")
    assert q(conn, "SELECT role FROM kb.app_user") == [("lector",)]            # existing: left as it is


def final_row(conn, listing_id):
    rows = q(conn, "SELECT horsepower_hp, sunroof, leather_seats, length_mm, wireless_charger, headlight_type, "
                   "price, currency, mileage_km, make, model, generation_name, variant_id IS NOT NULL, "
                   "unassigned_reason FROM kb.final_listing WHERE listing_id = %s", listing_id)
    return rows[0] if rows else None


def test_final_listing_inherits_the_levels(conn, tmp_path):
    recs = [creta(f"a{i}", 2017, 1.6, drivetrain="FWD", horsepower_hp=121, sunroof=True) for i in range(4)]
    recs += [creta("a4", 2017, 1.6, drivetrain="FWD", horsepower_hp=130, sunroof=False, leather_seats=True,
                   price=50_000_000, currency="COP", mileage_km=40_000)]
    recs += [creta(f"n{i}", 2018, 1.6, drivetrain="FWD", horsepower_hp=121) for i in range(2)]
    recs += [creta(f"b{i}", 2017, 2.0, drivetrain="FWD") for i in range(3)]
    recs += [creta("x1", 2017, None, drivetrain="FWD", horsepower_hp=150)]  # 1.6 or 2.0: unassigned
    recs += [creta("old", 1980, 1.6, drivetrain="FWD")]                     # out of scope: excluded
    recs += [creta("ny", None, 1.6, drivetrain="FWD")]                      # no year: excluded too
    built(conn, tmp_path, recs)
    gid = q(conn, "SELECT id FROM kb.generation")[0][0]
    vid = q(conn, "SELECT v.id FROM kb.commercial_variant v JOIN kb.powertrain p ON p.id = v.powertrain_id "
                  "WHERE p.engine_displacement_l = 1.6")[0][0]
    conn.execute("INSERT INTO kb.spec_evidence (entity_type, entity_id, field, source_kind, value, status) "
                 "VALUES ('generation', %s, 'length_mm', 'manual', '4300', 'accepted')", (gid,))
    for field, value, year in [("wireless_charger", "true", 2018), ("headlight_type_code", '"Halogen"', 2015),
                               ("headlight_type_code", '"LED"', 2018)]:
        conn.execute("INSERT INTO kb.evolution_note (variant_id, field, value, year_from, source) "
                     "VALUES (%s, %s, %s, %s, 'manual')", (vid, field, value, year))
    s = build(conn)
    in_scope = q(conn, "SELECT count(*) FROM kb.clean_listing WHERE excluded_reason IS NULL")[0][0]
    assert s["final_listings"]["rows"] == in_scope == 11 and final_row(conn, "old") is None and final_row(conn, "ny") is None
    # The base wins (hp 121 and sunroof published from the majority); the listing fills gaps
    # (leather seats: one listing isn't enough to publish), and always gives price and mileage.
    assert final_row(conn, "a4") == (121, True, True, 4300, None, "Halogen", 50_000_000, "COP", 40_000,
                                     "Hyundai", "Creta", "Creta (SUV)", True, None)
    # Evolution notes from their year on; the latest one not after the listing's year wins.
    assert final_row(conn, "n0")[:6] == (121, True, None, 4300, True, "LED")
    # Unassigned: what it inherits (the generation) plus its own values, and why.
    assert final_row(conn, "x1") == (150, None, None, 4300, None, None, None, None, None, "Hyundai", "Creta",
                                     "Creta (SUV)", False, "ambiguous_powertrain")
    # kb clean empties it (like listing_level); the next build fills it again.
    clean(conn)
    assert q(conn, "SELECT count(*) FROM kb.final_listing") == [(0,)]
    assert build(conn)["final_listings"]["rows"] == 11


def identity(conn, variant_id):
    rows = q(conn, "SELECT make, model, trim, trim_unknown, country_code, listings, horsepower_hp, sunroof, "
                   "length_mm, torque_nm, engine_displacement_l, sources, evolution_notes, variant_status "
                   "FROM kb.vehicle_identity WHERE variant_id = %s", variant_id)
    return rows[0] if rows else None


def test_vehicle_identity_consolidates_the_levels(conn, tmp_path):
    recs = [creta(f"a{i}", 2017 + i % 2, 1.6, drivetrain="FWD", horsepower_hp=121, sunroof=True) for i in range(4)]
    recs += [creta(f"b{i}", 2017, 2.0, drivetrain="FWD", trim="Limited", leather_seats=i == 0 or None)
             for i in range(3)]
    recs += [creta(f"u{i}", 2017, 1.6, drivetrain="FWD", trim=None) for i in range(2)]   # trim unknown
    built(conn, tmp_path, recs)
    gid = q(conn, "SELECT id FROM kb.generation")[0][0]
    a, pid = q(conn, "SELECT v.id, v.powertrain_id FROM kb.commercial_variant v JOIN kb.powertrain p "
                     "ON p.id = v.powertrain_id WHERE p.engine_displacement_l = 1.6 AND NOT v.trim_unknown")[0]
    unknown = q(conn, "SELECT id FROM kb.commercial_variant WHERE trim_unknown")[0][0]
    limited = q(conn, "SELECT id FROM kb.commercial_variant WHERE trim_name = 'Limited'")[0][0]
    for etype, eid, field, kind, value in [("generation", gid, "length_mm", "manual", "4300"),
                                           ("powertrain", pid, "torque_nm", "external", "151")]:
        conn.execute("INSERT INTO kb.spec_evidence (entity_type, entity_id, field, source_kind, value, status) "
                     "VALUES (%s, %s, %s, %s, %s, 'accepted')", (etype, eid, field, kind, value))
    conn.execute("INSERT INTO kb.evolution_note (variant_id, field, value, year_from, source, note) "
                 "VALUES (%s, 'headlight_type_code', '\"LED\"', 2018, 'manual', 'facelift')", (a,))
    # a provisional variant without listings (they moved elsewhere) gets no sheet
    empty = q(conn, "INSERT INTO kb.commercial_variant (generation_id, powertrain_id, country_code, trim_name, "
                    "trim_key) VALUES (%s, %s, 'CO', 'Vieja', 'vieja') RETURNING id", gid, pid)[0][0]
    s = build(conn)
    assert s["vehicle_identities"]["rows"] == 3
    row = identity(conn, a)
    make, model, trim, trim_unknown, country, listings, hp, sunroof, length, torque, disp, sources, notes, st = row
    assert (make, model, trim, trim_unknown, country, listings, st) == ("Hyundai", "Creta", "Advance", False, "CO", 4,
                                                                         "provisional")
    # Only the base's values, with where each came from (manual > external > listings).
    assert (hp, sunroof, length, torque, float(disp)) == (121, True, 4300, 151, 1.6)
    assert {k: sources[k] for k in ("horsepower_hp", "sunroof", "length_mm", "torque_nm")} == {
        "horsepower_hp": "listings", "sunroof": "listings", "length_mm": "manual", "torque_nm": "external"}
    assert "engine_displacement_l" not in sources                       # the powertrain's key, not evidence
    assert notes == [{"field": "headlight_type", "value": "LED", "year_from": 2018, "note": "facelift",
                      "source": "manual"}]
    # No listing fills a gap: one listing's leather seats aren't published, so only its final record has them.
    assert q(conn, "SELECT leather_seats FROM kb.vehicle_identity WHERE variant_id = %s", limited) == [(None,)]
    assert q(conn, "SELECT leather_seats FROM kb.final_listing WHERE listing_id = 'b0'") == [(True,)]
    assert identity(conn, unknown)[2:4] == (None, True)
    assert identity(conn, empty) is None
    # verified without listings: kept; rejected (variant or its powertrain): left out
    conn.execute("UPDATE kb.commercial_variant SET status = 'verified' WHERE id = %s", (empty,))
    conn.execute("UPDATE kb.commercial_variant SET status = 'rejected' WHERE id = %s", (unknown,))
    conn.execute("UPDATE kb.powertrain SET status = 'rejected' WHERE id = (SELECT powertrain_id FROM "
                 "kb.commercial_variant WHERE id = %s)", (limited,))
    assert build(conn)["vehicle_identities"]["rows"] == 2
    assert identity(conn, empty)[5] == 0 and identity(conn, empty)[-1] == "verified"
    assert identity(conn, unknown) is None and identity(conn, limited) is None
    # kb clean doesn't touch it (it comes from the levels)
    clean(conn)
    assert q(conn, "SELECT count(*) FROM kb.vehicle_identity") == [(2,)]
