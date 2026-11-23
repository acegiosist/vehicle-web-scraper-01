"""Database + worker for the review website's Playwright tests (src/web/e2e).

Not a pytest module: Playwright starts it as a web server (src/web/playwright.config.ts).
It (re)creates the throwaway database ``kb_e2e_review`` on the server of KB_TEST_DATABASE_URL,
migrates it, loads a handful of listings that open known review cases, and then runs the real
`kb review worker` on it until Playwright stops it.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402

from vehicle_scraper.kb import ai_batch, consensus, identity, importer  # noqa: E402
from vehicle_scraper.kb.db import connect  # noqa: E402
from vehicle_scraper.kb import settings, worker  # noqa: E402
from vehicle_scraper.kb.worker import WorkerSettings, run_worker  # noqa: E402
from vehicle_scraper.models import VehicleRecord  # noqa: E402
from vehicle_scraper.storage import Storage  # noqa: E402

DB_NAME = "kb_e2e_review"


def rec(lid, make, model, trim=None, **f) -> VehicleRecord:
    return VehicleRecord(source_site="carroya", source_url=f"https://example.test/carroya/{lid}", listing_id=str(lid),
                         make=make, model=model, trim=trim, model_year=2020, **f)


def records() -> list[VehicleRecord]:
    base = dict(engine_displacement_l=1.8, fuel_type="Gasoline", transmission_type="Manual", drivetrain="FWD")
    # 6 listings (5+ makes the model "known"); seats 3 vs 3 -> listings_disagree
    rows = [rec(f"tr{i}", "Chevrolet", "Tracker", "1.8 FWD LS Mecanica", **base,
                seats=5 if i <= 3 else 7, horsepower_hp=138) for i in range(1, 7)]
    rows += [rec("z1", "Zzzmotors", "Thing", "150 Bus")]       # unknown make; its model can be split
    return rows


def fake_ai_answer(conn) -> None:
    """A collected identity batch (no network, no cost) that proposes the make Zzzmotors: its case
    shows up as an AI proposal on the site. Its model is left to the rules."""
    reqs = ai_batch._with_params(ai_batch.identity_requests(conn), "identity", "low")
    req = next(r for r in reqs if r["meta"].get("make_unresolved"))
    run = ai_batch.record_submission(conn, [req], "identity", "low", {"cost_usd_est": 0}, "msgbatch_e2e")
    answer = {"make": {"canonical_name": "Zzzmotors", "is_vehicle_make": True, "status": "ok", "confidence": 0.7,
                       "reason": "Marca de prueba"}, "models": [], "trims": []}
    msg = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(answer)}], "usage": {}}
    ai_batch.store_and_apply(conn, conn.execute("SELECT * FROM kb.ai_run WHERE id = %s", (run,)).fetchone(),
                             [{"custom_id": req["custom_id"], "type": "succeeded", "message": msg}])


def fake_anthropic() -> None:
    """No network from the e2e worker: the spent run is still processing, the other one finished
    (4 answers, 1 error), and collecting it stores no answers (its requests aren't in kb.ai_decision)."""
    from datetime import datetime, timedelta, timezone

    def retrieve(batch_id):
        done = batch_id == "msgbatch_e2e_done"
        return {"processing_status": "ended" if done else "in_progress",
                "ended_at": datetime.now(timezone.utc) - timedelta(minutes=3) if done else None,
                "request_counts": {"succeeded": 4, "errored": 1, "expired": 0, "canceled": 0, "processing": 0}
                if done else {"succeeded": 0, "errored": 0, "expired": 0, "canceled": 0, "processing": 1}}

    def collect(conn, run_id, wait=False):
        run = conn.execute("SELECT * FROM kb.ai_run WHERE id = %s", (run_id,)).fetchone()
        return ai_batch.store_and_apply(conn, run, []) or {"succeeded": 0}

    worker._retrieve_fn = retrieve
    ai_batch.collect = collect


def main() -> int:
    admin = os.environ.get("KB_TEST_DATABASE_URL")
    if not admin:
        raise SystemExit("Set KB_TEST_DATABASE_URL (a Postgres where this user may CREATE DATABASE)")
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{DB_NAME}"')
    url = admin.rsplit("/", 1)[0] + "/" + DB_NAME
    subprocess.run([sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "-x", f"url={url}",
                    "upgrade", "head"], check=True, cwd=ROOT, capture_output=True)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "e2e.sqlite"
        storage = Storage(path)
        for r in records():
            storage.save(r)
        storage.close()
        with connect(url) as conn:
            importer.import_sqlite(conn, path)
            identity.normalize(conn)
            consensus.consolidate(conn)
            fake_ai_answer(conn)
            conn.execute("""INSERT INTO kb.ai_run (kind, batch_id, model, effort, status, submitted_at, est_cost_usd)
                            VALUES ('specs', 'msgbatch_e2e_spent', 'claude-opus-5-5', 'medium', 'submitted',
                                    now(), 2)""")               # US$2 spent today: over the US$1 budget
            # a batch that already finished at Anthropic: the worker's first check marks it 'ended'
            conn.execute("""INSERT INTO kb.ai_run (kind, batch_id, model, effort, status, request_count, submitted_at,
                                                   est_cost_usd)
                            VALUES ('identity', 'msgbatch_e2e_done', 'claude-opus-5-5', 'low', 'submitted', 5,
                                    now() - interval '20 minutes', 0)""")
    fake_anthropic()
    # never send a real batch from the tests: ignore the repo's .env (KB_ALLOW_WEB_AI_SUBMIT stays
    # off) and give the worker a US$1 daily budget that the seed has already exceeded
    settings.ENV_FILE = ""
    os.environ.pop(worker.AI_SUBMIT_ENV, None)
    os.environ["KB_AI_BUDGET_USD"], os.environ["KB_AI_BUDGET_PERIOD"] = "1", "daily"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run_worker(url, WorkerSettings(propagate_idle=0, poll=2))   # logs "listening on ..." when ready


if __name__ == "__main__":
    raise SystemExit(main())
