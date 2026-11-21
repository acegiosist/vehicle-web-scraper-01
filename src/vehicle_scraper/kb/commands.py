"""The `kb` commands as functions: the CLI (cli.py) prints their summary, the worker (worker.py)
runs them as jobs queued by the review website. One implementation for both.

Every function takes an open connection whose transaction the caller owns (and, for the ones
that write, the writer lock) and returns a ``CommandResult``.
"""
from __future__ import annotations

import gzip
import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .budget import budget_status

EXPORT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass
class OutputFile:
    filename: str
    content_type: str
    data: bytes          # gzip-compressed when ``gzipped``
    gzipped: bool
    size: int            # uncompressed size


@dataclass
class CommandResult:
    summary: str
    result: dict = field(default_factory=dict)
    file: Optional[OutputFile] = None


# --- recalculate ------------------------------------------------------------------------------------
def run_normalize(conn) -> CommandResult:
    from .identity import normalize
    s = normalize(conn)
    lines = [f"Listings: {s.listings}  new makes: {s.makes_new}  new models: {s.models_new}  "
             f"new trims: {s.trims_new}  new review cases: {s.review_items}"]
    if s.excluded:
        lines.append("Excluded: " + ", ".join(f"{k}={v}" for k, v in s.excluded.most_common()))
    return CommandResult("\n".join(lines), {
        "listings": s.listings, "makes_new": s.makes_new, "models_new": s.models_new, "trims_new": s.trims_new,
        "review_items": s.review_items, "excluded": dict(s.excluded)})


def run_consolidate(conn, min_support: int = 2, min_agreement: float = 0.7) -> CommandResult:
    from .consensus import Settings, consolidate
    s = consolidate(conn, Settings(min_support, min_agreement))
    lines = [f"Listings used: {s.listings} (waiting on identity: {s.waiting})  variants: {s.variants}  "
             f"partial matches: {s.partial_matches}  clusters: {s.clusters}",
             "Evidence: " + ", ".join(f"{k}={v}" for k, v in sorted(s.evidence.items()))]
    if s.flagged:
        lines.append("Flagged for review: " + ", ".join(f"{k}={v}" for k, v in s.flagged.most_common()))
    lines.append(f"Published: {s.published_mech} mechanical sheets, {s.published_equip} equipment sheets, "
                 f"{s.changes} field changes recorded in spec_history")
    return CommandResult("\n".join(lines), {
        "listings": s.listings, "waiting": s.waiting, "variants": s.variants, "clusters": s.clusters,
        "evidence": dict(s.evidence), "flagged": dict(s.flagged), "published_mech": s.published_mech,
        "published_equip": s.published_equip, "changes": s.changes})


def run_recalculate(conn, min_support: int = 2, min_agreement: float = 0.7) -> CommandResult:
    n = run_normalize(conn)
    c = run_consolidate(conn, min_support, min_agreement)
    return CommandResult(f"normalize\n{n.summary}\n\nconsolidate\n{c.summary}",
                         {"normalize": n.result, "consolidate": c.result})


# --- export ------------------------------------------------------------------------------------------
def run_export(conn, fmt: str = "csv", with_sources: bool = False, out: Optional[Path] = None) -> CommandResult:
    """Writes to ``out`` (CLI) or returns the file (web: gzip for csv/json, xlsx is already zip)."""
    from .export import export
    if fmt not in EXPORT_TYPES:
        raise ValueError(f"unknown export format: {fmt}")
    if out is not None:
        n = export(conn, out, fmt, with_sources)
        return CommandResult(f"Exported {n} standardized listings to {out}", {"rows": n, "path": str(out)})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"kb_listings.{fmt}"
        n = export(conn, path, fmt, with_sources)
        raw = path.read_bytes()
    gz = fmt != "xlsx"
    name = f"kb_listings{'_sources' if with_sources else ''}.{fmt}"
    data = gzip.compress(raw, mtime=0) if gz else raw
    return CommandResult(f"Exported {n} standardized listings ({fmt}, {len(raw):,} bytes)",
                         {"rows": n, "format": fmt, "with_sources": with_sources, "filename": name},
                         OutputFile(name, EXPORT_TYPES[fmt], data, gz, len(raw)))


# --- AI (Claude Message Batches) ----------------------------------------------------------------------
def _ai_requests(conn, kind: str, effort: str, makes: Optional[list[str]], limit: Optional[int],
                 min_listings: int) -> tuple[list[dict], int]:
    from . import ai_batch as ab
    wanted = {m.strip().lower() for m in makes if m.strip()} if makes else None
    reqs = ab.identity_requests(conn, wanted) if kind == "identity" else ab.specs_requests(conn, min_listings, wanted)
    reqs = ab._with_params(reqs, kind, effort)
    reqs, skipped = ab._drop_answered(conn, reqs)
    if limit:
        reqs = reqs[:limit]
    return reqs, skipped


def fingerprint(reqs: list[dict]) -> str:
    """Identifies the exact set of requests an estimate priced (sorted input hashes)."""
    return hashlib.sha256("\n".join(sorted(r["hash"] for r in reqs)).encode()).hexdigest()


def ai_params(kind: str, effort: Optional[str] = None, makes: Optional[list[str]] = None,
              limit: Optional[int] = None, min_listings: int = 3) -> dict:
    if kind not in ("identity", "specs"):
        raise ValueError(f"unknown AI kind: {kind}")
    return {"kind": kind, "effort": effort or ("low" if kind == "identity" else "medium"),
            "makes": sorted(makes) if makes else None, "limit": limit,
            "min_listings": min_listings if kind == "specs" else None}


def ai_estimate(conn, kind: str, effort: Optional[str] = None, makes: Optional[list[str]] = None,
                limit: Optional[int] = None, min_listings: int = 3, count_tokens: bool = False) -> CommandResult:
    from . import ai_batch as ab
    p = ai_params(kind, effort, makes, limit, min_listings)
    reqs, skipped = _ai_requests(conn, kind, p["effort"], p["makes"], limit, min_listings)
    budget = budget_status(conn)        # the website shows it and blocks "send" with its message
    if not reqs:
        return CommandResult(f"Nothing to send ({skipped} requests already answered).",
                             {"params": p, "requests": 0, "skipped": skipped, "fingerprint": fingerprint([]),
                              "budget": budget.as_json()})
    est = ab.estimate(reqs, kind, count_tokens)
    refusal = budget.refusal(est["cost_usd_est"])
    summary = (f"{kind}: {est['requests']} requests ({skipped} already answered, not resent), "
               f"~{est['input_tokens']:,} input tokens [{est['method']}], "
               f"~{est['output_tokens_est']:,} output+thinking tokens\n"
               f"Estimated cost (Batch, {ab.MODEL}, effort={p['effort']}): US${est['cost_usd_est']} "
               f"(range US${est['cost_usd_range'][0]}-{est['cost_usd_range'][1]})\n"
               f"{budget.describe()}" + (f"\n{refusal}" if refusal else ""))
    return CommandResult(summary, {"params": p, "requests": len(reqs), "skipped": skipped, "estimate": est,
                                   "model": ab.MODEL, "fingerprint": fingerprint(reqs),
                                   "budget": budget.as_json(est["cost_usd_est"])})


class SubmitRefused(RuntimeError):
    """An AI submission that failed one of its checks: nothing was sent, nothing was spent."""


def ai_submit(conn, kind: str, effort: Optional[str] = None, makes: Optional[list[str]] = None,
              limit: Optional[int] = None, min_listings: int = 3, *, expected_fingerprint: Optional[str] = None,
              max_usd: Optional[float] = None, submit_fn: Optional[Callable] = None) -> CommandResult:
    """Sends the batch (costs money). With ``expected_fingerprint`` / ``max_usd`` (the website's
    double control) it refuses when the requests changed since the estimate or cost more."""
    from . import ai_batch as ab
    p = ai_params(kind, effort, makes, limit, min_listings)
    reqs, skipped = _ai_requests(conn, kind, p["effort"], p["makes"], limit, min_listings)
    if not reqs:
        raise SubmitRefused(f"Nothing to send ({skipped} requests already answered).")
    if expected_fingerprint is not None and fingerprint(reqs) != expected_fingerprint:
        raise SubmitRefused("The requests changed since the estimate: estimate again.")
    est = ab.estimate(reqs, kind)
    if max_usd is not None and est["cost_usd_est"] > max_usd:
        raise SubmitRefused(f"Estimated US${est['cost_usd_est']} is above the confirmed US${max_usd}.")
    # the spending limit (KB_AI_BUDGET_USD per KB_AI_BUDGET_PERIOD, re-read from .env), for the
    # CLI and the website alike; the caller holds the writer lock, so submissions can't race it
    refusal = budget_status(conn).refusal(est["cost_usd_est"])
    if refusal:
        raise SubmitRefused(refusal)
    run_id = (submit_fn or ab.submit)(conn, reqs, kind, p["effort"], est)
    return CommandResult(f"Submitted ai_run {run_id}: {len(reqs)} requests, estimated US${est['cost_usd_est']}. "
                         f"Collect it when the batch ends (up to 24 h).",
                         {"params": p, "ai_run_id": run_id, "requests": len(reqs), "estimate": est})


def ai_collect(conn, run_id: Optional[int] = None) -> CommandResult:
    from . import ai_batch as ab
    stats = ab.collect(conn, run_id)
    if stats.get("status") and set(stats) <= {"status", "run"}:
        return CommandResult(f"Batch not finished yet: {stats['status']}" if stats.get("run")
                             else "No submitted run to collect.", stats)
    return CommandResult("Collected: " + ", ".join(f"{k}={v}" for k, v in stats.items())
                         + "\nNext: review the new cases.", stats)
