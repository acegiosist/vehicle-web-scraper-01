"""`vehicle-scraper kb ...` subcommands (knowledge base in PostgreSQL)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# Imports of psycopg/anthropic stay inside run(): the scraper CLI must keep working
# without the optional `kb` dependencies installed.


def add_parser(sub) -> None:
    kb = sub.add_parser("kb", help="vehicle knowledge base (PostgreSQL)")
    kb.add_argument("--database-url", default=None, help="postgresql://... (default: $KB_DATABASE_URL)")
    ks = kb.add_subparsers(dest="kb_cmd", required=True)

    m = ks.add_parser("migrate", help="apply migrations (alembic upgrade)")
    m.add_argument("revision", nargs="?", default="head")
    m.add_argument("--downgrade", action="store_true", help="alembic downgrade to REVISION instead")

    i = ks.add_parser("import", help="copy vehicles.sqlite into staging (idempotent, keeps history)")
    i.add_argument("--sqlite", type=Path, default=Path("data/vehicles.sqlite"))

    ks.add_parser("normalize", help="rule-based identity: makes, models, trims, years")

    c = ks.add_parser("consolidate", help="variants, consensus, cross-checks, publish sheets")
    c.add_argument("--min-support", type=int, default=2)
    c.add_argument("--min-agreement", type=float, default=0.7)

    for kind in ("identity", "specs"):
        a = ks.add_parser(f"ai-{kind}", help=f"Claude Message Batches: {kind}")
        g = a.add_mutually_exclusive_group(required=True)
        g.add_argument("--estimate", action="store_true", help="build the requests and estimate the cost (free)")
        g.add_argument("--submit", action="store_true", help="send the batch (costs money: needs --confirm)")
        g.add_argument("--collect", action="store_true", help="fetch finished results and apply them")
        a.add_argument("--confirm", action="store_true", help="really spend money on --submit")
        a.add_argument("--count-tokens", action="store_true",
                       help="exact input tokens via the free count_tokens API (sends the text to Anthropic)")
        a.add_argument("--effort", default="low" if kind == "identity" else "medium")
        a.add_argument("--makes", default=None, help="comma-separated make names (pilot), default: all")
        a.add_argument("--limit", type=int, default=None, help="max requests")
        if kind == "specs":
            a.add_argument("--min-listings", type=int, default=3, help="only variants with this many listings")
        a.add_argument("--run-id", type=int, default=None, help="ai_run to collect (default: latest submitted)")

    r = ks.add_parser("review", help="human review round-trip (CSV, opens in Excel)")
    rs = r.add_subparsers(dest="review_cmd", required=True)
    re_ = rs.add_parser("export", help="write open cases, ordered by level and listings unblocked")
    re_.add_argument("--out", type=Path, default=Path("data/review.csv"))
    re_.add_argument("--sample-size", type=int, default=50)
    re_.add_argument("--seed", type=int, default=20261120)
    re_.add_argument("--min-accuracy", type=float, default=0.95)
    re_.add_argument("--min-confidence", type=float, default=0.8)
    re_.add_argument("--limit", type=int, default=None)
    ri = rs.add_parser("import", help="apply decisions from a filled review CSV")
    ri.add_argument("path", type=Path)
    ri.add_argument("--reviewer", required=True, help="who reviewed (stored with each decision)")
    rw = rs.add_parser("worker", help="apply decisions queued by the review website (src/web)")
    rw.add_argument("--propagate-idle", type=float, default=120.0,
                    help="seconds without new decisions before running normalize + consolidate (0 = never)")
    rw.add_argument("--poll", type=float, default=30.0, help="max seconds between queue checks")
    rw.add_argument("--once", action="store_true", help="apply the queue once (and propagate), then exit")

    gs = ks.add_parser("golden", help="identity accuracy: labelled sample vs pipeline")
    gss = gs.add_subparsers(dest="golden_cmd", required=True)
    gsa = gss.add_parser("sample", help="stratified random sample to label")
    gsa.add_argument("--out", type=Path, default=Path("data/golden_sample.csv"))
    gsa.add_argument("--size", type=int, default=300)
    gsa.add_argument("--seed", type=int, default=20261120)
    gsc = gss.add_parser("score", help="compare validated labels with the pipeline")
    gsc.add_argument("path", type=Path)

    e = ks.add_parser("export", help="kb.listing_standardized as csv/xlsx/json")
    e.add_argument("--format", choices=["csv", "xlsx", "json"], default="csv")
    e.add_argument("--out", type=Path, default=None)
    e.add_argument("--with-sources", action="store_true", help="include the <field>__src columns")

    ks.add_parser("status", help="counts per table, review queue, coverage of the published sheets")

    fj = ks.add_parser("fields-json", help="field types/ranges/units for the review website (no database)")
    fj.add_argument("--out", type=Path, default=ROOT / "src" / "web" / "src" / "generated" / "kb-fields.json")


# Commands that only read; every other one takes the writer lock (one writer at a time).
READ_ONLY = {"status", "export", "golden"}


def run(args) -> int:
    if args.kb_cmd == "fields-json":
        import json
        from .fields import fields_catalog
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(fields_catalog(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {args.out}")
        return 0
    if args.kb_cmd == "review" and args.review_cmd == "worker":
        import logging
        from .worker import WorkerSettings, run_worker
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        return run_worker(args.database_url, WorkerSettings(propagate_idle=args.propagate_idle, poll=args.poll),
                          once=args.once)

    from .db import database_url
    if args.kb_cmd == "migrate":
        url = database_url(args.database_url)
        cmd = [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "-x", f"url={url}",
               "downgrade" if args.downgrade else "upgrade", args.revision]
        return subprocess.call(cmd, cwd=ROOT)

    from .db import connect, writer_lock
    with connect(args.database_url) as conn:
        if args.kb_cmd not in READ_ONLY:
            writer_lock(conn, "Waiting for another writer (kb command or review worker) to finish...")
        if args.kb_cmd == "import":
            from .importer import import_sqlite
            s = import_sqlite(conn, args.sqlite)
            if s["skipped"]:
                print(f"{s['file']} already imported (sha256 {s['sha256'][:12]}): nothing to do")
            else:
                print(f"Imported {s['rows']} rows: {s['new']} new, {s['changed']} changed (new version), "
                      f"{s['unchanged']} unchanged")
                if s["unknown_sites"]:
                    print(f"New sources registered with AI and training OFF: {', '.join(s['unknown_sites'])} "
                          "(review their terms, then UPDATE kb.source_site)")
        elif args.kb_cmd == "normalize":
            from .identity import normalize
            s = normalize(conn)
            print(f"Listings: {s.listings}  new makes: {s.makes_new}  new models: {s.models_new}  "
                  f"new trims: {s.trims_new}  new review cases: {s.review_items}")
            if s.excluded:
                print("Excluded: " + ", ".join(f"{k}={v}" for k, v in s.excluded.most_common()))
        elif args.kb_cmd == "consolidate":
            from .consensus import Settings, consolidate
            s = consolidate(conn, Settings(args.min_support, args.min_agreement))
            print(f"Listings used: {s.listings} (waiting on identity: {s.waiting})  variants: {s.variants}  "
                  f"partial matches: {s.partial_matches}  clusters: {s.clusters}")
            print("Evidence: " + ", ".join(f"{k}={v}" for k, v in sorted(s.evidence.items())))
            if s.flagged:
                print("Flagged for review: " + ", ".join(f"{k}={v}" for k, v in s.flagged.most_common()))
            print(f"Published: {s.published_mech} mechanical sheets, {s.published_equip} equipment sheets, "
                  f"{s.changes} field changes recorded in spec_history")
        elif args.kb_cmd in ("ai-identity", "ai-specs"):
            from .ai_batch import run_cli
            return run_cli(conn, args)
        elif args.kb_cmd == "review":
            from .review import export_review, import_review
            if args.review_cmd == "export":
                n = export_review(conn, args.out, sample_size=args.sample_size, seed=args.seed,
                                  min_accuracy=args.min_accuracy, min_confidence=args.min_confidence,
                                  limit=args.limit)
                print(f"Wrote {n} review rows to {args.out}. Fill `decision` (approve/reject/correct) and "
                      f"`corrected_value`, then: kb review import {args.out} --reviewer <name>")
            else:
                s = import_review(conn, args.path, args.reviewer)
                print(", ".join(f"{k}={v}" for k, v in s.items()))
                if s.get("invalid_value"):
                    print("invalid_value: corrections that don't parse or are out of range were left pending.")
                print("Run `kb normalize` and `kb consolidate` to propagate the decisions.")
        elif args.kb_cmd == "golden":
            from .golden import golden_sample, golden_score
            if args.golden_cmd == "sample":
                n = golden_sample(conn, args.out, args.size, args.seed)
                print(f"Wrote {n} listings to {args.out}")
            else:
                for line in golden_score(conn, args.path):
                    print(line)
        elif args.kb_cmd == "export":
            from .export import export
            out = args.out or Path(f"data/kb_listings.{args.format}")
            n = export(conn, out, args.format, args.with_sources)
            print(f"Exported {n} standardized listings to {out}")
        elif args.kb_cmd == "status":
            from .export import status
            print(status(conn))
    return 0
