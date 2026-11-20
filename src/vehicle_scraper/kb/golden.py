"""Golden set: measure how often the pipeline gets make / model / trim / year right.

`kb golden sample` draws a stratified random sample (site x vehicle class x common/rare model)
with a fixed seed. The first ``BLIND`` rows hide the pipeline's answer so the team can label
them without being anchored by it; the rest show it next to empty label columns.
`kb golden score` compares the validated labels with what the pipeline says *now*.
"""
from __future__ import annotations

import csv
import random
from collections import defaultdict
from pathlib import Path

from .db import compact_key

BLIND = 50
TARGETS = {"make": 0.98, "model": 0.98, "year": 0.95, "trim": 0.90}
COLUMNS = ["source_site", "listing_id", "source_url", "raw_make", "raw_model", "raw_trim", "raw_year",
           "blind", "pipeline_make", "pipeline_model", "pipeline_trim", "pipeline_year_ok",
           "label_make", "label_model", "label_trim", "label_year_ok", "label_source", "label_note"]


def _pipeline(conn) -> dict[tuple, dict]:
    rows = conn.execute(
        """SELECT l.source_site, l.listing_id, l.raw_make, l.raw_model, l.raw_trim, l.raw_year, md.vehicle_class,
                  r.row->>'source_url' AS source_url, mk.name AS make, mk.status AS make_status,
                  md.name AS model, md.status AS model_status, t.name AS trim, l.excluded_reason,
                  (SELECT count(*) FROM kb.listing x WHERE x.model_id = l.model_id) AS model_listings
           FROM kb.listing l
           JOIN staging.raw_listing r ON r.source_site = l.source_site AND r.listing_id = l.listing_id
                                     AND r.version = l.current_version
           LEFT JOIN kb.make mk ON mk.id = l.make_id LEFT JOIN kb.model md ON md.id = l.model_id
           LEFT JOIN kb.trim t ON t.id = l.trim_id""").fetchall()
    return {(r["source_site"], r["listing_id"]): r for r in rows}


def golden_sample(conn, out: Path, size: int = 300, seed: int = 20261120) -> int:
    data = _pipeline(conn)
    strata: dict[tuple, list] = defaultdict(list)
    for key, r in sorted(data.items()):
        strata[(r["source_site"], r["vehicle_class"] or "?", "common" if r["model_listings"] >= 5 else "rare")].append(r)
    rng = random.Random(seed)
    total = sum(len(v) for v in strata.values())
    picked = []
    for key in sorted(strata):
        items = strata[key]
        n = max(2, round(size * len(items) / total))       # every stratum is represented
        picked += rng.sample(items, min(n, len(items)))
    rng.shuffle(picked)
    picked = picked[:size]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for i, r in enumerate(picked):
            blind = i < BLIND
            w.writerow({"source_site": r["source_site"], "listing_id": r["listing_id"], "source_url": r["source_url"],
                        "raw_make": r["raw_make"], "raw_model": r["raw_model"], "raw_trim": r["raw_trim"],
                        "raw_year": r["raw_year"], "blind": "yes" if blind else "",
                        "pipeline_make": "" if blind else r["make"], "pipeline_model": "" if blind else r["model"],
                        "pipeline_trim": "" if blind else (r["trim"] or ""),
                        "pipeline_year_ok": "" if blind else ("no" if (r["excluded_reason"] or "").startswith("year") else "yes")})
    return len(picked)


def golden_score(conn, path: Path) -> list[str]:
    data = _pipeline(conn)
    hits, totals = defaultdict(int), defaultdict(int)
    misses: dict[str, list[str]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            r = data.get((row["source_site"], row["listing_id"]))
            if not r or not (row.get("label_make") or "").strip():
                continue
            checks = {
                "make": (row["label_make"], r["make"] if r["make_status"] == "accepted" else None),
                "model": (row["label_model"], r["model"] if r["model_status"] == "accepted" else None),
                "trim": (row.get("label_trim") or "", r["trim"] or ""),
            }
            for name, (label, got) in checks.items():
                if name == "trim" and not label and not got:
                    continue
                totals[name] += 1
                if compact_key(label) == compact_key(got):
                    hits[name] += 1
                else:
                    misses[name].append(f"{row['source_site']}:{row['listing_id']} label={label!r} pipeline={got!r}")
            if (row.get("label_year_ok") or "").strip():
                totals["year"] += 1
                ok_label = row["label_year_ok"].strip().lower() in ("yes", "si", "sí", "true", "1")
                ok_pipe = not (r["excluded_reason"] or "").startswith("year")
                hits["year"] += int(ok_label == ok_pipe)
    lines = []
    for name, target in TARGETS.items():
        if totals[name]:
            acc = hits[name] / totals[name]
            lines.append(f"{name:6} {acc:6.1%} ({hits[name]}/{totals[name]})  target {target:.0%}  "
                         f"{'OK' if acc >= target else 'BELOW TARGET'}")
        else:
            lines.append(f"{name:6} no labels")
    for name, items in misses.items():
        lines += [f"  miss {name}: {m}" for m in items[:10]]
    return lines
