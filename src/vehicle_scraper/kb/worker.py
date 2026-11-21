"""`kb worker` (alias `kb review worker`): does what the review website queues.

The website never changes the knowledge base itself and never runs processes: it only INSERTs
rows. This worker carries them out with the CLI's own code.

* **Decisions** (``kb.review_decision``) are applied with ``review.decide_item`` (the same code as
  `kb review import`), each in its own savepoint: ``applied``, ``failed`` with the error, or
  ``superseded`` when the case is no longer pending.
* **Jobs** (``kb.job``, migration 0003) run ``kb/commands.py``: normalize, consolidate,
  recalculate, export (the file goes to ``kb.job_file``), AI estimate / collect / submit. One job
  at a time, oldest first; queued decisions are applied before each job. A job's changes and its
  ``done`` status commit together; on an error everything rolls back and the job is ``failed``.
* AFTER INSERT triggers NOTIFY ``kb_review_decision`` and ``kb_job``; the queues are also polled,
  so a missed notification only delays the work.
* Every cycle holds the writer lock (db.writer_lock): never at the same time as a `kb` command.
* After ``propagate_idle`` seconds with no new decisions it runs normalize + consolidate, so the
  next level of cases appears (models once their make is decided, and so on).
* Sending a batch to Claude (``ai_submit``) costs money. The worker refuses it unless
  ``KB_ALLOW_WEB_AI_SUBMIT=true`` (re-read from .env on every submission, so no restart is
  needed to switch it on or off), the job points to an estimate
  finished less than an hour ago, the requests are still exactly the ones estimated
  (fingerprint), the confirmed amount covers the estimate, and it fits the AI budget
  (``KB_AI_BUDGET_USD`` per ``KB_AI_BUDGET_PERIOD``, see budget.py, checked in commands.ai_submit).
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Optional

import psycopg
from . import commands, settings
from .commands import CommandResult, SubmitRefused
from .db import connect, database_url, jsonb, writer_lock
from .review import close_sample_batches, create_sample_batches, decide_item

CHANNEL = "kb_review_decision"
JOB_CHANNEL = "kb_job"
log = logging.getLogger("vehicle_scraper.kb.worker")

ESTIMATE_MAX_AGE_MIN = 60
KEEP_FILES = 10
AI_SUBMIT_ENV = "KB_ALLOW_WEB_AI_SUBMIT"   # read from the .env in settings.ENV_FILE
# Replaced in tests by a fake that records the submission instead of calling the API.
_submit_fn: Optional[Callable] = None

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


# --- decisions -------------------------------------------------------------------------------------
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
    started = time.monotonic()
    r = commands.run_recalculate(conn)
    return (f"propagated in {time.monotonic() - started:.0f}s: normalize {r.result['normalize']['review_items']} "
            f"new cases; consolidate {r.result['consolidate']['variants']} variants, "
            f"{r.result['consolidate']['changes']} field changes")


# --- jobs ----------------------------------------------------------------------------------------------
class JobError(ValueError):
    """A job that cannot run as asked (bad parameters, a refused AI submission)."""


def _int(p: dict, key: str, lo: int, hi: int, default: Optional[int] = None) -> Optional[int]:
    v = p.get(key, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise JobError(f"{key} must be an integer between {lo} and {hi}")
    return v


def _num(p: dict, key: str, lo: float, hi: float, default: float) -> float:
    v = p.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise JobError(f"{key} must be a number between {lo} and {hi}")
    return float(v)


def _makes(p: dict) -> Optional[list[str]]:
    v = p.get("makes")
    if v is None:
        return None
    if not isinstance(v, list) or len(v) > 50 or not all(isinstance(m, str) and 0 < len(m) <= 60 for m in v):
        raise JobError("makes must be a list of up to 50 names")
    return v


def ai_submit_allowed() -> bool:
    """Re-read from .env on every check (settings.env_flag), so switching it on or off takes
    effect without restarting the worker."""
    return settings.env_flag(AI_SUBMIT_ENV)


def _ai_submit(conn, p: dict) -> CommandResult:
    if not ai_submit_allowed():
        raise JobError(f"Enviar a Claude desde el sitio está deshabilitado: falta {AI_SUBMIT_ENV}=true en el worker.")
    est_id = _int(p, "estimate_job_id", 1, 2**62)
    confirm = _num(p, "confirm_usd", 0, 100_000, -1)
    est = conn.execute(
        """SELECT * FROM kb.job WHERE id = %s AND command = 'ai_estimate' AND status = 'done'
           AND finished_at > now() - make_interval(mins => %s)""", (est_id, ESTIMATE_MAX_AGE_MIN)).fetchone()
    if not est:
        raise JobError(f"El estimado {est_id} no existe, no terminó o tiene más de {ESTIMATE_MAX_AGE_MIN} minutos: "
                       "estima de nuevo.")
    r = est["result"] or {}
    if not r.get("requests"):
        raise JobError("El estimado no tiene nada que enviar.")
    cost = r["estimate"]["cost_usd_est"]
    if confirm < cost:
        raise JobError(f"El monto confirmado (US${confirm}) es menor que el estimado (US${cost}).")
    q = r["params"]
    try:
        return commands.ai_submit(conn, q["kind"], q["effort"], q["makes"], q["limit"], q["min_listings"] or 3,
                                  expected_fingerprint=r["fingerprint"], max_usd=confirm, submit_fn=_submit_fn)
    except SubmitRefused as exc:
        raise JobError(str(exc)) from exc


def execute_job(conn, job: dict) -> CommandResult:
    """Run one job with validated parameters (the site validated them too; never trust it)."""
    p, cmd = job["params"] or {}, job["command"]
    if cmd == "normalize":
        return commands.run_normalize(conn)
    if cmd in ("consolidate", "recalculate"):
        args = (_int(p, "min_support", 1, 20, 2), _num(p, "min_agreement", 0.5, 1.0, 0.7))
        return commands.run_consolidate(conn, *args) if cmd == "consolidate" else commands.run_recalculate(conn, *args)
    if cmd == "export":
        fmt = p.get("format", "csv")
        if fmt not in commands.EXPORT_TYPES:
            raise JobError("format must be csv, xlsx or json")
        return commands.run_export(conn, fmt, p.get("with_sources") is True)
    if cmd == "ai_estimate":
        kind, effort = p.get("kind"), p.get("effort")
        if kind not in ("identity", "specs") or effort not in (None, "low", "medium", "high"):
            raise JobError("kind must be identity or specs; effort low, medium or high")
        return commands.ai_estimate(conn, kind, effort, _makes(p), _int(p, "limit", 1, 10_000),
                                    _int(p, "min_listings", 1, 1000, 3), p.get("count_tokens") is True)
    if cmd == "ai_collect":
        return commands.ai_collect(conn, _int(p, "run_id", 1, 2**62))
    if cmd == "ai_submit":
        return _ai_submit(conn, p)
    raise JobError(f"unknown command {cmd}")


def fail_stale_jobs(conn) -> int:
    """Jobs left 'running' by a worker that stopped: their transaction never committed."""
    return conn.execute("""UPDATE kb.job SET status = 'failed', finished_at = now(),
                           error = 'El worker se detuvo mientras corría la tarea; no se aplicó nada.'
                           WHERE status = 'running'""").rowcount


def _claim(url: str) -> Optional[dict]:
    with connect(url) as conn:     # committed right away, so the site shows "running"
        return conn.execute(
            """UPDATE kb.job SET status = 'running', started_at = now()
               WHERE id = (SELECT id FROM kb.job WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED)
               RETURNING *""").fetchone()


def run_next_job(url: str) -> Optional[tuple[dict, str]]:
    """Claim and run the oldest queued job. Returns (job, final status) or None if none."""
    job = _claim(url)
    if not job:
        return None
    started = time.monotonic()
    try:
        with connect(url) as conn:
            writer_lock(conn)
            res = execute_job(conn, job)
            conn.execute("""UPDATE kb.job SET status = 'done', summary = %s, result = %s, finished_at = now()
                            WHERE id = %s""", (res.summary, jsonb(res.result), job["id"]))
            if res.file:
                f = res.file
                conn.execute("""INSERT INTO kb.job_file (job_id, filename, content_type, gzipped, size, bytes)
                                VALUES (%s, %s, %s, %s, %s, %s)""",
                             (job["id"], f.filename, f.content_type, f.gzipped, f.size, f.data))
                conn.execute("""DELETE FROM kb.job_file WHERE job_id NOT IN
                                (SELECT job_id FROM kb.job_file ORDER BY job_id DESC LIMIT %s)""", (KEEP_FILES,))
        status = "done"
        log.info("job %s %s done in %.0fs", job["id"], job["command"], time.monotonic() - started)
    except Exception as exc:        # noqa: BLE001 - recorded on the job; the worker goes on
        if not isinstance(exc, JobError):
            log.exception("job %s %s failed", job["id"], job["command"])
        error = str(exc) if isinstance(exc, JobError) else f"{type(exc).__name__}: {exc}"
        with connect(url) as conn:
            conn.execute("UPDATE kb.job SET status = 'failed', error = %s, finished_at = now() WHERE id = %s",
                         (error[:2000], job["id"]))
        status = "failed"
    return job, status


# --- loop ----------------------------------------------------------------------------------------------
def _cycle(url: str, work: Callable) -> object:
    with connect(url) as conn:
        writer_lock(conn)
        return work(conn)


def run_worker(url: Optional[str] = None, cfg: WorkerSettings = WorkerSettings(), once: bool = False) -> int:
    """Run until interrupted (or one pass with ``once``: apply decisions, run queued jobs,
    propagate if a decision was applied, exit)."""
    url = database_url(url)
    sample = lambda conn: create_sample_batches(conn, cfg.sample_size, cfg.seed, cfg.min_accuracy,  # noqa: E731
                                                cfg.min_confidence)
    stale = _cycle(url, fail_stale_jobs)
    if stale:
        log.warning("marked %s interrupted job(s) as failed", stale)
    if _cycle(url, sample):
        log.info("created sample batch(es)")

    def drain(dirty: bool) -> tuple[bool, float]:
        """Decisions first, then one job at a time (decisions again before each)."""
        last = 0.0
        while True:
            stats = _cycle(url, process_queue)
            if stats:
                log.info("queue: %s", dict(stats))
            if stats.get("applied"):
                dirty, last = True, time.monotonic()
            ran = run_next_job(url)
            if not ran:
                return dirty, last
            job, status = ran
            if status == "done" and job["command"] == "recalculate":
                dirty = False                   # just propagated
            if status == "done" and job["command"] == "ai_collect":
                _cycle(url, sample)

    if once:
        dirty, _ = drain(False)
        if dirty and cfg.propagate_idle > 0:
            log.info(_cycle(url, propagate))
        return 0

    listener = psycopg.connect(url, autocommit=True)
    listener.execute(f"LISTEN {CHANNEL}")
    listener.execute(f"LISTEN {JOB_CHANNEL}")
    log.info("listening on %s, %s (propagate after %ss idle; AI submit from the site %s)", CHANNEL, JOB_CHANNEL,
             cfg.propagate_idle, "ENABLED" if ai_submit_allowed() else "disabled")
    dirty, last_applied, last_sample = False, 0.0, time.monotonic()
    try:
        while True:
            dirty, last = drain(dirty)
            if last:
                last_applied = last
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
