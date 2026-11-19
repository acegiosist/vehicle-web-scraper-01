"""Human review loop for the catalog: export open review items, import decisions.

    catalog review --export data/catalog_review.xlsx     # open it in Excel, fill `decision`
    catalog review --import data/catalog_review.xlsx     # applies approve / reject / correct

decision: approve  -> apply the stored proposal (method "human")
          reject   -> close the item, nothing applied
          correct  -> apply the JSON in `correction` instead (same shape as `proposal`)
Rows with an empty decision stay open. A .csv (UTF-8) works too in both directions.
"""
from __future__ import annotations

import csv
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from ..xlsx import write_xlsx
from . import schema as S
from .validate import apply_proposal

COLUMNS = ["id", "entity_type", "entity_key", "reason", "detail", "proposal", "decision", "correction"]


def export_review(engine: Engine, path: Path) -> int:
    with engine.connect() as conn:
        rows = conn.execute(select(S.review_item).where(S.review_item.c.status == "open")
                            .order_by(S.review_item.c.reason, S.review_item.c.entity_key)).mappings().all()
    data = [[r["id"], r["entity_type"], r["entity_key"], r["reason"], r["detail"],
             json.dumps(r["proposal"], ensure_ascii=False) if r["proposal"] is not None else "", "", ""] for r in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            w.writerows(data)
    else:
        write_xlsx(path, COLUMNS, data, sheet_name="review")
    return len(data)


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(path: Path) -> list[dict]:
    """First sheet as dicts (header row = keys). Handles shared and inline strings, which covers
    files written by xlsx.py and files saved again by Excel / LibreOffice."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        sheet = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))[0]
        root = ET.fromstring(z.read(sheet))
    table = []
    for row in root.iter(f"{{{_NS['m']}}}row"):
        cells: dict[int, str] = {}
        for c in row.findall("m:c", _NS):
            t, v = c.get("t"), c.find("m:v", _NS)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{_NS['m']}}}t"))
            else:
                val = v.text if v is not None else ""
            cells[_col_index(c.get("r"))] = val or ""
        if cells:
            table.append([cells.get(i, "") for i in range(max(cells) + 1)])
    if not table:
        return []
    header = [h.strip() for h in table[0]]
    return [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in table[1:]]


def _read(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    return read_xlsx(path)


def import_review(engine: Engine, path: Path, reviewer: str = "human") -> dict:
    counts = {"approved": 0, "rejected": 0, "corrected": 0, "open": 0, "errors": []}
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        for r in _read(path):
            decision = (r.get("decision") or "").strip().lower()
            if not decision or not str(r.get("id", "")).strip():
                counts["open"] += 1
                continue
            item_id = int(float(r["id"]))
            item = conn.execute(select(S.review_item).where(S.review_item.c.id == item_id)).mappings().first()
            if item is None or item["status"] != "open":
                continue
            try:
                if decision in ("approve", "approved", "aprobar", "si", "sí", "yes"):
                    if item["proposal"]:
                        apply_proposal(conn, item["proposal"], method="human")
                    status = "approved"
                elif decision in ("reject", "rejected", "rechazar", "no"):
                    status = "rejected"
                elif decision in ("correct", "corrected", "corregir"):
                    apply_proposal(conn, json.loads(r.get("correction") or "{}"), method="human")
                    status = "corrected"
                else:
                    raise ValueError(f"unknown decision {decision!r}")
            except (ValueError, KeyError, json.JSONDecodeError) as e:
                counts["errors"].append(f"item {item_id}: {e}")
                continue
            conn.execute(update(S.review_item).where(S.review_item.c.id == item_id).values(
                status=status, decided_by=reviewer, decided_at=now))
            counts[status] += 1
    return counts
