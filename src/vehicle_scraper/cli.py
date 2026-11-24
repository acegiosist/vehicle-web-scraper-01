"""Command-line interface.

    python -m vehicle_scraper sites
    python -m vehicle_scraper run --site carroya --site cofino --limit 50
    python -m vehicle_scraper run --all --limit 20 --refresh
    python -m vehicle_scraper run --site cars24 --limit 50 --max-age 5
    python -m vehicle_scraper export --format csv
    python -m vehicle_scraper export --format xlsx
    python -m vehicle_scraper coverage
    python -m vehicle_scraper new-site https://www.example-autos.com/usados --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
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


AGE_UNITS = {"d": 1, "w": 7, "m": 30, "y": 365}


def parse_max_age(text: str) -> timedelta:
    """'5' / '5y' -> 5 years, '6m' -> 6 months (30 d), '2w', '30d'. Used by ``run --max-age``."""
    m = re.fullmatch(r"\s*(\d+)\s*([dwmy]?)\s*", str(text).lower())
    if not m:
        raise argparse.ArgumentTypeError(f"invalid age {text!r}: use e.g. 5 (years), 5y, 6m, 2w, 30d")
    return timedelta(days=int(m.group(1)) * AGE_UNITS[m.group(2) or "y"])


def run_site(name: str, store: Storage, limit: int | None, refresh: bool,
             listed_since: datetime | None = None) -> dict:
    """Scrape one site. With ``listed_since``, only listings posted at or after it are saved:
    listings known (from discovery) to be older are skipped without fetching, and listings with
    no listing date at all are not saved. ``limit`` then counts only listings that pass."""
    cls = REGISTRY[name]
    stats = {"site": name, "saved": 0, "skipped": 0, "errors": 0, "too_old": 0, "no_date": 0,
             "status": "ok"}
    try:
        scraper = cls(settings)
    except RuntimeError as e:                     # e.g. missing API token
        log.error("[%s] %s", name, e)
        return stats | {"status": f"not configured: {e}"}
    scraper.listed_since = listed_since           # lets newest-first discovery stop early
    scraper.run_limit = limit
    raw_dir = settings.data_dir / "raw" / name
    passed = 0                                    # listings that got past the age filter
    try:
        # Without an age filter discovery itself stops at `limit`; with one, we keep discovering
        # until `limit` listings have passed it.
        for listing in scraper.discover(limit=limit if listed_since is None else None):
            if listed_since is not None:
                if limit is not None and passed >= limit:
                    break
                if listing.listed_at is not None and listing.listed_at < listed_since:
                    stats["too_old"] += 1         # rejected before fetching the page
                    continue
            if not refresh and store.has(name, listing.listing_id):
                stats["skipped"] += 1
                passed += 1
                continue
            try:
                rec = scraper.parse(listing)      # may refine listing.listed_at from the page
                if listed_since is not None:
                    if listing.listed_at is None:
                        stats["no_date"] += 1
                        continue
                    if listing.listed_at < listed_since:
                        stats["too_old"] += 1
                        continue
                passed += 1
                if listing.listed_at is not None:
                    rec.listed_at = listing.listed_at     # from discovery, or refined by parse()
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
                passed += 1
                log.warning("[%s] could not parse %s: %s", name, listing.url, e)
            except Exception as e:  # noqa: BLE001 - one bad listing must not stop the run
                stats["errors"] += 1
                passed += 1
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
    r.add_argument("--max-age", type=parse_max_age, default=None, metavar="AGE",
                   help="only save listings posted within AGE: 5 (years), 5y, 6m, 2w, 30d. "
                        "Uses the site's listing date (API field or sitemap <lastmod>); "
                        "listings without one are not saved")
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

    from .kb.cli import add_parser as add_kb_parser
    add_kb_parser(sub)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    load_yaml_sites(args.sites_file)

    if args.cmd == "kb":                      # PostgreSQL knowledge base (optional extra `kb`)
        from .kb.cli import run as run_kb
        return run_kb(args)

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
            since = None if args.max_age is None else datetime.now(timezone.utc) - args.max_age
            if since is not None:
                print(f"Only saving listings posted on or after {since:%Y-%m-%d %H:%M} UTC")
            results = [run_site(n, store, args.limit, args.refresh, since) for n in names]
            print("\nRun summary:")
            for s in results:
                age = f"too_old={s['too_old']:<5} no_date={s['no_date']:<4} " if since is not None else ""
                print(f"  {s['site']:<12} saved={s['saved']:<5} skipped={s['skipped']:<5} {age}"
                      f"errors={s['errors']:<4} {s['status']}")
                if since is not None and s["no_date"] and not (s["saved"] or s["too_old"]):
                    print(f"  {'':<12} ^ this site gave no listing dates, so --max-age saved nothing")
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
