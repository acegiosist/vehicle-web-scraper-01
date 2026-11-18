"""SQLite storage (upsert by site + listing id) with CSV / JSON / Excel export."""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from .models import ALL_FIELDS, VehicleRecord


class Storage:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        cols = ", ".join(f'"{c}"' for c in ALL_FIELDS)
        self.conn.execute(
            f"CREATE TABLE IF NOT EXISTS vehicles ({cols}, PRIMARY KEY (source_site, listing_id))"
        )
        self._ensure_columns()
        self.conn.commit()

    def _ensure_columns(self) -> None:
        """Add columns introduced by newer schema versions."""
        existing = {r[1] for r in self.conn.execute("PRAGMA table_info(vehicles)")}
        for c in ALL_FIELDS:
            if c not in existing:
                self.conn.execute(f'ALTER TABLE vehicles ADD COLUMN "{c}"')

    def has(self, site: str, listing_id: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM vehicles WHERE source_site=? AND listing_id=?", (site, str(listing_id)))
        return cur.fetchone() is not None

    def save(self, rec: VehicleRecord) -> None:
        row = rec.to_row()
        for k, v in row.items():
            if isinstance(v, bool):
                row[k] = int(v)
        cols = ", ".join(f'"{c}"' for c in row)
        marks = ", ".join("?" for _ in row)
        self.conn.execute(f"INSERT OR REPLACE INTO vehicles ({cols}) VALUES ({marks})", list(row.values()))
        self.conn.commit()

    def rows(self, site: Optional[str] = None) -> list[dict]:
        self.conn.row_factory = sqlite3.Row
        q, args = "SELECT * FROM vehicles", ()
        if site:
            q, args = q + " WHERE source_site=?", (site,)
        out = [dict(r) for r in self.conn.execute(q + " ORDER BY source_site, listing_id", args)]
        self.conn.row_factory = None
        return out

    def export_csv(self, path: Path, site: Optional[str] = None) -> int:
        rows = self.rows(site)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as f:   # BOM so Excel reads accents
            w = csv.DictWriter(f, fieldnames=ALL_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(_bools_out(rows))
        return len(rows)

    def export_json(self, path: Path, site: Optional[str] = None) -> int:
        rows = _bools_out(self.rows(site))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return len(rows)

    def export_xlsx(self, path: Path, site: Optional[str] = None) -> int:
        """Every column of the vehicles table (not only the current schema's), one row per listing."""
        from .xlsx import write_xlsx
        columns = [r[1] for r in self.conn.execute("PRAGMA table_info(vehicles)")]
        rows = _bools_out(self.rows(site))
        return write_xlsx(path, columns, ([r.get(c) for c in columns] for r in rows), sheet_name="vehicles")

    def close(self) -> None:
        self.conn.close()


def _bools_out(rows: Iterable[dict]) -> list[dict]:
    from .models import BOOLEAN_FIELDS
    out = []
    for r in rows:
        r = dict(r)
        for f in BOOLEAN_FIELDS:
            if r.get(f) is not None:
                r[f] = bool(r[f])
        out.append(r)
    return out
