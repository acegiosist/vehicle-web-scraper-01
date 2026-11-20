"""End-to-end knowledge-base tests against a real PostgreSQL.

Skipped unless KB_TEST_DATABASE_URL points to a server where the user may CREATE DATABASE,
e.g. a throwaway container:
    docker run -d --name vehicle-kb-test -e POSTGRES_USER=kb -e POSTGRES_PASSWORD=kbtest -p 55432:5432 postgres:16-alpine
    KB_TEST_DATABASE_URL=postgresql://kb:kbtest@localhost:55432/kb python -m pytest tests/test_kb_pg.py
Each test gets its own fresh database, migrated with Alembic and dropped afterwards.
"""
import csv
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("alembic")

from vehicle_scraper.kb import ai_batch, consensus, identity, importer, review
from vehicle_scraper.kb.db import connect, jsonb
from vehicle_scraper.models import VehicleRecord
from vehicle_scraper.storage import Storage

ADMIN_URL = os.getenv("KB_TEST_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="KB_TEST_DATABASE_URL not set")


def _alembic(url, *args):
    subprocess.run([sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "-x", f"url={url}", *args],
                   check=True, cwd=ROOT, capture_output=True)


@pytest.fixture
def db():
    name = f"kb_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    try:
        _alembic(url, "upgrade", "head")
        yield url
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def rec(site, lid, make, model, year=2020, trim=None, **f):
    return VehicleRecord(source_site=site, source_url=f"https://example.test/{site}/{lid}", listing_id=str(lid),
                         make=make, model=model, trim=trim, model_year=year, **f)


def sqlite_with(path: Path, records) -> Path:
    s = Storage(path)
    for r in records:
        s.save(r)
    s.close()
    return path


def pipeline(url, sqlite: Path):
    with connect(url) as conn:
        importer.import_sqlite(conn, sqlite)
        identity.normalize(conn)
        return consensus.consolidate(conn)


def tracker(n, site="carroya", **f):
    base = dict(engine_displacement_l=1.8, fuel_type="Gasoline", transmission_type="Manual", drivetrain="FWD")
    return rec(site, f"tr{n}", "Chevrolet", "Tracker", 2020, "1.8 FWD LS Mecanica", **{**base, **f})


# ------------------------------------------------------------------------------------------------
def test_migration_roundtrip(db):
    _alembic(db, "downgrade", "base")
    _alembic(db, "upgrade", "head")
    with connect(db) as conn:
        names = {r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'kb'")}
    assert {"make", "model", "trim", "variant", "variant_spec", "variant_market_spec", "spec_evidence",
            "review_item", "listing_standardized"} <= names


def test_import_is_idempotent_and_keeps_history(db, tmp_path):
    a = sqlite_with(tmp_path / "a.sqlite", [tracker(1, horsepower_hp=138)])
    with connect(db) as conn:
        assert importer.import_sqlite(conn, a)["new"] == 1
        assert importer.import_sqlite(conn, a)["skipped"]
    b = sqlite_with(tmp_path / "b.sqlite", [tracker(1, horsepower_hp=140)])          # seller edited the car
    with connect(db) as conn:
        s = importer.import_sqlite(conn, b)
        assert (s["changed"], s["new"]) == (1, 0)
        rows = conn.execute("SELECT version, valid_to IS NULL AS cur, row->>'horsepower_hp' AS hp "
                            "FROM staging.raw_listing ORDER BY version").fetchall()
        assert [(r["version"], r["cur"], r["hp"]) for r in rows] == [(1, False, "138"), (2, True, "140")]
        assert conn.execute("SELECT current_version FROM kb.listing").fetchone()["current_version"] == 2


def test_aliases_never_duplicate_and_unknowns_go_to_review(db, tmp_path):
    rows = [rec("carroya", i, "Toyota", "Rav 4") for i in range(3)]
    rows += [rec("cars24", 10, "TOYOTA", "RAV4"), rec("cofino", 11, "Toyota", "RAV4 HYBRID 4X4")]
    rows += [rec("carroya", 20, "Zzzmotors", "Thing")]
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", rows))
    with connect(db) as conn:
        models = conn.execute("SELECT m.name, m.status FROM kb.model m JOIN kb.make k ON k.id = m.make_id "
                              "WHERE k.slug = 'toyota'").fetchall()
        assert [(m["name"], m["status"]) for m in models] == [("Rav 4", "accepted")]
        assert conn.execute("SELECT count(*) AS n FROM kb.review_item WHERE issue = 'unresolved_make'").fetchone()["n"] == 1
    pipeline(db, sqlite_with(tmp_path / "b.sqlite", rows + [rec("carroya", 30, "Toyota", "RAV-4")]))
    with connect(db) as conn:
        assert conn.execute("SELECT count(*) AS n FROM kb.model m JOIN kb.make k ON k.id = m.make_id "
                            "WHERE k.slug = 'toyota'").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM kb.review_item").fetchone()["n"] == 2    # no repeats


def test_consensus_rules_crosschecks_and_idempotency(db, tmp_path):
    rows = [tracker(1, horsepower_hp=138, seats=5, sunroof=True)] + [tracker(i) for i in range(2, 6)]
    rows += [rec("carroya", f"g{i}", "BMW", "G 310", 2021, "R", vehicle_type="Motorcycle",
                 engine_displacement_l=1.0) for i in range(5)]
    rows += [rec("carroya", f"p{i}", "Bajaj", "Pulsar", 2021, "200 NS", vehicle_type="Motorcycle",
                 engine_displacement_l=0.2, horsepower_hp=24) for i in range(5)]
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", rows))
    with connect(db) as conn:
        spec = conn.execute("""SELECT s.horsepower_hp, s.seats FROM kb.variant_spec s JOIN kb.variant v ON v.id = s.variant_id
                               JOIN kb.model m ON m.id = v.model_id WHERE m.name = 'Tracker'""").fetchone()
        assert (spec["horsepower_hp"], spec["seats"]) == (138, 5)                     # one listing is enough
        assert conn.execute("SELECT count(*) AS n FROM kb.variant_market_spec WHERE sunroof").fetchone()["n"] == 0
        g310 = conn.execute("""SELECT v.status FROM kb.variant v JOIN kb.model m ON m.id = v.model_id
                               WHERE m.name = 'G 310'""").fetchone()
        assert g310["status"] == "pending_review"
        assert conn.execute("SELECT count(*) AS n FROM kb.review_item WHERE issue = 'name_vs_displacement'").fetchone()["n"] == 1
        pulsar = conn.execute("""SELECT v.status, s.horsepower_hp FROM kb.variant v JOIN kb.model m ON m.id = v.model_id
                                 JOIN kb.variant_spec s ON s.variant_id = v.id WHERE m.name = 'Pulsar'""").fetchone()
        assert (pulsar["status"], pulsar["horsepower_hp"]) == ("accepted", 24)
        assert consensus.consolidate(conn).changes == 0                             # idempotent


def test_same_car_on_two_portals_is_one_vote(db, tmp_path):
    import sqlite3
    common = dict(price=50_000_000, currency="COP", mileage_km=40_000, seats=5)
    rows = [tracker(1, **common), tracker(2, **{**common, "mileage_km": 40_100})]
    rows += [tracker(i) for i in range(3, 6)]
    path = sqlite_with(tmp_path / "a.sqlite", rows)
    with sqlite3.connect(path) as c:              # the listing date column of data/vehicles.sqlite
        c.execute("ALTER TABLE vehicles ADD COLUMN listed_at")
        c.execute("UPDATE vehicles SET listed_at = '2026-11-01T00:00:00+00:00' WHERE listing_id IN ('tr1', 'tr2')")
    stats = pipeline(db, path)
    assert stats.clusters == 1
    with connect(db) as conn:
        ev = conn.execute("SELECT source_kind, support_count FROM kb.spec_evidence WHERE field = 'seats'").fetchone()
        assert (ev["source_kind"], ev["support_count"]) == ("listing_single", 1)


def test_human_value_is_never_replaced(db, tmp_path):
    rows = [tracker(i, horsepower_hp=138) for i in range(1, 6)]
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", rows))
    with connect(db) as conn:
        vid = conn.execute("SELECT id FROM kb.variant").fetchone()["id"]
        conn.execute("""INSERT INTO kb.spec_evidence (variant_id, country, field, value, source_kind, confidence,
                        status, origin_key) VALUES (%s, '', 'horsepower_hp', %s, 'manual', 1, 'accepted', 'review:1')""",
                     (vid, jsonb(150)))
        consensus.consolidate(conn)
        assert conn.execute("SELECT horsepower_hp FROM kb.variant_spec").fetchone()["horsepower_hp"] == 150
        assert conn.execute("SELECT count(*) AS n FROM kb.review_item WHERE issue = 'conflicts_with_human'").fetchone()["n"] == 1


def test_ai_flow_without_spending(db, tmp_path):
    rows = [tracker(i) for i in range(1, 6)]
    rows += [rec("carroya", "u1", "Toyota", "Corola")]                                 # weak spelling -> AI
    rows += [rec("cofino", "c1", "Toyota", "Secretcofinomodel")]                       # never sent to the AI
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", rows))
    with connect(db) as conn:
        reqs = ai_batch.identity_requests(conn)
        assert reqs and all("Secretcofinomodel" not in r["user"] for r in reqs)
        assert any("Corola" in r["user"] for r in reqs)

        specs = ai_batch._with_params(ai_batch.specs_requests(conn, min_listings=1), "specs", "medium")
        assert len(specs) == 1
        run = ai_batch.record_submission(conn, specs, "specs", "medium", {"cost_usd_est": 0}, "msgbatch_test")
        vid = int(next(iter(specs[0]["meta"]["variants"])))
        answer = {"variants": [{"id": vid, "suspect_known": [], "values": [
            {"field": "horsepower_hp", "value": "138 hp", "confidence": 0.9},          # critical -> individual
            {"field": "fuel_tank_capacity_l", "value": "53 L", "confidence": 0.9},     # sampled
            {"field": "abs", "value": "true", "confidence": 0.9},
            {"field": "sunroof", "value": "true", "confidence": 0.3}]}]}             # too unsure: dropped
        msg = {"stop_reason": "end_turn", "content": [{"type": "text", "text": __import__("json").dumps(answer)}],
               "usage": {"input_tokens": 100, "output_tokens": 50}}
        stats = ai_batch.store_and_apply(conn, conn.execute("SELECT * FROM kb.ai_run WHERE id = %s", (run,)).fetchone(),
                                         [{"custom_id": "nope", "type": "errored", "message": None},
                                          {"custom_id": specs[0]["custom_id"], "type": "succeeded", "message": msg}])
        assert stats["ai_values"] == 3 and stats["critical_individual"] == 1
        # the same request is never resent
        assert ai_batch._drop_answered(conn, specs)[0] == []

    out = tmp_path / "review.csv"
    with connect(db) as conn:
        review.export_review(conn, out, sample_size=5)
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    for r in rows:
        r["decision"] = "approve"
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    with connect(db) as conn:
        s = review.import_review(conn, out, "tester")
        assert s.get("batch_accepted") == 1
        consensus.consolidate(conn)
        spec = conn.execute("SELECT horsepower_hp, fuel_tank_capacity_l FROM kb.variant_spec").fetchone()
        assert (spec["horsepower_hp"], spec["fuel_tank_capacity_l"]) == (138, 53.0)
        srcs = {r["field"]: (r["source_kind"], r["status"]) for r in conn.execute(
            "SELECT field, source_kind, status FROM kb.spec_evidence WHERE status <> 'rejected'")}
        assert srcs["horsepower_hp"] == ("manual", "accepted")                       # human-approved
        assert srcs["fuel_tank_capacity_l"] == ("ai_knowledge", "accepted_sampled")


def test_merging_models_cascades(db, tmp_path):
    rows = [rec("carroya", f"a{i}", "Toyota", "Prado", 2015, engine_displacement_l=3.0, fuel_type="Diesel")
            for i in range(5)]
    rows += [rec("carroya", f"b{i}", "Toyota", "Land Cruiser Prado", 2015, engine_displacement_l=3.0,
                 fuel_type="Diesel") for i in range(5)]
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", rows))
    with connect(db) as conn:
        ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM kb.model")}
        vars_ = {r["model_id"]: r["id"] for r in conn.execute("SELECT id, model_id FROM kb.variant")}
        for name, hp in (("Prado", 160), ("Land Cruiser Prado", 170)):
            conn.execute("""INSERT INTO kb.spec_evidence (variant_id, country, field, value, source_kind, confidence,
                            status, origin_key) VALUES (%s, '', 'horsepower_hp', %s, 'manual', 1, 'accepted', 'review:9')""",
                         (vars_[ids[name]], jsonb(hp)))
        identity.merge_model(conn, ids["Prado"], ids["Land Cruiser Prado"], "test")
        assert conn.execute("SELECT count(*) AS n FROM kb.variant").fetchone()["n"] == 1
        assert conn.execute("SELECT count(DISTINCT model_id) AS n FROM kb.listing").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM kb.review_item WHERE issue = 'merge_human_conflict'").fetchone()["n"] == 1
        identity.normalize(conn)                                 # old spelling keeps resolving to the survivor
        consensus.consolidate(conn)
        assert conn.execute("SELECT count(DISTINCT model_id) AS n FROM kb.listing").fetchone()["n"] == 1
        assert conn.execute("SELECT horsepower_hp FROM kb.variant_spec").fetchone()["horsepower_hp"] == 170


# --- review website: decision inbox + worker (migration 0002) ------------------------------------
from vehicle_scraper.kb import worker  # noqa: E402
from vehicle_scraper.kb.db import writer_lock  # noqa: E402


def _queue(conn, item_id, decision, corrected=None, reviewer="ana"):
    return conn.execute("""INSERT INTO kb.review_decision (review_item_id, decision, corrected_value, reviewer)
                           VALUES (%s, %s, %s, %s) RETURNING id""", (item_id, decision, corrected, reviewer)).fetchone()["id"]


def _spec_case(conn, field="horsepower_hp"):
    vid = conn.execute("SELECT id FROM kb.variant ORDER BY id LIMIT 1").fetchone()["id"]
    identity.open_review(conn, level=5, entity_type="spec", entity_id=vid, issue="listings_disagree", source="rule",
                         field_=field, current={"top_value": 138, "agreement": 0.5, "support": 2})
    return vid, conn.execute("SELECT id FROM kb.review_item WHERE issue = 'listings_disagree'").fetchone()["id"]


def test_review_queue_view_labels_and_listing_number(db, tmp_path):
    rows = [tracker(i) for i in range(1, 6)] + [rec("carroya", 20, "Zzzmotors", "Thing")]
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", rows))
    with connect(db) as conn:
        _spec_case(conn)
        q = {r["issue"]: r for r in conn.execute("SELECT * FROM kb.review_queue WHERE status = 'pending' AND in_queue")}
        assert q["unresolved_make"]["entity_label"] == "Zzzmotors"
        assert q["listings_disagree"]["entity_label"].startswith("Chevrolet Tracker")
        assert q["listings_disagree"]["make_name"] == "Chevrolet" and q["listings_disagree"]["variant_id"]
        n = conn.execute("SELECT kb.listing_number('carroya', 'tr1') AS n").fetchone()["n"]
        assert n == identity.listing_number("carroya", "tr1")


def test_worker_applies_queued_decisions(db, tmp_path):
    rows = [tracker(i, horsepower_hp=138) for i in range(1, 6)] + [rec("carroya", 20, "Zzzmotors", "Thing")]
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", rows))
    with connect(db) as conn:
        make_case = conn.execute("SELECT id, entity_id FROM kb.review_item WHERE issue = 'unresolved_make'").fetchone()
        vid, spec_case = _spec_case(conn)
        d_make = _queue(conn, make_case["id"], "approved")
        d_bad = _queue(conn, spec_case, "corrected", "mucho")                       # not a number
    with connect(db) as conn:                                                          # double click: refused
        with pytest.raises(psycopg.errors.UniqueViolation):
            _queue(conn, make_case["id"], "rejected")

    with connect(db) as conn:
        writer_lock(conn)
        stats = worker.process_queue(conn)
    assert (stats["applied"], stats["failed"]) == (1, 1)
    with connect(db) as conn:
        d = {r["id"]: r for r in conn.execute("SELECT * FROM kb.review_decision")}
        assert d[d_make]["status"] == "applied" and d[d_make]["processed_at"]
        assert d[d_bad]["status"] == "failed" and "válido" in d[d_bad]["error"]
        assert conn.execute("SELECT status FROM kb.make WHERE id = %s", (make_case["entity_id"],)).fetchone()["status"] == "accepted"
        assert conn.execute("SELECT status FROM kb.review_item WHERE id = %s", (spec_case,)).fetchone()["status"] == "pending"
        d_late = _queue(conn, make_case["id"], "rejected", reviewer="beto")          # case already decided
        d_ok = _queue(conn, spec_case, "corrected", "150 hp")

    assert worker.run_worker(db, worker.WorkerSettings(propagate_idle=1), once=True) == 0   # applies + propagates
    with connect(db) as conn:
        d = {r["id"]: r for r in conn.execute("SELECT * FROM kb.review_decision")}
        assert d[d_late]["status"] == "superseded" and d[d_ok]["status"] == "applied"
        item = conn.execute("SELECT status, reviewer FROM kb.review_item WHERE id = %s", (spec_case,)).fetchone()
        assert (item["status"], item["reviewer"]) == ("corrected", "ana")
        assert conn.execute("SELECT horsepower_hp FROM kb.variant_spec WHERE variant_id = %s",
                            (vid,)).fetchone()["horsepower_hp"] == 150            # propagated by consolidate


def test_decision_insert_notifies_the_worker(db, tmp_path):
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", [rec("carroya", 20, "Zzzmotors", "Thing")]))
    with psycopg.connect(db, autocommit=True) as listener:
        listener.execute(f"LISTEN {worker.CHANNEL}")
        with connect(db) as conn:
            item = conn.execute("SELECT id FROM kb.review_item LIMIT 1").fetchone()["id"]
            did = _queue(conn, item, "approved")
        got = [n.payload for n in listener.notifies(timeout=5, stop_after=1)]
    assert got == [str(did)]


def test_writer_lock_allows_one_writer(db):
    with connect(db) as a, connect(db) as b:
        writer_lock(a)
        assert b.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s)) AS ok",
                         ("vehicle_scraper.kb.writer",)).fetchone()["ok"] is False


def test_csv_import_reports_invalid_corrections(db, tmp_path):
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", [tracker(i, horsepower_hp=138) for i in range(1, 6)]))
    with connect(db) as conn:
        _, case = _spec_case(conn)
    out = tmp_path / "review.csv"
    with connect(db) as conn:
        review.export_review(conn, out)
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert [r["entity"].split()[:2] for r in rows] == [["Chevrolet", "Tracker"]]
    rows[0].update(decision="correct", corrected_value="99999")                       # out of range
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    with connect(db) as conn:
        assert review.import_review(conn, out, "tester")["invalid_value"] == 1
        assert conn.execute("SELECT status FROM kb.review_item WHERE id = %s", (case,)).fetchone()["status"] == "pending"
