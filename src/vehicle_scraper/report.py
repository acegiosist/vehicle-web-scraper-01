"""Field-coverage report: % of non-null values per schema field, per site."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from .models import LISTING_FIELDS, SCHEMA_FIELDS

FIELDS = LISTING_FIELDS + SCHEMA_FIELDS


def coverage(rows: list[dict]) -> tuple[dict[str, dict[str, float]], dict[str, int]]:
    by_site: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_site[r["source_site"]].append(r)
    pct = {
        site: {f: round(100 * sum(r.get(f) is not None for r in rs) / len(rs), 1) for f in FIELDS}
        for site, rs in by_site.items()
    }
    return pct, {site: len(rs) for site, rs in by_site.items()}


def write_coverage(rows: list[dict], path: Path) -> str:
    """Write coverage CSV and return a console table."""
    pct, counts = coverage(rows)
    sites = sorted(pct)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["field"] + sites)
        w.writerow(["(listings)"] + [counts[s] for s in sites])
        for fld in FIELDS:
            w.writerow([fld] + [pct[s][fld] for s in sites])
    lines = [f"{'field':<30}" + "".join(f"{s:>12}" for s in sites),
             f"{'(listings)':<30}" + "".join(f"{counts[s]:>12}" for s in sites)]
    lines += [f"{fld:<30}" + "".join(f"{pct[s][fld]:>11.0f}%" for s in sites) for fld in FIELDS]
    return "\n".join(lines)
