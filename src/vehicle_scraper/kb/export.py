"""`kb export` (standardized listings) and `kb status`."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from ..xlsx import write_xlsx
from .fields import EQUIP_FIELDS, MECH_FIELDS


def export(conn, out: Path, fmt: str = "csv", with_sources: bool = False) -> int:
    cur = conn.execute("SELECT * FROM kb.listing_standardized ORDER BY source_site, listing_id")
    cols = [d.name for d in cur.description]
    if not with_sources:
        cols = [c for c in cols if not c.endswith("__src")]
    rows = [{c: r[c] for c in cols} for r in cur.fetchall()]
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    elif fmt == "json":
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    else:
        write_xlsx(out, cols, ([r[c] for c in cols] for r in rows), sheet_name="listings")
    return len(rows)


def status(conn) -> str:
    q = lambda sql, *a: conn.execute(sql, a).fetchall()   # noqa: E731
    lines = ["Identity:"]
    for t in ("make", "model", "trim"):
        counts = ", ".join(f"{r['status']}={r['n']}" for r in q(f"SELECT status, count(*) AS n FROM kb.{t} GROUP BY 1 ORDER BY 1"))
        lines.append(f"  {t:6} {counts}")
    total = q("SELECT count(*) AS n, count(variant_id) AS v FROM kb.listing")[0]
    lines.append(f"Listings: {total['n']} ({total['v']} matched to a variant)")
    lines.append(f"Variants: {q('SELECT count(*) AS n FROM kb.variant')[0]['n']}  "
                 f"mechanical sheets: {q('SELECT count(*) AS n FROM kb.variant_spec')[0]['n']}  "
                 f"equipment sheets: {q('SELECT count(*) AS n FROM kb.variant_market_spec')[0]['n']}")
    lines.append("Review queue (pending):")
    for r in q("SELECT level, kind, issue, count(*) AS n, sum(listings_affected) AS l FROM kb.review_item "
               "WHERE status = 'pending' GROUP BY 1, 2, 3 ORDER BY 1, 2, 4 DESC"):
        lines.append(f"  L{r['level']} {r['kind']:10} {r['issue']:24} {r['n']:6} cases  {r['l'] or 0:7} listings")
    lines.append("Coverage of published listings (kb.listing_standardized, % non-null):")
    fields = MECH_FIELDS + EQUIP_FIELDS
    exprs = ", ".join(f"round(100.0 * count({f}) / greatest(count(*), 1), 1) AS {f}" for f in fields)
    cov = q(f"SELECT {exprs} FROM kb.listing_standardized WHERE variant_id IS NOT NULL")[0]
    for i in range(0, len(fields), 4):
        lines.append("  " + "  ".join(f"{f}={cov[f]}" for f in fields[i:i + 4]))
    for r in q("SELECT kind, status, count(*) AS n, sum(request_count) AS req, sum(est_cost_usd) AS usd FROM kb.ai_run GROUP BY 1, 2"):
        lines.append(f"AI runs: {r['kind']} {r['status']} runs={r['n']} requests={r['req']} est=US${r['usd']}")
    for r in q("SELECT id, kind, ended_at, batch_counts FROM kb.ai_run WHERE status = 'ended' ORDER BY id"):
        lines.append(f"AI run {r['id']} ({r['kind']}) finished {r['ended_at']:%Y-%m-%d %H:%M} {r['batch_counts'] or {}}: "
                     f"collect it with `kb ai-{r['kind']} --collect --run-id {r['id']}`")
    return "\n".join(lines)
