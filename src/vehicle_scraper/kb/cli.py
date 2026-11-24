"""``vehicle_scraper kb ...``: knowledge base commands.

    python -m vehicle_scraper kb migrate                 # alembic upgrade head
    python -m vehicle_scraper kb migrate base --downgrade
    python -m vehicle_scraper kb import --sqlite data/vehicles.sqlite
    python -m vehicle_scraper kb status

The database URL comes from ``--database-url`` (before the subcommand) or
``$OMNIBASE_DATABASE_URL``. Nothing here creates or drops the database itself.
psycopg/Alembic are imported only when a kb command runs, so the scraper works without them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def add_parser(sub) -> None:
    kb = sub.add_parser("kb", help="knowledge base (PostgreSQL omnibase)")
    kb.add_argument("--database-url", default=None,
                    help="PostgreSQL URL (default: $OMNIBASE_DATABASE_URL)")
    ksub = kb.add_subparsers(dest="kb_cmd", required=True)

    m = ksub.add_parser("migrate", help="apply the Alembic migrations (default: upgrade to head)")
    m.add_argument("revision", nargs="?", default=None, help="target revision (default: head)")
    m.add_argument("--downgrade", action="store_true",
                   help="downgrade to REVISION instead ('base' drops the kb and staging schemas)")

    i = ksub.add_parser("import", help="copy vehicles.sqlite into staging.raw_listing")
    i.add_argument("--sqlite", type=Path, default=Path("data/vehicles.sqlite"))
    i.add_argument("--force", action="store_true", help="re-read a file already imported")

    ksub.add_parser("clean", help="clean the imported listings into kb.clean_listing (makes, models, trims, "
                                  "fields) and open review cases")

    ksub.add_parser("build", help="build generations, powertrains and commercial variants from the cleaned "
                                  "listings (run after clean)")

    ksub.add_parser("status", help="catalogs, sites, imported and cleaned listings, levels")


def alembic_config(url: str):
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["url"] = url
    return cfg


def cmd_migrate(url: str, args) -> int:
    from alembic import command
    cfg = alembic_config(url)
    if args.downgrade:
        if not args.revision:
            print("--downgrade needs a target revision (e.g. 'base' or '-1')", file=sys.stderr)
            return 2
        command.downgrade(cfg, args.revision)
    else:
        command.upgrade(cfg, args.revision or "head")
    command.current(cfg)
    return 0


def cmd_import(url: str, args) -> int:
    from .db import connect
    from .importer import import_sqlite
    with connect(url) as conn:
        s = import_sqlite(conn, args.sqlite, force=args.force)
    if s["status"] == "already_imported":
        print(f"{s['file']} was already imported (batch {s['batch_id']}); nothing to do. "
              "Use --force to read it again.")
        return 0
    print(f"Imported {s['file']} as batch {s['batch_id']}: {s['rows_read']} rows read, "
          f"{s['new_listings']} new listings, {s['new_versions']} new versions, {s['unchanged']} unchanged.")
    if s["skipped"]:
        print("Not imported (site not registered in kb.source_site): "
              + ", ".join(f"{site}={n}" for site, n in s["skipped"].items()))
    return 0


def print_clean_summary(s: dict) -> None:
    def kv(d: dict) -> str:
        return ", ".join(f"{k}={v}" for k, v in d.items()) or "none"
    print(f"Cleaned {s['listings']} listings: {s['in_scope']} in scope, "
          f"{s['listings'] - s['in_scope']} excluded ({kv(s['excluded'])}).")
    print(f"  in scope by model status: {kv(s['in_scope_by_model_status'])}")
    print(f"  makes: {kv(s['makes'])}")
    print(f"  models with listings: {kv(s['models'])}")
    print(f"  fields filled from model/trim names: {kv(s['filled_from_names'])}")
    print(f"  structured field vs name conflicts: {kv(s['conflicts'])}")
    print(f"  review cases pending: {kv(s['review_pending'])}")


def cmd_clean(url: str, args) -> int:
    from .clean import clean
    from .db import connect
    with connect(url) as conn:
        summary = clean(conn)
    print_clean_summary(summary)
    return 0


def print_build_summary(s: dict) -> None:
    def kv(d: dict) -> str:
        return ", ".join(f"{k}={v}" for k, v in d.items()) or "none"
    print(f"Built levels for {s['listings']} in-scope listings: {s['assigned']} reach a commercial variant, "
          f"{s['listings'] - s['assigned']} don't ({kv(s['unassigned'])}).")
    print(f"  generations with listings: {kv(s['generations'])}")
    print(f"  generations by number of powertrains: {kv(s['powertrains'])}")
    print(f"  commercial variants: {kv(s['variants'])}; by country: {kv(s['variants_by_country'])}")
    print(f"  published values (level.source): {kv(s['published_values'])}")
    print(f"  review cases pending: {kv(s['review_pending'])}")


def cmd_build(url: str, args) -> int:
    from .build import build
    from .db import connect
    with connect(url) as conn:
        summary = build(conn)
    print_build_summary(summary)
    return 0


def cmd_status(url: str, args) -> int:
    from .db import connect
    with connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('kb.source_site') IS NOT NULL")
        if not cur.fetchone()[0]:
            print("The knowledge base schema is not there yet: run `kb migrate`.")
            return 1
        print("Catalogs:")
        counts = []
        for t in ("country", "vehicle_class", "fuel_type", "transmission_type", "drivetrain", "body_style",
                  "segment", "headlight_type", "brake_type"):
            cur.execute(f"SELECT count(*) FROM kb.{t}")
            counts.append(f"{t}={cur.fetchone()[0]}")
        print("  " + "  ".join(counts))
        print("Source sites (current listings / all versions):")
        cur.execute("""
SELECT s.code, s.country_code, s.ai_allowed, s.training_allowed,
       count(r.*) FILTER (WHERE r.valid_to IS NULL), count(r.*)
FROM kb.source_site s LEFT JOIN staging.raw_listing r ON r.source_site = s.code
GROUP BY s.code, s.country_code, s.ai_allowed, s.training_allowed ORDER BY s.code""")
        for code, country, ai, train, cur_n, all_n in cur.fetchall():
            print(f"  {code:<10} {country}  ai={'yes' if ai else 'no ':<3} training={'yes' if train else 'no ':<3} "
                  f"{cur_n:>7} / {all_n}")
        cur.execute("SELECT id, imported_at, rows_read, new_listings, new_versions, unchanged, skipped "
                    "FROM staging.import_batch ORDER BY id DESC LIMIT 5")
        batches = cur.fetchall()
        print("Last imports:" if batches else "No imports yet.")
        for bid, at, read, new, ver, same, skipped in batches:
            extra = f" skipped={skipped}" if skipped else ""
            print(f"  #{bid} {at:%Y-%m-%d %H:%M} read={read} new={new} versions={ver} unchanged={same}{extra}")
        cur.execute("SELECT to_regclass('kb.clean_run') IS NOT NULL")
        if cur.fetchone()[0]:
            cur.execute("SELECT id, started_at, summary FROM kb.clean_run ORDER BY id DESC LIMIT 1")
            last = cur.fetchone()
            if last:
                print(f"Last clean: #{last[0]} {last[1]:%Y-%m-%d %H:%M}")
                print_clean_summary(last[2])
            else:
                print("Not cleaned yet: run `kb clean`.")
        cur.execute("SELECT to_regclass('kb.build_run') IS NOT NULL")
        if cur.fetchone()[0]:
            cur.execute("SELECT id, started_at, summary FROM kb.build_run ORDER BY id DESC LIMIT 1")
            last = cur.fetchone()
            if last:
                print(f"Last build: #{last[0]} {last[1]:%Y-%m-%d %H:%M}")
                print_build_summary(last[2])
            else:
                print("Levels not built yet: run `kb build`.")
    return 0


def run(args: argparse.Namespace) -> int:
    from .db import MissingDatabaseUrl, database_url
    try:
        url = database_url(args.database_url)
    except MissingDatabaseUrl as e:
        print(e, file=sys.stderr)
        return 2
    return {"migrate": cmd_migrate, "import": cmd_import, "clean": cmd_clean, "build": cmd_build,
            "status": cmd_status}[args.kb_cmd](url, args)
