"""Database and worker for the portal's end-to-end tests (src/portal/e2e, `pnpm test:e2e`).

Recreates a small database in the throwaway test container, migrates it, seeds a few listings,
users with each role and the portal's least-privilege role, then runs the real `kb worker` on it
until Playwright stops it. Playwright waits for the READY line below on stdout.

    docker run -d --name omnibase-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=omnibase_test \
        -p 55441:5432 postgres:16-alpine
    python tests/e2e_portal.py               # setup + worker (what Playwright runs)
    python tests/e2e_portal.py --setup-only  # setup, then exit (to look at the data)

OMNIBASE_E2E_ADMIN_URL (default below) is a superuser connection to that container; the
database OMNIBASE_E2E_DB is dropped and created again on every run. Never point it at omnibase.
Not collected by pytest (its name doesn't start with test_).
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Before anything reads .env: migration 0008 must never pick the developer's own address.
os.environ["KB_FIRST_EDITOR_EMAIL"] = ""
os.environ["KB_FIRST_EDITOR_NAME"] = ""

import psycopg  # noqa: E402
from alembic import command  # noqa: E402

from vehicle_scraper.kb.build import build  # noqa: E402
from vehicle_scraper.kb.clean import clean  # noqa: E402
from vehicle_scraper.kb.cli import alembic_config  # noqa: E402
from vehicle_scraper.kb.importer import import_sqlite  # noqa: E402
from vehicle_scraper.kb.worker import run_worker  # noqa: E402
from vehicle_scraper.models import VehicleRecord  # noqa: E402
from vehicle_scraper.storage import Storage  # noqa: E402

ADMIN_URL = os.getenv("OMNIBASE_E2E_ADMIN_URL", "postgresql://postgres:test@localhost:55441/postgres")
DB = os.getenv("OMNIBASE_E2E_DB", "omnibase_e2e")
PORTAL_ROLE, PORTAL_PASSWORD = "omnibase_portal_e2e", "e2e"
SOURCES_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sources" / "kia_sportage.json"
ROLE_SQL = ROOT / "docs" / "sql" / "portal_role.sql"
READY = "e2e worker ready"

# Same addresses as src/portal/e2e/fixtures.ts (.test is a reserved domain: nobody real).
USERS = {"lector@e2e.test": "lector", "revisor@e2e.test": "revisor", "editor@e2e.test": "editor"}

log = logging.getLogger("e2e_portal")


def urls() -> tuple[str, str]:
    """(owner URL, portal-role URL) of the e2e database; refuses anything but a throwaway one."""
    if re.search(r":(5435|5436)/", ADMIN_URL) or DB in {"omnibase", "carknowledge", "postgres"}:
        sys.exit(f"refusing to run against {ADMIN_URL} / {DB}: only the throwaway test container")
    owner = re.sub(r"/[^/?]*(\?|$)", f"/{DB}\\1", ADMIN_URL, count=1)
    portal = re.sub(r"//[^@/]+@", f"//{PORTAL_ROLE}:{PORTAL_PASSWORD}@", owner, count=1)
    return owner, portal


def car(listing_id: str, make: str, model: str, year: int, disp: float, **kw) -> VehicleRecord:
    base = dict(source_site="carroya", source_url=f"https://example.test/{listing_id}", listing_id=listing_id,
                make=make, model=model, trim="Advance", model_year=year, engine_displacement_l=disp,
                fuel_type="Gasoline", transmission_type="Automatic", body_style="SUV", drivetrain="FWD")
    return VehicleRecord(**(base | kw))


def listings() -> list[VehicleRecord]:
    """Two models whose engine changes between years (each gets a proposed generation split)
    and one model with a single listing (a weak_model case)."""
    recs = [car(f"creta-a{i}", "Hyundai", "Creta", 2017, 1.6, horsepower_hp=121) for i in range(4)]
    recs += [car(f"creta-b{i}", "Hyundai", "Creta", 2021, 1.5) for i in range(4)]
    recs += [car(f"sportage-a{i}", "Kia", "Sportage", 2016, 2.0) for i in range(4)]
    recs += [car(f"sportage-b{i}", "Kia", "Sportage", 2022, 1.6) for i in range(4)]
    recs += [car("zoe-1", "Renault", "Zoe", 2020, 1.0, body_style="Hatchback")]
    return recs


def recreate_database() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{DB}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{DB}"')
        if not c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (PORTAL_ROLE,)).fetchone():
            c.execute(f"CREATE ROLE {PORTAL_ROLE} LOGIN PASSWORD '{PORTAL_PASSWORD}'")


def grant_portal_role(conn) -> None:
    """docs/sql/portal_role.sql as written, for the e2e role and database."""
    sql = ROLE_SQL.read_text(encoding="utf-8").replace("omnibase_portal", PORTAL_ROLE) \
        .replace("DATABASE omnibase ", f'DATABASE "{DB}" ')
    body = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    for stmt in (s.strip() for s in body.split(";")):
        if stmt:
            conn.execute(stmt)


def setup() -> str:
    owner, portal = urls()
    recreate_database()
    command.upgrade(alembic_config(owner), "head")
    with tempfile.TemporaryDirectory() as tmp:
        sqlite = Path(tmp) / "e2e.sqlite"
        store = Storage(sqlite)
        for r in listings():
            store.save(r)
        store.close()
        with psycopg.connect(owner, autocommit=True) as conn:
            import_sqlite(conn, sqlite, force=True)
            clean(conn)
            build(conn)
            for email, role in USERS.items():
                conn.execute("INSERT INTO kb.app_user (email, name, role) VALUES (%s, %s, %s)",
                             (email, role.capitalize(), role))
            # the seed's cars are Colombian: let vPIC apply everywhere so the generation page offers it
            conn.execute("UPDATE kb.external_source SET countries = '{}' WHERE code = 'vpic_canada'")
            grant_portal_role(conn)
    log.info("e2e database %s ready; the portal connects as %s", DB, PORTAL_ROLE)
    return owner


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--setup-only", action="store_true", help="prepare the database, then exit")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    owner = setup()
    if args.setup_only:
        return 0
    # external sources answer from saved responses (a 2016/2019 Kia Sportage), never the network
    os.environ["KB_SOURCES_FIXTURES"] = str(SOURCES_FIXTURE)
    with psycopg.connect(owner, autocommit=True) as conn:
        print(READY, flush=True)
        run_worker(conn, poll=2.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
