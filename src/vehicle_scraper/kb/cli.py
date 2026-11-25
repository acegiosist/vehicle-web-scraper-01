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

    rv = ksub.add_parser("review", help="decide review cases in an Excel file")
    rsub = rv.add_subparsers(dest="review_cmd", required=True)
    re_ = rsub.add_parser("export", help="write the pending cases to a .xlsx")
    re_.add_argument("--out", type=Path, default=Path("data/review.xlsx"))
    re_.add_argument("--issue", action="append", default=None, help="only this kind of case (repeatable)")
    re_.add_argument("--limit", type=int, default=None, help="at most this many cases")
    ri = rsub.add_parser("import", help="read the decisions back, then re-run clean and build")
    ri.add_argument("path", type=Path)
    ri.add_argument("--reviewer", required=True, help="who decided (recorded on every case)")
    ri.add_argument("--no-rebuild", action="store_true", help="only save the decisions (no clean + build)")

    sp = ksub.add_parser("specs", help="capture what listings don't carry (dimensions, torque...) from a source")
    ssub = sp.add_subparsers(dest="specs_cmd", required=True)
    se = ssub.add_parser("export", help="write generations and powertrains missing values to a .xlsx")
    se.add_argument("--out", type=Path, default=Path("data/specs.xlsx"))
    se.add_argument("--make", default=None, help="only this make")
    se.add_argument("--country", default=None, help="only generations with listings from this country (CO, US...)")
    se.add_argument("--limit", type=int, default=500, help="at most this many rows per sheet")
    si = ssub.add_parser("import", help="save the captured values as external evidence, then re-run build")
    si.add_argument("path", type=Path)
    si.add_argument("--by", required=True, help="who captured the values (recorded with each one)")
    si.add_argument("--no-rebuild", action="store_true", help="only save the values (no build)")

    w = ksub.add_parser("worker", help="apply the portal's queued actions (kb.web_action)")
    w.add_argument("--once", action="store_true", help="apply what is queued, then exit")
    w.add_argument("--poll", type=float, default=30.0, help="seconds between queue checks without a NOTIFY")

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


def cmd_review(url: str, args) -> int:
    from .db import connect
    from .review import export_review, import_review
    with connect(url) as conn:
        if args.review_cmd == "export":
            try:
                s = export_review(conn, args.out, issues=args.issue, limit=args.limit)
            except PermissionError:
                print(f"Can't write {args.out}: close it in Excel (or pass --out) and retry.", file=sys.stderr)
                return 1
            print(f"Wrote {s['cases']} pending cases to {s['file']}: "
                  + (", ".join(f"{k}={v}" for k, v in s["by_issue"].items()) or "none"))
            return 0
        s = import_review(conn, args.path, args.reviewer, rebuild=not args.no_rebuild)
    decided = s["decided"]
    print(f"Read {s['file']}: approved={decided.get('approved', 0)} rejected={decided.get('rejected', 0)} "
          f"corrected={decided.get('corrected', 0)} already decided={decided.get('already_decided', 0)} "
          f"errors={len(s['errors'])}")
    for e in s["errors"]:
        print(f"  row {e['row']}" + (f" (case {e['id']})" if "id" in e else "") + f": {e['error']}")
    if s["errors"]:
        print("  Those cases stay pending: fix the rows and import the file again.")
    if "clean" in s:
        print_clean_summary(s["clean"])
        print_build_summary(s["build"])
    elif not args.no_rebuild:
        print("Nothing was decided, so clean and build didn't run.")
    return 0


def cmd_specs(url: str, args) -> int:
    from .db import connect
    from .specs import export_specs, import_specs
    with connect(url) as conn:
        if args.specs_cmd == "export":
            try:
                s = export_specs(conn, args.out, make=args.make, country=args.country, limit=args.limit)
            except PermissionError:
                print(f"Can't write {args.out}: close it in Excel (or pass --out) and retry.", file=sys.stderr)
                return 1
            print(f"Wrote {s['generations']} generations and {s['powertrains']} powertrains missing values "
                  f"to {s['file']}")
            return 0
        s = import_specs(conn, args.path, args.by, rebuild=not args.no_rebuild)
    saved = s["saved"]
    print(f"Read {s['file']}: generation values={saved.get('generation_values', 0)} "
          f"powertrain values={saved.get('powertrain_values', 0)} "
          f"cycle cases opened={saved.get('cycle_opened', 0)} (already decided={saved.get('cycle_already_decided', 0)}) "
          f"errors={len(s['errors'])}")
    for e in s["errors"]:
        print(f"  {e['sheet']} row {e['row']}" + (f" (id {e['id']})" if "id" in e else "") + f": {e['error']}")
    if s["errors"]:
        print("  Those rows weren't saved: fix them and import the file again.")
    if "build" in s:
        print_build_summary(s["build"])
    elif not args.no_rebuild:
        print("No value changed, so build didn't run.")
    return 0


def cmd_worker(url: str, args) -> int:
    import psycopg
    from .db import libpq_url
    from .worker import run_worker
    with psycopg.connect(libpq_url(url), autocommit=True) as conn:
        done = run_worker(conn, once=args.once, poll=args.poll)
    print(f"Applied {sum(d['status'] == 'applied' for d in done)} actions, "
          f"{sum(d['status'] == 'failed' for d in done)} failed.")
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
            "review": cmd_review, "specs": cmd_specs, "worker": cmd_worker,
            "status": cmd_status}[args.kb_cmd](url, args)
