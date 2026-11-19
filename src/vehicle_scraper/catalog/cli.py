"""`catalog` subcommands (wired into vehicle_scraper.cli).

    catalog build                         raw vehicles.sqlite -> catalog DB (rules only, free)
    catalog export-ddl [--out schema.sql] PostgreSQL DDL of the catalog schema
    catalog ai-prepare [--make toyota] [--max-requests N] [--estimate]
    catalog ai-submit --yes [--run ID]    sends the batch (spends money)
    catalog ai-status [--run ID]
    catalog ai-ingest [--run ID]          validate + apply results, then rebuild
    catalog review --export FILE | --import FILE
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import settings


def add_parser(sub) -> None:
    c = sub.add_parser("catalog", help="build the normalized vehicle catalog (knowledge base)")
    c.add_argument("--db", default=None, help="catalog database URL (default: CATALOG_DATABASE_URL or data/catalog.sqlite)")
    c.add_argument("--raw-db", type=Path, default=None, help="scraper SQLite to read (default: data/vehicles.sqlite)")
    cs = c.add_subparsers(dest="catalog_cmd", required=True)
    cs.add_parser("build", help="canonicalize listings into make/model/trim/variant (rules only)")
    d = cs.add_parser("export-ddl", help="write the catalog schema as SQL DDL")
    d.add_argument("--out", type=Path, default=None)
    d.add_argument("--dialect", choices=["postgresql", "sqlite"], default="postgresql")
    p = cs.add_parser("ai-prepare", help="prepare the AI batch for what rules could not settle")
    p.add_argument("--make", action="append", default=[], help="only this make slug (repeatable), e.g. toyota")
    p.add_argument("--max-requests", type=int, default=None, help="cap the number of requests (pilot runs)")
    p.add_argument("--estimate", action="store_true", help="count tokens with the API (free) and estimate cost")
    s = cs.add_parser("ai-submit", help="send the prepared batch to the Message Batches API")
    s.add_argument("--run", type=int, default=None)
    s.add_argument("--yes", action="store_true", help="confirm: this spends API credit")
    st = cs.add_parser("ai-status", help="show the batch status")
    st.add_argument("--run", type=int, default=None)
    i = cs.add_parser("ai-ingest", help="validate and apply the batch results, then rebuild")
    i.add_argument("--run", type=int, default=None)
    r = cs.add_parser("review", help="export / import the human review queue")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--export", type=Path, metavar="FILE", help=".xlsx or .csv")
    g.add_argument("--import", dest="import_", type=Path, metavar="FILE", help=".xlsx or .csv")
    r.add_argument("--reviewer", default="human")


def _client():
    import anthropic
    return anthropic.Anthropic()


def run(args: argparse.Namespace) -> int:
    from . import schema as S
    from .build import build_catalog, load_raw_rows

    engine = S.get_engine(args.db or settings.catalog_url)
    raw_db = args.raw_db or settings.db_path
    ai_dir = settings.data_dir / "ai"
    cmd = args.catalog_cmd

    if cmd == "export-ddl":
        sql = S.ddl(args.dialect)
        if args.out:
            args.out.write_text(sql, encoding="utf-8")
            print(f"Wrote {args.out} ({sql.count('CREATE TABLE')} tables)")
        else:
            print(sql)
        return 0

    if cmd in ("build", "ai-prepare", "ai-ingest") and not Path(raw_db).exists():
        print(f"No scraper database at {raw_db}: run the scraper first.", file=sys.stderr)
        return 1

    if cmd == "build":
        print(build_catalog(engine, load_raw_rows(raw_db)).text())
        return 0

    if cmd == "ai-prepare":
        from .ai_batch import estimate, prepare
        rep = build_catalog(engine, load_raw_rows(raw_db))
        prep = prepare(engine, rep.resolution, ai_dir, set(args.make) or None, args.max_requests)
        print(f"Memoized (already decided, not sent again): {prep.skipped_memoized}")
        if not prep.requests:
            print("Nothing new for the AI step.")
            return 0
        print(f"Prepared run {prep.run_id}: {len(prep.requests)} requests, {prep.n_models} model lines, "
              f"{prep.n_trims} trim lines -> {prep.path}")
        client = None
        if args.estimate:
            try:
                client = _client()
            except Exception as e:  # noqa: BLE001 - no credentials: fall back to the approximation
                print(f"(no API client: {e}; using an approximation)")
        try:
            est = estimate(prep.requests, prep.n_models + prep.n_trims, client)
        except Exception as e:  # noqa: BLE001
            print(f"(count_tokens failed: {e}; using an approximation)")
            est = estimate(prep.requests, prep.n_models + prep.n_trims, None)
        print(f"Estimate [{est['method']}]: {est['input_tokens']:,} input tokens "
              f"(system prompt {est['system_tokens']:,}, cached after the first request), "
              f"~{est['est_output_tokens']:,} output tokens")
        print(f"Cost at Batch prices: ~US${est['usd_with_cache']:.2f} with cache hits, "
              f"US${est['usd_no_cache']:.2f} without. Send it with: catalog ai-submit --yes")
        return 0

    if cmd == "ai-submit":
        if not args.yes:
            print("This sends the batch to the Anthropic API and spends credit. Re-run with --yes.", file=sys.stderr)
            return 1
        from .ai_batch import submit
        print(f"Submitted batch {submit(engine, _client(), ai_dir, args.run)}. Check it with: catalog ai-status")
        return 0

    if cmd == "ai-status":
        from .ai_batch import status
        print(json.dumps(status(engine, _client(), args.run), indent=2))
        return 0

    if cmd == "ai-ingest":
        from .ai_batch import _run, ingest, status
        # One client for the whole command, kept open until the results are read: results() streams the
        # JSONL over the client's connection, and a throwaway client gets garbage-collected (closing that
        # connection) mid-download -> "WinError 10038 ... not a socket".
        with _client() as client:
            st = status(engine, client, args.run)
            if st.get("status") != "ended":
                print(f"Batch not finished yet: {st}", file=sys.stderr)
                return 1
            run_row = _run(engine, args.run)
            rep = ingest(engine, client.messages.batches.results(run_row["batch_id"]), run_row["id"])
        print(rep.text())
        print("\nRebuilding the catalog with the accepted decisions:")
        print(build_catalog(engine, load_raw_rows(raw_db)).text())
        return 0

    if cmd == "review":
        from .review import export_review, import_review
        if args.export:
            n = export_review(engine, args.export)
            print(f"Exported {n} open review items to {args.export}")
        else:
            counts = import_review(engine, args.import_, args.reviewer)
            print(json.dumps(counts, indent=2, ensure_ascii=False))
            if Path(raw_db).exists():
                print("\nRebuilding the catalog with the review decisions:")
                print(build_catalog(engine, load_raw_rows(raw_db)).text())
        return 0
    return 1
