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
                                 JOIN kb.variant_spec s ON s.variant_id = v.id WHERE m.name = 'Pulsar 200'""").fetchone()  # split_models
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


def _models(conn, make):
    return {r["name"]: r for r in conn.execute(
        "SELECT m.* FROM kb.model m JOIN kb.make k ON k.id = m.make_id WHERE k.name = %s", (make,))}


def test_review_splits_a_family_by_version_number(db, tmp_path):
    # CarroYa: model "LV", the truck's number at the start of the version
    rows = [rec("carroya", "lv1", "Chevrolet", "LV", 2006, "150 Bus"),
            rec("carroya", "lv2", "Chevrolet", "LV", 2019, "452"),
            rec("carroya", "lv3", "Chevrolet", "LV", 2020, "452 4x2"),
            rec("carroya", "lv4", "Chevrolet", "LV", 2018)]                           # no number: stays
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", rows))
    with connect(db) as conn:
        lv = _models(conn, "Chevrolet")["LV"]
        case = conn.execute("SELECT id FROM kb.review_item WHERE issue = 'unresolved_model' AND entity_id = %s",
                            (lv["id"],)).fetchone()["id"]
        assert review.decide_item(conn, case, "corrected", "split:truck", None, "ana") == "invalid_value"
        assert review.decide_item(conn, case, "corrected", "split:heavy", None, "ana") == "corrected"
        identity.normalize(conn)
        consensus.consolidate(conn)
    with connect(db) as conn:
        models = _models(conn, "Chevrolet")
        assert {"LV", "LV 150", "LV 452"} <= set(models)
        for name in ("LV 150", "LV 452"):
            m = models[name]
            assert (m["status"], m["verified_by"], m["vehicle_class"], m["split_from"]) == \
                   ("accepted", "human", "heavy", lv["id"])
        assert models["LV"]["split_by_number"] and models["LV"]["status"] == "unresolved"
        where = {r["listing_id"]: (r["model"], r["trim"]) for r in conn.execute(
            """SELECT l.listing_id, m.name AS model, t.name AS trim FROM kb.listing l
               JOIN kb.model m ON m.id = l.model_id LEFT JOIN kb.trim t ON t.id = l.trim_id""")}
        assert where == {"lv1": ("LV 150", "Bus"), "lv2": ("LV 452", None), "lv3": ("LV 452", None),
                         "lv4": ("LV", None)}
        # the split models reach the knowledge base; the family's raw spelling never aliases them
        assert conn.execute("SELECT count(DISTINCT v.model_id) AS n FROM kb.variant v JOIN kb.listing l "
                            "ON l.variant_id = v.id").fetchone()["n"] == 2
        assert not conn.execute("SELECT 1 FROM kb.model_alias WHERE alias_key = 'lv' AND model_id <> %s",
                                (lv["id"],)).fetchone()
        before = conn.execute("SELECT (SELECT count(*) FROM kb.model) AS m, (SELECT count(*) FROM kb.review_item) AS r").fetchone()
        identity.normalize(conn)                                                        # idempotent
        consensus.consolidate(conn)
        assert conn.execute("SELECT (SELECT count(*) FROM kb.model) AS m, (SELECT count(*) FROM kb.review_item) AS r"
                            ).fetchone() == before


def test_seeded_family_takes_its_variants_and_human_values_along(db, tmp_path):
    import yaml
    seed = yaml.safe_load(identity.SEED_PATH.read_text(encoding="utf-8"))
    assert {"make": "KTM", "model": "Duke"} in seed["split_models"]
    no_split = tmp_path / "makes.yaml"
    no_split.write_text(yaml.safe_dump({"makes": seed["makes"]}), encoding="utf-8")
    moto = dict(vehicle_type="Motorcycle", fuel_type="Gasoline")
    rows = [rec("carroya", f"d{i}", "KTM", "DUKE", 2022, "200 NG", engine_displacement_l=0.2, **moto) for i in range(3)]
    rows += [rec("carroya", f"e{i}", "KTM", "DUKE", 2022, "390", engine_displacement_l=0.373, **moto) for i in range(3)]
    with connect(db) as conn:                          # before the family was curated: one model
        importer.import_sqlite(conn, sqlite_with(tmp_path / "a.sqlite", rows))
        identity.normalize(conn, seed_path=no_split)
        consensus.consolidate(conn)
        duke = _models(conn, "KTM")["Duke"]
        assert duke["status"] == "accepted"
        v200 = conn.execute("SELECT v.id FROM kb.variant v JOIN kb.trim t ON t.id = v.trim_id "
                            "WHERE t.name = '200 NG'").fetchone()["id"]
        conn.execute("""INSERT INTO kb.spec_evidence (variant_id, country, field, value, source_kind, confidence,
                        status, origin_key) VALUES (%s, '', 'horsepower_hp', '25', 'manual', 1, 'accepted', 'review:7')""",
                     (v200,))
    with connect(db) as conn:                          # now makes.yaml lists it
        identity.normalize(conn)
        consensus.consolidate(conn)
    with connect(db) as conn:
        models = _models(conn, "KTM")
        assert models["Duke 200"]["verified_by"] == "seed" and models["Duke 200"]["vehicle_class"] == "motorcycle"
        assert models["Duke 390"]["split_from"] == duke["id"]
        v = conn.execute("""SELECT v.id, m.name AS model, t.name AS trim FROM kb.variant v JOIN kb.model m ON m.id = v.model_id
                            LEFT JOIN kb.trim t ON t.id = v.trim_id WHERE v.id = %s""", (v200,)).fetchone()
        assert (v["model"], v["trim"]) == ("Duke 200", "NG")                         # same variant, re-keyed
        assert conn.execute("SELECT horsepower_hp FROM kb.variant_spec WHERE variant_id = %s",
                            (v200,)).fetchone()["horsepower_hp"] == 25
        assert conn.execute("SELECT count(*) AS n FROM kb.listing WHERE model_id = %s", (duke["id"],)).fetchone()["n"] == 0


# --- review website: decision inbox + worker (migration 0002) ------------------------------------
from vehicle_scraper.kb import settings, worker  # noqa: E402
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


def test_ai_cases_keep_their_origin_when_normalize_runs_again(db, tmp_path):
    import json
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", [rec("carroya", 20, "Zzzmotors", "Thing")]))
    with connect(db) as conn:
        reqs = ai_batch._with_params(ai_batch.identity_requests(conn), "identity", "low")
        req = next(r for r in reqs if r["meta"].get("make_unresolved"))
        model_id = req["meta"]["models"][0]
        run = ai_batch.record_submission(conn, [req], "identity", "low", {"cost_usd_est": 0}, "msgbatch_test")
        answer = {"make": {"canonical_name": "Zzzmotors", "is_vehicle_make": True, "status": "ok", "confidence": 0.9},
                  "models": [{"id": model_id, "status": "ok", "is_real_model": True, "confidence": 0.9}],  # sampled
                  "trims": []}
        msg = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(answer)}], "usage": {}}
        ai_batch.store_and_apply(conn, conn.execute("SELECT * FROM kb.ai_run WHERE id = %s", (run,)).fetchone(),
                                 [{"custom_id": req["custom_id"], "type": "succeeded", "message": msg}])
        identity.normalize(conn)          # what the worker does after a decision: re-opens the same cases
        cases = {r["issue"]: r for r in conn.execute(
            "SELECT issue, source, kind, from_ai, ai_run_id FROM kb.review_queue WHERE status = 'pending'")}
        assert (cases["unresolved_make"]["source"], cases["unresolved_make"]["kind"]) == ("ai", "individual")
        assert (cases["unresolved_model"]["source"], cases["unresolved_model"]["kind"]) == ("ai", "sample")
        assert all(c["from_ai"] and c["ai_run_id"] == run for c in cases.values())
        # cases broken before migration 0004 (source reset to 'rule') get their origin back
        conn.execute("UPDATE kb.review_item SET source = 'rule' WHERE ai_decision_id IS NOT NULL")
    _alembic(db, "downgrade", "0003_web_jobs")
    _alembic(db, "upgrade", "head")
    with connect(db) as conn:
        assert {r["source"] for r in conn.execute(
            "SELECT source FROM kb.review_item WHERE ai_decision_id IS NOT NULL")} == {"ai"}
        assert conn.execute("SELECT count(*) AS n FROM kb.review_queue WHERE NOT from_ai").fetchone()["n"] == 0


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


# --- jobs queued by the review website (migration 0003) -----------------------------------------------
import gzip  # noqa: E402

from vehicle_scraper.kb import ai_batch as _ab  # noqa: E402


def _job(conn, command, params=None, by="ana"):
    return conn.execute("INSERT INTO kb.job (command, params, requested_by) VALUES (%s, %s, %s) RETURNING id",
                        (command, jsonb(params or {}), by)).fetchone()["id"]


def _jobs(url):
    with connect(url) as conn:
        return {r["id"]: r for r in conn.execute("SELECT * FROM kb.job")}


def test_jobs_recalculate_and_export(db, tmp_path):
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", [tracker(i, horsepower_hp=138) for i in range(1, 6)]))
    with connect(db) as conn:
        j_rec = _job(conn, "recalculate")
        j_csv = _job(conn, "export", {"format": "csv"})
        j_bad = _job(conn, "export", {"format": "pdf"})
        j_xlsx = _job(conn, "export", {"format": "xlsx", "with_sources": True})
        with pytest.raises(psycopg.errors.UniqueViolation):          # same job twice while queued
            with conn.transaction():
                _job(conn, "recalculate")
    assert worker.run_worker(db, worker.WorkerSettings(propagate_idle=0), once=True) == 0
    jobs = _jobs(db)
    assert [jobs[j]["status"] for j in (j_rec, j_csv, j_bad, j_xlsx)] == ["done", "done", "failed", "done"]
    assert "consolidate" in jobs[j_rec]["summary"] and jobs[j_rec]["result"]["consolidate"]["variants"] == 1
    assert "csv, xlsx or json" in jobs[j_bad]["error"]
    with connect(db) as conn:
        f = conn.execute("SELECT * FROM kb.job_file WHERE job_id = %s", (j_csv,)).fetchone()
        text = gzip.decompress(f["bytes"]).decode("utf-8-sig")
        assert f["gzipped"] and f["filename"] == "kb_listings.csv" and f["size"] == len(gzip.decompress(f["bytes"]))
        assert text.splitlines()[0].startswith("source_site") and len(text.splitlines()) == 6
        x = conn.execute("SELECT * FROM kb.job_file WHERE job_id = %s", (j_xlsx,)).fetchone()
        assert not x["gzipped"] and bytes(x["bytes"][:2]) == b"PK" and x["filename"] == "kb_listings_sources.xlsx"


def test_cancel_and_interrupted_jobs(db):
    with connect(db) as conn:
        queued, running = _job(conn, "normalize"), _job(conn, "consolidate")
        conn.execute("UPDATE kb.job SET status = 'running' WHERE id = %s", (running,))
        assert conn.execute("SELECT kb.cancel_job(%s) AS ok", (queued,)).fetchone()["ok"] is True
        assert conn.execute("SELECT kb.cancel_job(%s) AS ok", (running,)).fetchone()["ok"] is None
    worker.run_worker(db, worker.WorkerSettings(propagate_idle=0), once=True)
    jobs = _jobs(db)
    assert jobs[queued]["status"] == "canceled"
    assert jobs[running]["status"] == "failed" and "se detuvo" in jobs[running]["error"]


def test_ai_submit_from_the_site_needs_every_check(db, tmp_path, monkeypatch):
    rows = [tracker(i) for i in range(1, 6)] + [rec("carroya", "u1", "Toyota", "Corola")]   # weak model -> AI
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", rows))
    sent = []

    def fake_submit(conn, reqs, kind, effort, est):                  # no network, no cost
        sent.append(len(reqs))
        return _ab.record_submission(conn, reqs, kind, effort, est, f"msgbatch_fake_{len(sent)}")
    monkeypatch.setattr(worker, "_submit_fn", fake_submit)
    env = tmp_path / ".env"                       # the worker re-reads this file on every submission
    env.write_text("KB_ALLOW_WEB_AI_SUBMIT=\n", encoding="utf-8")
    monkeypatch.setattr(settings, "ENV_FILE", str(env))
    monkeypatch.setenv(worker.AI_SUBMIT_ENV, "true")  # the .env value wins over the environment
    for key in ("KB_AI_BUDGET_USD", "KB_AI_BUDGET_PERIOD"):   # loaded from the repo's .env at import
        monkeypatch.delenv(key, raising=False)

    with connect(db) as conn:
        est = _job(conn, "ai_estimate", {"kind": "identity"})
    worker.run_next_job(db)
    e = _jobs(db)[est]
    assert e["status"] == "done" and e["result"]["requests"] >= 1 and len(e["result"]["fingerprint"]) == 64
    cost = e["result"]["estimate"]["cost_usd_est"]

    def submit(confirm, by):
        with connect(db) as conn:
            jid = _job(conn, "ai_submit", {"estimate_job_id": est, "confirm_usd": confirm}, by)
        worker.run_next_job(db)
        return _jobs(db)[jid]

    assert "deshabilitado" in submit(cost, "a")["error"]                       # 1. flag off
    env.write_text("KB_ALLOW_WEB_AI_SUBMIT=true\n", encoding="utf-8")         # switched on, no restart
    assert "menor" in submit(cost - 0.01, "b")["error"]                        # 4. amount below the estimate
    with connect(db) as conn:                                                  # 3. requests changed
        conn.execute("UPDATE kb.job SET result = jsonb_set(result, '{fingerprint}', '\"x\"') WHERE id = %s", (est,))
    assert "changed since the estimate" in submit(cost, "c")["error"]
    with connect(db) as conn:                                                  # 2. estimate too old
        conn.execute("UPDATE kb.job SET finished_at = now() - interval '2 hours' WHERE id = %s", (est,))
    assert "minutos" in submit(cost, "d")["error"]
    assert sent == []

    def fresh_estimate():
        with connect(db) as conn:
            jid = _job(conn, "ai_estimate", {"kind": "identity", "effort": "low"})
        worker.run_next_job(db)
        return jid

    est = fresh_estimate()                                                     # 5. the spending limit
    assert "falta KB_AI_BUDGET_USD" in submit(cost, "e")["error"]              # no limit in .env: never sent
    with connect(db) as conn:      # already spent today (an older run that is still being processed)
        conn.execute("""INSERT INTO kb.ai_run (kind, batch_id, model, effort, status, submitted_at, est_cost_usd)
                        VALUES ('specs', 'msgbatch_old', 'm', 'low', 'submitted', now(), 4.5),
                               ('specs', 'msgbatch_last_month', 'm', 'low', 'applied', now() - interval '40 days', 90)""")
    env.write_text("KB_ALLOW_WEB_AI_SUBMIT=true\nKB_AI_BUDGET_USD=4\n", encoding="utf-8")
    est = fresh_estimate()
    b = _jobs(db)[est]["result"]["budget"]
    assert (b["limit_usd"], b["spent_usd"], b["allows"]) == (4.0, 4.5, False) and "Se superó" in b["message"]
    assert "Se superó el límite de gasto en IA" in submit(cost, "f")["error"]
    assert sent == []
    env.write_text("KB_ALLOW_WEB_AI_SUBMIT=true\nKB_AI_BUDGET_USD=5\nKB_AI_BUDGET_PERIOD=daily\n", encoding="utf-8")
    est = fresh_estimate()                       # last month's US$90 doesn't count today
    assert _jobs(db)[est]["result"]["budget"]["allows"] is (4.5 + cost <= 5)
    ok = submit(cost, "g")
    assert ok["status"] == "done" and ok["result"]["ai_run_id"] and sent == [ok["result"]["requests"]]
    with connect(db) as conn:
        assert conn.execute("SELECT batch_id FROM kb.ai_run ORDER BY id DESC").fetchone()["batch_id"] == "msgbatch_fake_1"


def test_collected_runs_keep_their_real_cost(db, tmp_path):
    import json
    pipeline(db, sqlite_with(tmp_path / "a.sqlite", [rec("carroya", 20, "Zzzmotors", "Thing")]))
    with connect(db) as conn:
        req = ai_batch._with_params(ai_batch.identity_requests(conn), "identity", "low")[0]
        run = ai_batch.record_submission(conn, [req], "identity", "low", {"cost_usd_est": 0.5}, "msgbatch_test")
        msg = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps({"models": []})}],
               "usage": {"input_tokens": 1000, "output_tokens": 2000, "cache_read_input_tokens": 3000,
                         "cache_creation_input_tokens": 4000}}
        ai_batch.store_and_apply(conn, conn.execute("SELECT * FROM kb.ai_run WHERE id = %s", (run,)).fetchone(),
                                 [{"custom_id": req["custom_id"], "type": "succeeded", "message": msg}])
        r = conn.execute("SELECT * FROM kb.ai_run WHERE id = %s", (run,)).fetchone()
        expected = ai_batch.actual_cost(1000, 2000, 3000, 4000)
        assert (r["cache_write_tokens"], float(r["actual_cost_usd"])) == (4000, expected)
        assert expected == round(1000 * 2e-6 + 2000 * 10e-6 + 3000 * 0.1e-6 + 4000 * 2.5e-6, 4)
        from vehicle_scraper.kb.budget import spent_since
        assert spent_since(conn, r["submitted_at"]) == expected                # real cost, not the estimate
    # runs collected before 0005 get their real cost from the tokens they had (no cache writes)
    _alembic(db, "downgrade", "0004_queue_ai_origin")
    _alembic(db, "upgrade", "head")
    with connect(db) as conn:
        r = conn.execute("SELECT * FROM kb.ai_run WHERE id = %s", (run,)).fetchone()
        assert float(r["actual_cost_usd"]) == ai_batch.actual_cost(1000, 2000, 3000, 0)


def test_worker_marks_finished_batches_for_collection(db, tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone
    from types import SimpleNamespace

    import anthropic

    from vehicle_scraper.kb import commands
    from vehicle_scraper.kb.export import status as kb_status

    pipeline(db, sqlite_with(tmp_path / "a.sqlite", [rec("carroya", 20, "Zzzmotors", "Thing")]))
    with connect(db) as conn:
        req = ai_batch._with_params(ai_batch.identity_requests(conn), "identity", "low")[0]
        run = ai_batch.record_submission(conn, [req], "identity", "low", {"cost_usd_est": 0.01}, "msgbatch_check")
    status = {"processing_status": "in_progress", "ended_at": None,
              "request_counts": {"processing": 1, "succeeded": 0, "errored": 0, "expired": 0, "canceled": 0}}
    calls = []

    def fake_retrieve(batch_id):                        # no network
        calls.append(batch_id)
        return status
    monkeypatch.setattr(worker, "_retrieve_fn", fake_retrieve)

    def run_row():
        with connect(db) as conn:
            return conn.execute("SELECT * FROM kb.ai_run WHERE id = %s", (run,)).fetchone()

    assert worker.check_batches(db) == []                                     # still processing
    r = run_row()
    assert r["status"] == "submitted" and r["batch_checked_at"] and r["batch_counts"]["processing"] == 1

    ended = datetime(2026, 11, 23, 14, 7, tzinfo=timezone.utc)
    status.update(processing_status="ended", ended_at=ended,
                  request_counts={"processing": 0, "succeeded": 1, "errored": 0, "expired": 0, "canceled": 0})
    assert worker.check_batches(db) == [run]                                  # finished: ready to collect
    r = run_row()
    assert (r["status"], r["ended_at"], r["batch_counts"]["succeeded"]) == ("ended", ended, 1)
    assert worker.check_batches(db) == [] and calls == ["msgbatch_check"] * 2  # an ended run isn't asked again
    with connect(db) as conn:
        assert f"AI run {run} (identity) finished" in kb_status(conn)            # `kb status` says so too

    # older code only collects submitted runs: a downgrade gives the uncollected ones back
    _alembic(db, "downgrade", "0005_ai_run_cost")
    with connect(db) as conn:
        assert conn.execute("SELECT status FROM kb.ai_run WHERE id = %s", (run,)).fetchone()["status"] == "submitted"
    _alembic(db, "upgrade", "head")
    with connect(db) as conn:
        conn.execute("UPDATE kb.ai_run SET status = 'ended', ended_at = %s WHERE id = %s", (ended, run))

    # an ended run is collected like a submitted one (the default picks it) and keeps its end time
    msg = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps({"models": []})}],
           "usage": {"input_tokens": 10, "output_tokens": 20}}
    result = SimpleNamespace(type="succeeded", message=SimpleNamespace(model_dump=lambda: msg))
    batches = SimpleNamespace(retrieve=lambda batch_id: SimpleNamespace(processing_status="ended"),
                              results=lambda batch_id: [SimpleNamespace(custom_id=req["custom_id"], result=result)])
    monkeypatch.setattr(anthropic, "Anthropic", lambda: SimpleNamespace(messages=SimpleNamespace(batches=batches)))
    with connect(db) as conn:
        assert commands.ai_collect(conn).result == {"succeeded": 1}
    r = run_row()
    assert (r["status"], r["ended_at"], r["input_tokens"]) == ("applied", ended, 10)

    # without an API key nothing is checked (and the worker says so once)
    with connect(db) as conn:
        conn.execute("""INSERT INTO kb.ai_run (kind, batch_id, model, effort, status, submitted_at)
                        VALUES ('specs', 'msgbatch_nokey', 'm', 'low', 'submitted', now())""")
    monkeypatch.setattr(worker, "_retrieve_fn", None)
    monkeypatch.setattr(worker, "_warned_no_key", False)
    monkeypatch.setattr(settings, "ENV_FILE", "")
    monkeypatch.delenv(worker.API_KEY_ENV, raising=False)
    assert worker.check_batches(db) == [] and worker._warned_no_key
    with connect(db) as conn:
        assert conn.execute("SELECT batch_checked_at FROM kb.ai_run WHERE batch_id = 'msgbatch_nokey'"
                            ).fetchone()["batch_checked_at"] is None
