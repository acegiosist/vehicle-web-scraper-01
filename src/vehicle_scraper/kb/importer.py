"""``kb import``: copy the scraper's listings (vehicles.sqlite) into ``staging.raw_listing``.

* The SQLite file is opened read-only; nothing in it is changed.
* Each row is stored as read (``data`` jsonb). A listing gets a new version only when its
  ``row_hash`` changes; the previous version is closed (``valid_to``). Re-importing the same
  data adds nothing.
* Rows from a site not registered in ``kb.source_site`` are not imported; they are counted in
  ``import_batch.skipped`` and reported, so a site never enters with a guessed country.
* A file whose sha256 was already imported in full is skipped, unless ``force``.
* Everything runs in one transaction under the writer lock: a failure leaves nothing behind.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Iterator

from .db import take_writer_lock

HASH_EXCLUDED = ("scraped_at",)     # changes on every re-scrape without the listing changing


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(row: dict) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def row_hash(row: dict) -> str:
    return hashlib.sha256(
        canonical_json({k: v for k, v in row.items() if k not in HASH_EXCLUDED}).encode("utf-8")
    ).hexdigest()


def read_sqlite(path: Path) -> Iterator[dict]:
    """Every row of the scraper's ``vehicles`` table, opening the file read-only."""
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        for r in con.execute("SELECT * FROM vehicles ORDER BY source_site, listing_id"):
            yield dict(r)
    finally:
        con.close()


def import_sqlite(conn, path: Path, force: bool = False) -> dict:
    """Import ``path`` into staging. Returns a summary dict (also stored in import_batch)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    sha = file_sha256(path)
    with conn.transaction(), conn.cursor() as cur:
        take_writer_lock(cur)
        if not force:
            cur.execute("SELECT id, skipped FROM staging.import_batch WHERE file_sha256 = %s "
                        "ORDER BY id DESC LIMIT 1", (sha,))
            prev = cur.fetchone()
            if prev and not prev[1]:
                return {"status": "already_imported", "batch_id": prev[0], "file": str(path)}

        cur.execute("SELECT code FROM kb.source_site")
        sites = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT source_site, listing_id, version, row_hash FROM staging.raw_listing "
                    "WHERE valid_to IS NULL")
        current = {(s, i): (v, h) for s, i, v, h in cur.fetchall()}
        cur.execute("INSERT INTO staging.import_batch (source_file, file_sha256) VALUES (%s, %s) "
                    "RETURNING id", (str(path), sha))
        batch_id = cur.fetchone()[0]

        stats = Counter()
        skipped: Counter = Counter()
        to_close: list[tuple[str, str]] = []
        to_insert: list[tuple] = []
        for row in read_sqlite(path):
            stats["rows_read"] += 1
            site, listing_id = row.get("source_site"), str(row.get("listing_id"))
            if site not in sites:
                skipped[str(site)] += 1
                continue
            h = row_hash(row)
            prev = current.get((site, listing_id))
            if prev and prev[1] == h:
                stats["unchanged"] += 1
                continue
            if prev:
                to_close.append((site, listing_id))
                stats["new_versions"] += 1
            else:
                stats["new_listings"] += 1
            to_insert.append((site, listing_id, prev[0] + 1 if prev else 1, h, canonical_json(row),
                              row.get("listed_at") or None, row.get("scraped_at") or None, batch_id))

        if to_close:
            cur.executemany("UPDATE staging.raw_listing SET valid_to = now() "
                            "WHERE source_site = %s AND listing_id = %s AND valid_to IS NULL", to_close)
        with cur.copy("COPY staging.raw_listing (source_site, listing_id, version, row_hash, data, "
                      "listed_at, scraped_at, import_batch_id) FROM STDIN") as copy:
            for rec in to_insert:
                copy.write_row(rec)

        cur.execute("UPDATE staging.import_batch SET rows_read = %s, new_listings = %s, new_versions = %s, "
                    "unchanged = %s, skipped = %s WHERE id = %s",
                    (stats["rows_read"], stats["new_listings"], stats["new_versions"], stats["unchanged"],
                     json.dumps(dict(sorted(skipped.items()))), batch_id))
    return {"status": "imported", "batch_id": batch_id, "file": str(path),
            "rows_read": stats["rows_read"], "new_listings": stats["new_listings"],
            "new_versions": stats["new_versions"], "unchanged": stats["unchanged"],
            "skipped": dict(sorted(skipped.items()))}
