"""`kb import`: copy vehicles.sqlite (read-only) into staging, with per-listing history.

* The same file (same sha256) never creates a second snapshot.
* A listing is keyed by (source_site, listing_id). A new version is stored only when its
  content changes (``row_hash``); the old version gets ``valid_to`` and stops voting.
* ``kb.listing`` is upserted (first_seen / last_seen). A listing whose content changed has its
  identity cleared so the next ``kb normalize`` resolves it again.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path

from ..models import BOOLEAN_FIELDS
from .db import dumps, jsonb

log = logging.getLogger(__name__)

# Fields that change on every scrape without the car changing: kept in the row, not hashed.
VOLATILE = {"scraped_at", "parse_warnings"}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_sqlite(path: Path) -> list[dict]:
    """Rows of the scraper's vehicles table, booleans as real booleans. Opened read-only."""
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM vehicles ORDER BY source_site, listing_id")]
    finally:
        conn.close()
    for r in rows:
        for f in BOOLEAN_FIELDS:
            if r.get(f) is not None:
                r[f] = bool(r[f])
        r["listing_id"] = str(r["listing_id"])
    return rows


def row_hash(row: dict) -> str:
    return hashlib.sha256(dumps({k: v for k, v in row.items() if k not in VOLATILE}).encode()).hexdigest()


def import_sqlite(conn, path: Path) -> dict:
    sha = file_sha256(path)
    stats = {"file": str(path), "sha256": sha, "rows": 0, "new": 0, "changed": 0, "unchanged": 0,
             "skipped": False, "unknown_sites": []}
    if conn.execute("SELECT 1 FROM staging.import_snapshot WHERE sha256 = %s", (sha,)).fetchone():
        stats["skipped"] = True
        return stats
    rows = read_sqlite(path)
    stats["rows"] = len(rows)

    sites = {r["site"]: r for r in conn.execute("SELECT * FROM kb.source_site").fetchall()}
    for site in sorted({r["source_site"] for r in rows} - set(sites)):
        # Unknown source: registered with AI and training OFF until someone reviews its terms.
        conn.execute("INSERT INTO kb.source_site (site, country, ai_allowed, training_allowed, notes) "
                     "VALUES (%s, %s, false, false, 'auto-registered on import: review its terms')",
                     (site, "??"))
        stats["unknown_sites"].append(site)
        sites[site] = {"site": site, "country": "??"}

    snap = conn.execute("INSERT INTO staging.import_snapshot (source_file, sha256, row_count) "
                        "VALUES (%s, %s, %s) RETURNING id", (str(path), sha, len(rows))).fetchone()["id"]
    current = {(r["source_site"], r["listing_id"]): (r["version"], r["row_hash"]) for r in conn.execute(
        "SELECT source_site, listing_id, version, row_hash FROM staging.raw_listing WHERE valid_to IS NULL")}

    new_versions, touched = [], []
    for r in rows:
        key = (r["source_site"], r["listing_id"])
        h = row_hash(r)
        prev = current.get(key)
        if prev and prev[1] == h:
            stats["unchanged"] += 1
            touched.append(key)
            continue
        version = (prev[0] + 1) if prev else 1
        stats["changed" if prev else "new"] += 1
        new_versions.append((r, key, version, h, prev is not None))

    with conn.cursor() as cur:
        changed_keys = [k for _, k, _, _, was in new_versions if was]
        if changed_keys:
            cur.executemany("UPDATE staging.raw_listing SET valid_to = now() "
                            "WHERE source_site = %s AND listing_id = %s AND valid_to IS NULL", changed_keys)
        cur.executemany(
            "INSERT INTO staging.raw_listing (source_site, listing_id, version, row_hash, row, snapshot_id) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [(k[0], k[1], v, h, jsonb(r), snap) for r, k, v, h, _ in new_versions])
        cur.executemany(
            """INSERT INTO kb.listing (source_site, listing_id, current_version, country, listed_at,
                                       raw_make, raw_model, raw_trim, raw_year)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (source_site, listing_id) DO UPDATE SET
                   current_version = EXCLUDED.current_version, last_seen = now(),
                   listed_at = EXCLUDED.listed_at, raw_make = EXCLUDED.raw_make,
                   raw_model = EXCLUDED.raw_model, raw_trim = EXCLUDED.raw_trim,
                   raw_year = EXCLUDED.raw_year,
                   make_id = NULL, model_id = NULL, trim_id = NULL, variant_id = NULL,
                   match_method = NULL, match_confidence = NULL, excluded_reason = NULL""",
            [(k[0], k[1], v, sites[k[0]]["country"], r.get("listed_at"), r.get("make"), r.get("model"),
              r.get("trim"), r.get("model_year")) for r, k, v, _, _ in new_versions])
        if touched:
            cur.executemany("UPDATE kb.listing SET last_seen = now() WHERE source_site = %s AND listing_id = %s",
                            touched)
    conn.execute("UPDATE staging.import_snapshot SET new_versions = %s WHERE id = %s", (len(new_versions), snap))
    return stats
