"""Stage 3: AI extraction/validation through the Message Batches API (50 % price).

    prepare  -> pick only what rules could not settle, skip anything already decided (memoized by
                hash), group by make, write data/ai/run_<id>.jsonl and pending ai_decision rows
    estimate -> messages.count_tokens on the prepared requests (free) + cost range
    submit   -> messages.batches.create (spends money: the CLI asks for --yes)
    status   -> messages.batches.retrieve
    ingest   -> stream results, validate (validate.py), apply accepted decisions, queue the rest
                for human review, record token usage and cost on ai_run

Nothing here sends a listing: requests carry unique model / model+trim strings with aggregated
evidence, so cost grows with new names, not with how many listings are scraped.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from . import schema as S
from .ai_prompt import MODEL, PROMPT_VERSION, render_user, request_params
from .build import ModelCluster, Resolution, trim_alias_norm
from .canonical import key
from .validate import apply_decision, validate_answer

MAX_LINES_PER_REQUEST = 120
EST_OUTPUT_TOKENS_PER_LINE = 90           # ~60 tokens of JSON + low-effort thinking
# USD per million tokens for claude-opus-5-5 with the Batch API's 50 % discount applied.
BATCH_PRICES = {"input": 2.0, "output": 10.0, "cache_read": 0.10, "cache_write_1h": 4.0}


def item_hash(kind: str, make_slug: str, natural: str) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}|{kind}|{make_slug}|{natural}".encode()).hexdigest()


def _years(ys) -> str:
    ys = sorted(y for y in ys if y)
    return f"{ys[0]}-{ys[-1]}" if ys else "-"


def _top(counter: Counter) -> Optional[Any]:
    return counter.most_common(1)[0][0] if counter else None


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
def _model_needs_ai(mc: ModelCluster) -> list[str]:
    flags = []
    if not mc.verified:
        flags.append("unverified")
    if mc.vehicle_class == "car" and not mc.bodies:
        flags.append("no_body")
    if len({t.lower() for t in mc.texts}) > 1:           # "Rav 4" vs "RAV4": which name is official?
        flags.append("spellings")
    return flags


def _trim_needs_ai(trim_text: str, model_unverified: bool) -> bool:
    return model_unverified or len(trim_text.split()) > 3 or "." in trim_text


@dataclass
class Prepared:
    run_id: Optional[int]
    requests: list[dict] = field(default_factory=list)          # {"custom_id", "params"}
    n_models: int = 0
    n_trims: int = 0
    skipped_memoized: int = 0
    path: Optional[Path] = None


def select_work(res: Resolution, decided: set[str], only_makes: Optional[set[str]] = None) -> dict:
    """make_slug -> {"make", "models": [...], "known": [...], "trims": [...]} of what to ask."""
    per_make: dict = defaultdict(lambda: {"models": [], "known": [], "trims": [], "skipped": 0})
    by_model_listings: dict = defaultdict(list)
    for rl in res.listings:
        by_model_listings[(rl.make.slug, rl.model_key)].append(rl)

    for (slug, mkey), mc in sorted(res.models.items(), key=lambda kv: (kv[0][0], -kv[1].n)):
        if only_makes and slug not in only_makes:
            continue
        w = per_make[slug]
        w["make"] = mc.make
        flags = _model_needs_ai(mc)
        h = item_hash("model", slug, mkey)
        lid = f"m{len(w['models']) + len(w['known']) + 1}"
        mc_line = {"id": lid, "name": mc.name, "spellings": "/".join(t for t, _ in mc.raw_models.most_common(6)),
                   "n": mc.n, "markets": ",".join(sorted({rl.country or "?" for rl in by_model_listings[(slug, mkey)]})),
                   "years": _years(mc.years), "body": _top(mc.bodies), "class": mc.vehicle_class,
                   "flags": ",".join(flags)}
        if flags and h not in decided:
            w["models"].append({"hash": h, "match_key": mkey, "line": mc_line})
        else:
            w["skipped"] += bool(flags)
            w["known"].append({"match_key": mkey, "line": mc_line})

        seen: dict[str, list] = defaultdict(list)
        for rl in by_model_listings[(slug, mkey)]:
            seen[trim_alias_norm(rl.row.get("model"), rl.row.get("trim"))].append(rl)
        for alias, rls in seen.items():
            rl0 = rls[0]
            if not rl0.row.get("trim") and not rl0.names.model_split and rl0.names.model_key == mkey:
                continue                              # the raw text is just the model name: nothing to decide
            if not _trim_needs_ai(rl0.trim_text, not mc.verified):
                continue
            h = item_hash("trim", slug, alias)        # raw text only: a later model merge doesn't re-ask it
            if h in decided:
                w["skipped"] += 1
                continue
            ev = {f: Counter(rl.row.get(f) for rl in rls if rl.row.get(f) is not None)
                  for f in ("engine_displacement_l", "fuel_type", "transmission_type", "body_style", "drivetrain")}
            w["trims"].append({"hash": h, "model_key": mkey, "alias_norm": alias,
                               "raw_model": rls[0].row.get("model"), "raw_trim": rls[0].row.get("trim"),
                               "line": {"id": None, "model": lid, "raw_model": rls[0].row.get("model"),
                                        "raw_trim": rls[0].row.get("trim"), "parsed_trim": rls[0].trim_text,
                                        "n": len(rls), "years": _years(rl.row.get("model_year") for rl in rls),
                                        "cc": _top(ev["engine_displacement_l"]), "fuel": _top(ev["fuel_type"]),
                                        "gear": _top(ev["transmission_type"]), "body": _top(ev["body_style"]),
                                        "drive": _top(ev["drivetrain"])}})
    return {s: w for s, w in per_make.items() if w["models"] or w["trims"]} | {
        "_skipped": sum(w["skipped"] for w in per_make.values())}


def _chunks(models: list, trims: list) -> Iterable[tuple[list, list]]:
    """First chunk carries the model decisions; trims spill over into more requests if needed."""
    room = max(MAX_LINES_PER_REQUEST - len(models), 20)
    yield models, trims[:room]
    for i in range(room, len(trims), MAX_LINES_PER_REQUEST):
        yield [], trims[i:i + MAX_LINES_PER_REQUEST]


def prepare(engine: Engine, res: Resolution, out_dir: Path, only_makes: Optional[set[str]] = None,
            max_requests: Optional[int] = None, record: bool = True) -> Prepared:
    S.create_all(engine)
    with engine.connect() as conn:
        decided = {h for (h,) in conn.execute(select(S.ai_decision.c.input_hash))}
    work = select_work(res, decided, only_makes)
    skipped = work.pop("_skipped")
    prep = Prepared(run_id=None, skipped_memoized=skipped)
    decisions: list[dict] = []
    now = datetime.now(timezone.utc)
    for slug, w in sorted(work.items()):
        asked_models = w["models"]
        for ci, (models, trims) in enumerate(_chunks(asked_models, w["trims"])):
            if max_requests is not None and len(prep.requests) >= max_requests:
                break
            custom_id = f"{slug}-{ci}"[:64]
            known = [(k["line"]["id"], k["line"]["name"]) for k in w["known"]]
            if ci > 0:                                   # later chunks: asked models are context only
                known += [(m["line"]["id"], m["line"]["name"]) for m in asked_models]
            for i, t in enumerate(trims, 1):
                t["line"]["id"] = f"t{i}"
            user = render_user(w["make"].name, [m["line"] for m in models], known, [t["line"] for t in trims])
            prep.requests.append({"custom_id": custom_id, "params": request_params(user)})
            model_ids = {m["line"]["id"]: m["match_key"] for m in [*asked_models, *w["known"]]}
            for m in models:
                decisions.append({"input_hash": m["hash"], "custom_id": custom_id, "item_kind": "model",
                                  "request": {"local_id": m["line"]["id"], "make_slug": slug, "match_key": m["match_key"],
                                              "line": m["line"], "model_ids": model_ids},
                                  "status": "pending", "created_at": now})
            for t in trims:
                decisions.append({"input_hash": t["hash"], "custom_id": custom_id, "item_kind": "trim",
                                  "request": {"local_id": t["line"]["id"], "make_slug": slug, "model_key": t["model_key"],
                                              "alias_norm": t["alias_norm"], "raw_model": t["raw_model"],
                                              "raw_trim": t["raw_trim"], "line": t["line"], "model_ids": model_ids},
                                  "status": "pending", "created_at": now})
            prep.n_models += len(models)
            prep.n_trims += len(trims)
    if not prep.requests or not record:
        return prep
    with engine.begin() as conn:
        prep.run_id = conn.execute(insert(S.ai_run).values(
            model=MODEL, prompt_version=PROMPT_VERSION, status="prepared", n_requests=len(prep.requests),
            created_at=now)).inserted_primary_key[0]
        for d in decisions:
            d["ai_run_id"] = prep.run_id
        for i in range(0, len(decisions), 500):
            conn.execute(insert(S.ai_decision), decisions[i:i + 500])
    out_dir.mkdir(parents=True, exist_ok=True)
    prep.path = out_dir / f"run_{prep.run_id}.jsonl"
    with prep.path.open("w", encoding="utf-8") as f:
        for r in prep.requests:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return prep


def load_requests(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Estimate / submit / status (these call the API)
# ---------------------------------------------------------------------------
def estimate(requests: list[dict], n_lines: int, client=None) -> dict:
    """Input tokens via messages.count_tokens (free) when a client is given, else ~4 chars/token."""
    if client is not None:
        counts = []
        for r in requests:
            p = {k: v for k, v in r["params"].items() if k != "max_tokens"}
            counts.append(client.messages.count_tokens(**p).input_tokens)
        system_tokens = client.messages.count_tokens(
            model=MODEL, system=requests[0]["params"]["system"],
            messages=[{"role": "user", "content": "x"}]).input_tokens if requests else 0
        method = "count_tokens"
    else:
        counts = [len(json.dumps(r["params"], ensure_ascii=False)) // 4 for r in requests]
        system_tokens = len(requests[0]["params"]["system"][0]["text"]) // 4 if requests else 0
        method = "approximate (~4 chars per token)"
    total_in = sum(counts)
    out = n_lines * EST_OUTPUT_TOKENS_PER_LINE
    p = BATCH_PRICES
    no_cache = (total_in * p["input"] + out * p["output"]) / 1e6
    cached_in = system_tokens * max(len(requests) - 1, 0)
    with_cache = ((total_in - cached_in - system_tokens) * p["input"] + system_tokens * p["cache_write_1h"]
                  + cached_in * p["cache_read"] + out * p["output"]) / 1e6
    return {"method": method, "requests": len(requests), "input_tokens": total_in, "system_tokens": system_tokens,
            "est_output_tokens": out, "usd_no_cache": round(no_cache, 4), "usd_with_cache": round(with_cache, 4)}


def _run(engine: Engine, run_id: Optional[int]):
    with engine.connect() as conn:
        q = select(S.ai_run).order_by(S.ai_run.c.id.desc())
        if run_id is not None:
            q = select(S.ai_run).where(S.ai_run.c.id == run_id)
        row = conn.execute(q).mappings().first()
    if row is None:
        raise SystemExit("No AI run found. Run `catalog ai-prepare` first.")
    return row


def submit(engine: Engine, client, out_dir: Path, run_id: Optional[int] = None) -> str:
    run = _run(engine, run_id)
    if run["batch_id"]:
        raise SystemExit(f"Run {run['id']} was already submitted as {run['batch_id']}.")
    batch = client.messages.batches.create(requests=load_requests(out_dir / f"run_{run['id']}.jsonl"))
    with engine.begin() as conn:
        conn.execute(update(S.ai_run).where(S.ai_run.c.id == run["id"]).values(batch_id=batch.id, status="submitted"))
    return batch.id


def status(engine: Engine, client, run_id: Optional[int] = None) -> dict:
    run = _run(engine, run_id)
    if not run["batch_id"]:
        return {"run": run["id"], "status": run["status"]}
    b = client.messages.batches.retrieve(run["batch_id"])
    rc = b.request_counts
    if b.processing_status == "ended" and run["status"] == "submitted":
        with engine.begin() as conn:
            conn.execute(update(S.ai_run).where(S.ai_run.c.id == run["id"]).values(status="ended"))
    return {"run": run["id"], "batch_id": b.id, "status": b.processing_status, "succeeded": rc.succeeded,
            "processing": rc.processing, "errored": rc.errored, "expired": rc.expired, "canceled": rc.canceled}


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
@dataclass
class IngestReport:
    accepted: int = 0
    review: int = 0
    rejected: int = 0
    requeued: int = 0                       # errored / expired / refused requests, asked again next prepare
    usage: Counter = field(default_factory=Counter)
    cost_usd: float = 0.0
    problems: list = field(default_factory=list)

    def text(self) -> str:
        u = self.usage
        return (f"Decisions: {self.accepted} accepted, {self.review} sent to review, {self.rejected} rejected, "
                f"{self.requeued} re-queued\nTokens: input {u['input_tokens']}, cache read {u['cache_read_input_tokens']}, "
                f"cache write {u['cache_creation_input_tokens']}, output {u['output_tokens']}\n"
                f"Cost (Batch prices): US${self.cost_usd:.4f}"
                + ("\nProblems:\n  " + "\n  ".join(self.problems[:20]) if self.problems else ""))


def ingest(engine: Engine, results: Iterable, run_id: int) -> IngestReport:
    """``results``: iterable of batch result objects (``client.messages.batches.results(id)``)."""
    rep = IngestReport()
    with engine.begin() as conn:
        pending = defaultdict(dict)
        for row in conn.execute(select(S.ai_decision).where(S.ai_decision.c.ai_run_id == run_id,
                                                            S.ai_decision.c.status == "pending")).mappings():
            pending[row["custom_id"]][row["request"]["local_id"]] = dict(row)
        for res in results:
            items = pending.get(res.custom_id, {})
            kind = res.result.type
            msg = getattr(res.result, "message", None)
            if msg is not None:
                for f in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                    rep.usage[f] += getattr(msg.usage, f, 0) or 0
            if kind != "succeeded" or msg is None or msg.stop_reason in ("refusal", "max_tokens"):
                why = kind if kind != "succeeded" else msg.stop_reason
                rep.problems.append(f"{res.custom_id}: {why} - {len(items)} items re-queued")
                rep.requeued += len(items)
                conn.execute(delete(S.ai_decision).where(S.ai_decision.c.ai_run_id == run_id,
                                                         S.ai_decision.c.custom_id == res.custom_id))
                continue
            text = next((b.text for b in msg.content if getattr(b, "type", "") == "text"), "")
            try:
                answer = json.loads(text)
            except json.JSONDecodeError as e:
                rep.problems.append(f"{res.custom_id}: invalid JSON ({e}) - items re-queued")
                rep.requeued += len(items)
                conn.execute(delete(S.ai_decision).where(S.ai_decision.c.ai_run_id == run_id,
                                                         S.ai_decision.c.custom_id == res.custom_id))
                continue
            answered = set()
            for d in validate_answer(answer, items):
                apply_decision(conn, d, method="ai")
                answered.add(d.local_id)
                setattr(rep, d.status, getattr(rep, d.status) + 1)
                if d.status == "rejected":
                    rep.problems.append(f"{res.custom_id}/{d.local_id}: {'; '.join(d.reasons)}")
            missing = [lid for lid in items if lid not in answered]
            if missing:   # the answer skipped some lines: ask again next time
                rep.requeued += len(missing)
                conn.execute(delete(S.ai_decision).where(S.ai_decision.c.input_hash.in_(
                    [items[lid]["input_hash"] for lid in missing])))
        p, u = BATCH_PRICES, rep.usage
        rep.cost_usd = (u["input_tokens"] * p["input"] + u["output_tokens"] * p["output"]
                        + u["cache_read_input_tokens"] * p["cache_read"]
                        + u["cache_creation_input_tokens"] * p["cache_write_1h"]) / 1e6
        conn.execute(update(S.ai_run).where(S.ai_run.c.id == run_id).values(
            status="ingested", ended_at=datetime.now(timezone.utc), input_tokens=u["input_tokens"],
            output_tokens=u["output_tokens"], cache_read_tokens=u["cache_read_input_tokens"],
            cache_write_tokens=u["cache_creation_input_tokens"], cost_usd=round(rep.cost_usd, 6)))
    return rep
