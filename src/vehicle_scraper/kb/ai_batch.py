"""`kb ai-identity` / `kb ai-specs`: Claude Opus 5.5 through the Message Batches API.

* Only text from sites with ``kb.source_site.ai_allowed`` is ever sent (Cofino is not).
* ``--estimate`` builds the requests and prices them; nothing leaves the machine unless an
  API credential is present (then ``count_tokens`` is used, which is free).
* ``--submit`` spends money and refuses to run without ``--confirm``.
* Requests are memoized by ``input_hash``: one already answered is never sent again.
* Nothing the AI says is accepted on its own: identity proposals and AI spec values go to
  ``kb.review_item`` (individual or sampled, see review.py).
"""
from __future__ import annotations

import json
import logging
import math
import time
from collections import Counter, defaultdict
from typing import Optional

from .. import mapping as M
from .db import jsonb
from .fields import CRITICAL_FIELDS, EQUIP_FIELDS, MECH_FIELDS, coerce
from .identity import open_review, similar, split_trim
from .prompts import identity_user, input_hash, request_params, specs_user

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
# Message Batches = 50 % of standard Opus 5.5 prices ($4 / $20 per MTok).
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ = 2.0 / 1e6, 10.0 / 1e6, 0.10 / 1e6
MODELS_PER_REQUEST = 120
VARIANTS_PER_REQUEST = 10
MIN_AI_CONFIDENCE = 0.6
COUNTRY_NAMES = {"CO": "Colombia", "GT": "Guatemala", "IN": "India", "CL": "Chile", "US": "Estados Unidos"}


# --- building requests -------------------------------------------------------------------------
def _ai_sites(conn) -> list[str]:
    return [r["site"] for r in conn.execute("SELECT site FROM kb.source_site WHERE ai_allowed ORDER BY site")]


def identity_requests(conn, makes_filter: Optional[set[str]] = None) -> list[dict]:
    """One request per make (chunked) with the unresolved models/make, built only from
    listings of AI-allowed sites."""
    sites = _ai_sites(conn)
    rows = conn.execute(
        """SELECT mk.id AS make_id, mk.name AS make, mk.status AS make_status, md.id AS model_id,
                  md.status AS model_status, l.raw_model, l.raw_trim, l.raw_year, l.source_site
           FROM kb.listing l JOIN kb.make mk ON mk.id = l.make_id LEFT JOIN kb.model md ON md.id = l.model_id
           WHERE l.source_site = ANY(%s) AND (mk.status = 'unresolved' OR md.status = 'unresolved')""",
        (sites,)).fetchall()
    by_make: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        if makes_filter and r["make"].lower() not in makes_filter:
            continue
        by_make[r["make_id"]].append(r)
    out = []
    for make_id, rs in sorted(by_make.items()):
        models: dict[int, dict] = {}
        trims: Counter = Counter()
        for r in rs:
            if r["model_id"] is None:
                continue
            m = models.setdefault(r["model_id"], {"id": r["model_id"], "spellings": set(), "n": 0, "years": [],
                                                  "sites": set()})
            m["spellings"].add(r["raw_model"])
            m["n"] += 1
            m["sites"].add(r["source_site"])
            if r["raw_year"]:
                m["years"].append(r["raw_year"])
            if r["raw_trim"] and split_trim(r["raw_trim"]):
                trims[(r["model_id"], r["raw_trim"])] += 1
        for m in models.values():
            m["years"] = [min(m["years"]), max(m["years"])] if m["years"] else None
        known = [dict(id=k["id"], name=k["name"]) for k in conn.execute(
            "SELECT id, name FROM kb.model WHERE make_id = %s AND status = 'accepted' AND merged_into IS NULL", (make_id,))]
        unresolved_make = rs[0]["make_status"] == "unresolved"
        model_list = sorted(models.values(), key=lambda m: m["id"])
        chunks = [model_list[i:i + MODELS_PER_REQUEST] for i in range(0, len(model_list), MODELS_PER_REQUEST)] or [[]]
        for n, chunk in enumerate(chunks):
            ids = {m["id"] for m in chunk}
            trim_rows = [{"id": i, "model_id": mid, "raw": raw, "n": cnt}
                         for i, ((mid, raw), cnt) in enumerate(sorted(trims.items())) if mid in ids][:400]
            user = identity_user({"name": rs[0]["make"], "unresolved": unresolved_make and n == 0},
                                 chunk, known, trim_rows)
            out.append({"custom_id": f"identity-m{make_id}-{n}", "kind": "identity", "make_id": make_id,
                        "user": user, "meta": {"make_id": make_id, "make_unresolved": unresolved_make and n == 0,
                                               "models": sorted(ids), "trims": trim_rows}})
    return out


def specs_requests(conn, min_listings: int, makes_filter: Optional[set[str]] = None) -> list[dict]:
    sites = _ai_sites(conn)
    variants = conn.execute(
        """SELECT v.*, md.name AS model, mk.name AS make, md.vehicle_class, t.name AS trim, vm.country,
                  vm.listings_seen
           FROM kb.variant v JOIN kb.model md ON md.id = v.model_id JOIN kb.make mk ON mk.id = md.make_id
           LEFT JOIN kb.trim t ON t.id = v.trim_id
           JOIN kb.variant_market vm ON vm.variant_id = v.id
           WHERE v.status = 'accepted' AND md.status = 'accepted' AND mk.status = 'accepted'
             AND vm.listings_seen >= %s
             AND EXISTS (SELECT 1 FROM kb.listing l WHERE l.variant_id = v.id AND l.country = vm.country
                         AND l.source_site = ANY(%s))
           ORDER BY mk.name, md.name, vm.country, v.id""", (min_listings, sites)).fetchall()
    if makes_filter:
        variants = [v for v in variants if v["make"].lower() in makes_filter]
    vids = list({v["id"] for v in variants})
    mech = {r["variant_id"]: r for r in conn.execute("SELECT * FROM kb.variant_spec WHERE variant_id = ANY(%s)", (vids,))}
    equip = {(r["variant_id"], r["country"]): r for r in conn.execute(
        "SELECT * FROM kb.variant_market_spec WHERE variant_id = ANY(%s)", (vids,))}
    src = {(r["variant_id"], r["country"], r["field"]): r["source_kind"] for r in conn.execute(
        "SELECT variant_id, country, field, source_kind FROM kb.spec_evidence WHERE variant_id = ANY(%s) "
        "AND status IN ('accepted', 'accepted_sampled')", (vids,))}
    pending = {(r["variant_id"], r["country"], r["field"]) for r in conn.execute(
        "SELECT variant_id, country, field FROM kb.spec_evidence WHERE variant_id = ANY(%s) AND status = 'pending_review'",
        (vids,))}
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for v in variants:
        known, missing = {}, []
        m, e = mech.get(v["id"]) or {}, equip.get((v["id"], v["country"])) or {}
        for f in MECH_FIELDS:
            if m.get(f) is not None:
                known[f] = (m[f], src.get((v["id"], "", f), "kb"))
            elif (v["id"], "", f) not in pending and not (v["vehicle_class"] == "motorcycle" and f in ("doors", "cargo_capacity_l")):
                missing.append(f)
        for f in EQUIP_FIELDS:
            if e.get(f) is not None:
                known[f] = (e[f], src.get((v["id"], v["country"], f), "kb"))
            elif (v["id"], v["country"], f) not in pending:
                missing.append(f)
        if missing:
            groups[(v["make"], v["model"], v["country"])].append({
                "id": v["id"], "trim": v["trim"], "year": v["model_year"],
                "displacement_l": float(v["engine_displacement_l"]) if v["engine_displacement_l"] is not None else None,
                "fuel_type": v["fuel_type"], "transmission_type": v["transmission_type"],
                "drivetrain": v["drivetrain"], "known": known, "missing": missing,
                "vehicle_class": v["vehicle_class"]})
    out = []
    for (make, model, country), vs in sorted(groups.items()):
        for n in range(0, len(vs), VARIANTS_PER_REQUEST):
            chunk = vs[n:n + VARIANTS_PER_REQUEST]
            user = specs_user(make, model, COUNTRY_NAMES.get(country, country), chunk)
            out.append({"custom_id": f"specs-{chunk[0]['id']}-{country}", "kind": "specs", "user": user,
                        "meta": {"country": country, "variants": {str(v["id"]): {"missing": v["missing"],
                                                                                 "vehicle_class": v["vehicle_class"]}
                                                                  for v in chunk}}})
    return out


def _with_params(reqs: list[dict], kind: str, effort: str) -> list[dict]:
    for r in reqs:
        r["params"] = request_params(kind, r["user"], effort, MODEL)
        r["hash"] = input_hash(r["params"])
    return reqs


def _drop_answered(conn, reqs: list[dict]) -> tuple[list[dict], int]:
    answered = {r["input_hash"] for r in conn.execute(
        "SELECT input_hash FROM kb.ai_decision WHERE result_type = 'succeeded' AND input_hash = ANY(%s)",
        ([r["hash"] for r in reqs],))}
    return [r for r in reqs if r["hash"] not in answered], len(answered)


# --- estimate -------------------------------------------------------------------------------------
def estimate(reqs: list[dict], kind: str, count_tokens: bool = False) -> dict:
    """Token and cost estimate: ~3.5 characters per token (Spanish/TSV) by default, which
    sends nothing anywhere. With ``count_tokens`` the free count_tokens endpoint is used,
    which DOES send the request text to the API (no charge)."""
    method = "approx (3.5 chars/token)"
    inputs = [math.ceil((len(r["params"]["system"][0]["text"]) + len(r["user"])) / 3.5) + 400 for r in reqs]
    if count_tokens:
        import anthropic
        client = anthropic.Anthropic()
        inputs = [client.messages.count_tokens(model=r["params"]["model"], system=r["params"]["system"],
                                               messages=r["params"]["messages"]).input_tokens for r in reqs]
        method = "count_tokens"
    system_tokens = math.ceil(len(reqs[0]["params"]["system"][0]["text"]) / 3.5) if reqs else 0
    if kind == "identity":
        out_tokens = [60 * len(r["meta"]["models"]) + 20 * len(r["meta"]["trims"]) + 200 for r in reqs]
    else:
        out_tokens = [sum(len(v["missing"]) for v in r["meta"]["variants"].values()) * 14 + 150 for r in reqs]
    thinking = [o for o in out_tokens]           # adaptive thinking: assume as much again
    tin, tout = sum(inputs), sum(out_tokens) + sum(thinking)
    cached = system_tokens * max(0, len(reqs) - 1)
    cost = (tin - cached) * PRICE_IN + cached * PRICE_CACHE_READ + tout * PRICE_OUT
    return {"requests": len(reqs), "input_tokens": tin, "output_tokens_est": tout, "method": method,
            "cost_usd_est": round(cost, 2), "cost_usd_range": [round(cost * 0.6, 2), round(cost * 1.8, 2)]}


# --- submit / collect -------------------------------------------------------------------------------
def submit(conn, reqs: list[dict], kind: str, effort: str, est: dict) -> int:
    import anthropic
    from anthropic.types.messages.batch_create_params import Request
    client = anthropic.Anthropic()
    batch = client.messages.batches.create(requests=[Request(custom_id=r["custom_id"], params=r["params"]) for r in reqs])
    return record_submission(conn, reqs, kind, effort, est, batch.id)


def record_submission(conn, reqs: list[dict], kind: str, effort: str, est: dict, batch_id: str) -> int:
    run_id = conn.execute(
        """INSERT INTO kb.ai_run (kind, batch_id, model, effort, status, request_count, submitted_at, est_cost_usd)
           VALUES (%s, %s, %s, %s, 'submitted', %s, now(), %s) RETURNING id""",
        (kind, batch_id, MODEL, effort, len(reqs), est["cost_usd_est"])).fetchone()["id"]
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO kb.ai_decision (ai_run_id, custom_id, input_hash, request)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (input_hash) DO UPDATE SET ai_run_id = EXCLUDED.ai_run_id, custom_id = EXCLUDED.custom_id,
                   response = NULL, result_type = NULL, stop_reason = NULL, applied = false""",
            [(run_id, r["custom_id"], r["hash"], jsonb({"params": r["params"], "meta": r["meta"]})) for r in reqs])
    return run_id


def parse_message(message) -> tuple[Optional[dict], Optional[str]]:
    """(json, stop_reason) from a batch result message (SDK object or dict)."""
    d = message if isinstance(message, dict) else message.model_dump()
    stop = d.get("stop_reason")
    if stop == "refusal":
        return None, stop
    text = next((b["text"] for b in d.get("content", []) if b.get("type") == "text"), None)
    try:
        return (json.loads(text) if text else None), stop
    except json.JSONDecodeError:
        return None, stop


def collect(conn, run_id: Optional[int], wait: bool = False) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    run = conn.execute("SELECT * FROM kb.ai_run WHERE " + ("id = %s" if run_id else "status = 'submitted' ORDER BY id DESC LIMIT 1"),
                       (run_id,) if run_id else ()).fetchone()
    if not run:
        return {"status": "no submitted run"}
    batch = client.messages.batches.retrieve(run["batch_id"])
    while wait and batch.processing_status != "ended":
        time.sleep(60)
        batch = client.messages.batches.retrieve(run["batch_id"])
    if batch.processing_status != "ended":
        return {"status": batch.processing_status, "run": run["id"]}
    results = []
    for res in client.messages.batches.results(run["batch_id"]):
        msg = res.result.message.model_dump() if res.result.type == "succeeded" else None
        results.append({"custom_id": res.custom_id, "type": res.result.type, "message": msg})
    return store_and_apply(conn, run, results)


def store_and_apply(conn, run: dict, results: list[dict]) -> dict:
    """Store each result (keyed by custom_id: batch results arrive in any order) and apply."""
    stats = Counter()
    tin = tout = tcache = 0
    for res in results:
        dec = conn.execute("SELECT * FROM kb.ai_decision WHERE ai_run_id = %s AND custom_id = %s",
                           (run["id"], res["custom_id"])).fetchone()
        if not dec:
            stats["unknown_custom_id"] += 1
            continue
        data, stop = parse_message(res["message"]) if res["message"] else (None, None)
        if res["message"]:
            u = res["message"].get("usage") or {}
            tin += u.get("input_tokens") or 0
            tout += u.get("output_tokens") or 0
            tcache += u.get("cache_read_input_tokens") or 0
        result_type = res["type"] if (res["type"] != "succeeded" or data is not None) else "unparseable"
        conn.execute("UPDATE kb.ai_decision SET response = %s, result_type = %s, stop_reason = %s WHERE id = %s",
                     (jsonb(data) if data is not None else None, result_type, stop, dec["id"]))
        stats[result_type if stop != "refusal" else "refusal"] += 1
        if data is not None:
            meta = dec["request"]["meta"]
            (apply_identity if run["kind"] == "identity" else apply_specs)(conn, dec["id"], meta, data, stats)
            conn.execute("UPDATE kb.ai_decision SET applied = true WHERE id = %s", (dec["id"],))
    conn.execute("""UPDATE kb.ai_run SET status = 'applied', ended_at = now(), input_tokens = %s, output_tokens = %s,
                    cache_read_tokens = %s WHERE id = %s""", (tin, tout, tcache, run["id"]))
    return dict(stats)


# --- applying results (everything becomes a review case) -------------------------------------
def apply_identity(conn, decision_id: int, meta: dict, data: dict, stats: Counter) -> None:
    make_id = meta["make_id"]
    mk = data.get("make")
    if meta.get("make_unresolved") and mk:
        open_review(conn, level=1, entity_type="make", entity_id=make_id, issue="unresolved_make", source="ai",
                    kind="individual", proposed=mk, ai_decision_id=decision_id)
        stats["make_proposals"] += 1
    allowed = set(meta["models"])
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM kb.model WHERE make_id = %s", (make_id,))}
    for m in data.get("models") or []:
        mid = m.get("id")
        if mid not in allowed:
            stats["ignored_unknown_id"] += 1
            continue
        target = m.get("merge_into_id")
        # Individual: changes what the model IS. Sampled: only spelling / attributes in the name.
        drastic = (not m.get("is_real_model", True) or m.get("wrong_make") or m.get("status") == "unsure"
                   or (target and target in names and not similar(names.get(mid, ""), names[target])))
        open_review(conn, level=2, entity_type="model", entity_id=mid, issue="unresolved_model", source="ai",
                    kind="individual" if drastic else "sample", proposed=m, ai_decision_id=decision_id)
        stats["model_individual" if drastic else "model_sample"] += 1
    trims = {t["id"]: t for t in meta.get("trims") or []}
    for t in data.get("trims") or []:
        if t.get("id") in trims and t.get("canonical_trim"):
            stats["trim_suggestions"] += 1     # informational: stored with the decision, applied on review
    conn.execute("UPDATE kb.ai_decision SET response = response || %s WHERE id = %s",
                 (jsonb({"_trim_rows": list(trims.values())}), decision_id))


def apply_specs(conn, decision_id: int, meta: dict, data: dict, stats: Counter) -> None:
    country = meta["country"]
    for v in data.get("variants") or []:
        vmeta = meta["variants"].get(str(v.get("id")))
        if not vmeta:
            stats["ignored_unknown_id"] += 1
            continue
        vid = int(v["id"])
        moto = vmeta["vehicle_class"] == "motorcycle"
        for item in v.get("values") or []:
            f, raw, conf = item.get("field"), item.get("value"), item.get("confidence") or 0
            if f not in vmeta["missing"] or conf < MIN_AI_CONFIDENCE:
                stats["skipped_low_confidence_or_not_asked"] += 1
                continue
            conv = (moto and M.MOTO_CONVERTERS.get(f)) or M.CONVERTERS.get(f)
            value = coerce(f, conv(raw, f) if conv else raw)    # same unit parsing as the scraper
            if value is None:
                stats["unparseable_value"] += 1
                continue
            cc = "" if f in MECH_FIELDS else country
            ev = conn.execute(
                """INSERT INTO kb.spec_evidence (variant_id, country, field, value, source_kind, confidence, status,
                                                 sites, ai_decision_id, origin_key)
                   VALUES (%s, %s, %s, %s, 'ai_knowledge', %s, 'pending_review', '{}', %s, %s)
                   ON CONFLICT (variant_id, country, field, source_kind, origin_key) DO UPDATE SET
                       value = EXCLUDED.value, confidence = EXCLUDED.confidence, updated_at = now()
                   RETURNING id""",
                (vid, cc, f, jsonb(value), conf, decision_id, f"ai:{decision_id}")).fetchone()["id"]
            stats["ai_values"] += 1
            if f in CRITICAL_FIELDS:
                open_review(conn, level=5, entity_type="spec", entity_id=vid, country=cc, field_=f,
                            issue="ai_value", source="ai", kind="individual",
                            proposed={"value": value, "raw": raw, "confidence": conf},
                            ai_decision_id=decision_id, evidence_id=ev)
                stats["critical_individual"] += 1
        for s in v.get("suspect_known") or []:
            open_review(conn, level=5, entity_type="spec", entity_id=vid, field_=str(s.get("field", ""))[:60],
                        country="" if s.get("field") in MECH_FIELDS else country, issue="ai_suspect_known",
                        source="ai", kind="individual", proposed=s, ai_decision_id=decision_id)
            stats["suspect_known"] += 1


# --- CLI ---------------------------------------------------------------------------------------------
def run_cli(conn, args) -> int:
    kind = "identity" if args.kb_cmd == "ai-identity" else "specs"
    if args.collect:
        print(collect(conn, args.run_id))
        print("Next: kb review export")
        return 0
    makes = {m.strip().lower() for m in args.makes.split(",")} if args.makes else None
    reqs = identity_requests(conn, makes) if kind == "identity" else specs_requests(conn, args.min_listings, makes)
    reqs = _with_params(reqs, kind, args.effort)
    reqs, skipped = _drop_answered(conn, reqs)
    if args.limit:
        reqs = reqs[:args.limit]
    if not reqs:
        print(f"Nothing to send ({skipped} requests already answered).")
        return 0
    est = estimate(reqs, kind, getattr(args, "count_tokens", False))
    print(f"{kind}: {est['requests']} requests ({skipped} already answered, not resent), "
          f"~{est['input_tokens']:,} input tokens [{est['method']}], ~{est['output_tokens_est']:,} output+thinking tokens")
    print(f"Estimated cost (Batch, {MODEL}, effort={args.effort}): US${est['cost_usd_est']} "
          f"(range US${est['cost_usd_range'][0]}-{est['cost_usd_range'][1]})")
    if args.estimate:
        return 0
    if not args.confirm:
        print("Not sent: --submit spends money. Re-run with --submit --confirm once the estimate is approved.")
        return 2
    run_id = submit(conn, reqs, kind, args.effort, est)
    print(f"Submitted ai_run {run_id}. Collect with: kb {args.kb_cmd} --collect --run-id {run_id}")
    return 0
