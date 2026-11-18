"""Command-line interface.

    python -m vehicle_scraper sites
    python -m vehicle_scraper run --site carroya --site cofino --limit 50
    python -m vehicle_scraper run --all --limit 20 --refresh
    python -m vehicle_scraper export --format csv
    python -m vehicle_scraper export --format xlsx
    python -m vehicle_scraper coverage
    python -m vehicle_scraper new-site https://www.example-autos.com/usados --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .config import settings
from .http import BlockedError, DisallowedError
from .report import write_coverage
from .scaffold import cli_new_site
from .sites import REGISTRY, load_yaml_sites
from .storage import Storage

log = logging.getLogger("vehicle_scraper")
SITES_YAML = next((p for p in (Path("config/sites.yaml"),
                                Path(__file__).resolve().parents[2] / "config" / "sites.yaml") if p.exists()),
                  Path("config/sites.yaml"))


def run_site(name: str, store: Storage, limit: int | None, refresh: bool) -> dict:
    cls = REGISTRY[name]
    stats = {"site": name, "saved": 0, "skipped": 0, "errors": 0, "status": "ok"}
    try:
        scraper = cls(settings)
    except RuntimeError as e:                     # e.g. missing API token
        log.error("[%s] %s", name, e)
        return stats | {"status": f"not configured: {e}"}
    raw_dir = settings.data_dir / "raw" / name
    try:
        for listing in scraper.discover(limit=limit):
            if not refresh and store.has(name, listing.listing_id):
                stats["skipped"] += 1
                continue
            try:
                rec = scraper.parse(listing)
                store.save(rec)
                stats["saved"] += 1
                if settings.save_raw:
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    (raw_dir / f"{listing.listing_id}.json").write_text(rec.model_dump_json(indent=2), encoding="utf-8")
                log.info("[%s] saved %s %s %s %s", name, listing.listing_id, rec.make, rec.model, rec.model_year)
            except (BlockedError, DisallowedError):
                raise
            except (ValidationError, ValueError, KeyError) as e:
                stats["errors"] += 1
                log.warning("[%s] could not parse %s: %s", name, listing.url, e)
            except Exception as e:  # noqa: BLE001 - one bad listing must not stop the run
                stats["errors"] += 1
                log.exception("[%s] error on %s: %s", name, listing.url, e)
    except BlockedError as e:
        stats["status"] = f"blocked: {e}"
        log.error("[%s] stopped — %s. Not bypassing; see README for options.", name, e)
    except DisallowedError as e:
        stats["status"] = f"robots.txt: {e}"
        log.error("[%s] stopped — %s", name, e)
    except Exception as e:  # noqa: BLE001
        stats["status"] = f"failed: {e}"
        log.exception("[%s] discovery failed", name)
    finally:
        scraper.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vehicle_scraper", description="Standardized vehicle scraper")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--sites-file", type=Path, default=SITES_YAML, help="extra sites YAML")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sites", help="list available sites")

    r = sub.add_parser("run", help="scrape one or more sites")
    r.add_argument("--site", action="append", default=[], help="site name (repeatable)")
    r.add_argument("--all", action="store_true", help="run every site")
    r.add_argument("--limit", type=int, default=None, help="max listings per site")
    r.add_argument("--refresh", action="store_true", help="re-scrape listings already stored")
    r.add_argument("--browser", action="store_true", help="render pages with Playwright")

    e = sub.add_parser("export", help="export stored records")
    e.add_argument("--format", choices=["csv", "json", "xlsx"], default="csv")
    e.add_argument("--site", default=None)
    e.add_argument("--out", type=Path, default=None)

    sub.add_parser("coverage", help="print the field-coverage report")

    ns = sub.add_parser("new-site", help="scaffold a scraper module for a new site from a URL")
    ns.add_argument("url", help="a listing/search page, a car's detail page, or the homepage")
    ns.add_argument("--name", default=None, help="site name (default: from the domain)")
    ns.add_argument("--country", default=None, help="ISO country code (default: from the domain)")
    ns.add_argument("--currency", default=None, help="ISO currency code that prices are really in")
    ns.add_argument("--browser", action="store_true", help="render pages with Playwright")
    ns.add_argument("--force", action="store_true", help="overwrite an existing site module")
    ns.add_argument("--dry-run", action="store_true", help="print the generated files, write nothing")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    load_yaml_sites(args.sites_file)

    if args.cmd == "new-site":
        return cli_new_site(args)

    if args.cmd == "sites":
        for name, cls in sorted(REGISTRY.items()):
            print(f"{name:<12} {cls.status:<16} {cls.base_url:<32} {cls.notes}")
        return 0

    store = Storage(settings.db_path)
    try:
        if args.cmd == "run":
            names = sorted(REGISTRY) if args.all else args.site
            unknown = [n for n in names if n not in REGISTRY]
            if not names or unknown:
                p.error(f"choose sites with --site or --all (unknown: {unknown}); available: {sorted(REGISTRY)}")
            if args.browser:
                settings.use_browser = True
            results = [run_site(n, store, args.limit, args.refresh) for n in names]
            print("\nRun summary:")
            for s in results:
                print(f"  {s['site']:<12} saved={s['saved']:<5} skipped={s['skipped']:<5} errors={s['errors']:<4} {s['status']}")
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            n = store.export_csv(settings.data_dir / f"vehicles_{stamp}.csv")
            print(f"\nExported {n} records to {settings.data_dir / f'vehicles_{stamp}.csv'}")
            rows = store.rows()
            if rows:
                print("\nField coverage (% of listings with a value):")
                print(write_coverage(rows, settings.data_dir / "coverage.csv"))
        elif args.cmd == "export":
            out = args.out or settings.data_dir / f"vehicles.{args.format}"
            exporter = {"csv": store.export_csv, "json": store.export_json, "xlsx": store.export_xlsx}[args.format]
            try:
                n = exporter(out, args.site)
            except PermissionError:
                print(f"Can't write {out}: close it in Excel (or pass --out) and retry.", file=sys.stderr)
                return 1
            print(f"Exported {n} records to {out}")
        elif args.cmd == "coverage":
            rows = store.rows()
            print(write_coverage(rows, settings.data_dir / "coverage.csv") if rows else "No data yet.")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
