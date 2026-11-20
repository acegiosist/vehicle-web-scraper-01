"""`kb review worker`: applies the decisions the review website queues in ``kb.review_decision``.

The website never changes the knowledge base itself: it only INSERTs a decision. This worker
applies each one with ``review.decide_item`` (the same code as `kb review import`), so merges,
aliases, unit conversion and sample batches behave exactly as with the CSV.

* An AFTER INSERT trigger NOTIFYs ``kb_review_decision``: a decision is applied within a second.
  The queue is also polled, so a missed notification only delays it.
* Each decision runs in its own savepoint: one that fails is marked ``failed`` with the error
  and the rest go on. A case that is no longer pending is marked ``superseded``.
* Every cycle holds the writer lock (db.writer_lock), so it never runs at the same time as
  `kb normalize`, `kb consolidate` or `kb review import`.
* After ``propagate_idle`` seconds with no new decisions it runs normalize + consolidate, so the
  next level of cases appears (models once their make is decided, and so on).
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Optional

import psycopg

from .db import connect, database_url, writer_lock
from .review import close_sample_batches, create_sample_batches, decide_item

CHANNEL = "kb_review_decision"
log = logging.getLogger("vehicle_scraper.kb.worker")

# decide_item outcome -> review_decision.status (and the error shown on the website)
OUTCOMES = {
    "approved": ("applied", None),
    "rejected": ("applied", None),
    "corrected": ("applied", None),
    "already_decided_or_missing": ("superseded", "El caso ya estaba decidido o ya no existe."),
    "correct_without_value": ("failed", "Falta el valor corregido."),
    "invalid_value": ("failed", "El valor corregido no es válido para este campo (tipo o rango)."),
}


@dataclass
class WorkerSettings:
    propagate_idle: float = 120.0   # seconds without decisions before normalize + consolidate; 0 = never
    poll: float = 30.0              # max seconds between queue checks
    sample_every: float = 300.0     # seconds between create_sample_batches runs
    sample_size: int = 50
    seed: int = 20261120
    min_accuracy: float = 0.95
    min_confidence: float = 0.8


def process_queue(conn) -> Counter:
    """Apply every queued decision, oldest first. The caller holds the writer lock."""
    stats: Counter = Counter()
    rows = conn.execute("SELECT * FROM kb.review_decision WHERE status = 'queued' ORDER BY id FOR UPDATE").fetchall()
    last_reviewer: Optional[str] = None
    for d in rows:
        try:
            with conn.transaction():
                outcome = decide_item(conn, d["review_item_id"], d["decision"], d["corrected_value"], d["note"],
                                      d["reviewer"])
            status, error = OUTCOMES.get(outcome, ("failed", outcome))
        except Exception as exc:        # noqa: BLE001 - recorded on the decision, the rest go on
            log.exception("decision %s failed", d["id"])
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        conn.execute("UPDATE kb.review_decision SET status = %s, error = %s, processed_at = now() WHERE id = %s",
                     (status, error, d["id"]))
        stats[status] += 1
        if status == "applied":
            last_reviewer = d["reviewer"]
    if last_reviewer:
        stats.update(close_sample_batches(conn, last_reviewer))
    return stats


def propagate(conn) -> str:
    from .consensus import consolidate
    from .identity import normalize
    started = time.monotonic()
    n = normalize(conn)
    c = consolidate(conn)
    return (f"propagated in {time.monotonic() - started:.0f}s: normalize {n.review_items} new cases; "
            f"consolidate {c.variants} variants, {c.changes} field changes")


def _cycle(url: str, work: Callable) -> object:
    with connect(url) as conn:
        writer_lock(conn)
        return work(conn)


def run_worker(url: Optional[str] = None, cfg: WorkerSettings = WorkerSettings(), once: bool = False) -> int:
    """Run until interrupted (or one pass with ``once``: apply the queue, propagate if anything
    was applied, exit)."""
    url = database_url(url)
    sample = lambda conn: create_sample_batches(conn, cfg.sample_size, cfg.seed, cfg.min_accuracy,  # noqa: E731
                                                cfg.min_confidence)
    created = _cycle(url, sample)
    if created:
        log.info("created %s sample batch(es)", created)
    if once:
        stats = _cycle(url, process_queue)
        log.info("queue: %s", dict(stats) or "empty")
        if stats.get("applied") and cfg.propagate_idle > 0:
            log.info(_cycle(url, propagate))
        return 0

    listener = psycopg.connect(url, autocommit=True)
    listener.execute(f"LISTEN {CHANNEL}")
    log.info("listening on %s (propagate after %ss idle)", CHANNEL, cfg.propagate_idle)
    dirty, last_applied, last_sample = False, 0.0, time.monotonic()
    try:
        while True:
            stats = _cycle(url, process_queue)
            if stats:
                log.info("queue: %s", dict(stats))
            if stats.get("applied"):
                dirty, last_applied = True, time.monotonic()
            now = time.monotonic()
            if dirty and cfg.propagate_idle > 0 and now - last_applied >= cfg.propagate_idle:
                log.info(_cycle(url, propagate))
                dirty = False
            if now - last_sample >= cfg.sample_every:
                if _cycle(url, sample):
                    log.info("created sample batch(es)")
                last_sample = now
            wait = cfg.poll
            if dirty and cfg.propagate_idle > 0:
                wait = max(0.5, min(wait, cfg.propagate_idle - (time.monotonic() - last_applied)))
            for _ in listener.notifies(timeout=wait, stop_after=1):
                pass
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        listener.close()
    return 0
