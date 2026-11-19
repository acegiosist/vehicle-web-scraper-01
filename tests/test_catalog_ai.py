"""AI step (stage 3-4) offline: prepare -> simulated Batch results -> validate/apply -> rebuild,
memoization, re-queueing of failed requests and the human review round trip. No network."""
import csv
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from vehicle_scraper.catalog import schema as S
from vehicle_scraper.catalog.ai_batch import estimate, ingest, prepare
from vehicle_scraper.catalog.ai_prompt import MODEL, OUTPUT_SCHEMA, SYSTEM_PROMPT
from vehicle_scraper.catalog.build import build_catalog
from vehicle_scraper.catalog.canonical import MakeTable
from vehicle_scraper.catalog.review import export_review, import_review, read_xlsx

MAKES = MakeTable({"Honda": {}})


def row(site, lid, model, trim=None, **kw):
    return {"source_site": site, "listing_id": lid, "make": "Honda", "model": model, "trim": trim,
            "currency": {"carroya": "COP", "cofino": "GTQ"}[site], "model_year": 2020,
            "fuel_type": "Gasoline", "transmission_type": "Automatic", "scraped_at": "2026-11-18T10:00:00+00:00"} | kw


RAW = [
    row("carroya", "c1", "CR-V", "EXL", body_style="SUV"),
    row("cofino", "g1", "CRV", None, body_style="SUV"),                     # spelling question
    row("carroya", "c2", "HR-V", "EX", body_style="SUV"),
    row("cofino", "g2", "NEW HR-V", None),                                  # unverified -> AI says merge
    row("carroya", "c3", "Pilot", "Touring Edicion Especial Black"),        # no body + long trim
    row("cofino", "g3", "ODYSSEY", None),                                   # unverified, AI unsure
]


@pytest.fixture
def engine(tmp_path):
    e = S.get_engine(f"sqlite:///{(tmp_path / 'catalog.sqlite').as_posix()}")
    return e


def _ids(request):
    """name -> local id, and (raw_model, raw_trim) -> trim id, read back from the TSV message."""
    text = request["params"]["messages"][0]["content"]
    models, trims, section = {}, {}, None
    for line in text.splitlines():
        if line in ("MODELS", "TRIMS", "KNOWN"):
            section = line
            continue
        cells = line.split("\t")
        if section == "MODELS" and cells[0].startswith("m"):
            models[cells[1]] = cells[0]
        elif section == "TRIMS" and cells[0].startswith("t"):
            trims[cells[2]] = (cells[0], cells[1])
        elif section == "KNOWN" and line:
            models.update({p.split("=")[1]: p.split("=")[0] for p in line.split(", ")})
    return models, trims


def _result(custom_id, answer=None, kind="succeeded", stop="end_turn"):
    usage = SimpleNamespace(input_tokens=120, output_tokens=80, cache_read_input_tokens=1100,
                            cache_creation_input_tokens=0)
    msg = None if answer is None else SimpleNamespace(
        stop_reason=stop, usage=usage, content=[SimpleNamespace(type="text", text=json.dumps(answer))])
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type=kind, message=msg))


def _model(id_, action, name, conf=0.95, merge=None, body=None, src=None):
    return {"id": id_, "action": action, "canonical_name": name, "merge_into": merge, "vehicle_class": "car",
            "body_style": body, "body_source": src, "confidence": conf, "note": ""}


def test_request_shape_is_cache_friendly(engine, tmp_path):
    rep = build_catalog(engine, RAW, MAKES)
    prep = prepare(engine, rep.resolution, tmp_path / "ai")
    assert len(prep.requests) == 1 and prep.requests[0]["custom_id"] == "honda-0"
    p = prep.requests[0]["params"]
    assert p["model"] == MODEL == "claude-opus-5-5"
    assert p["system"] == [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    assert p["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}
    assert "temperature" not in p and "thinking" not in p
    models, trims = _ids(prep.requests[0])
    assert {"CRV", "NEW HR-V", "Pilot", "Odyssey"} <= set(models) and "Pilot" in trims
    assert "EXL" not in json.dumps(trims)                          # short, clean trims are not sent
    est = estimate(prep.requests, prep.n_models + prep.n_trims)
    assert est["system_tokens"] >= 512                             # Opus 5.5's minimum cacheable prefix
    assert (tmp_path / "ai" / f"run_{prep.run_id}.jsonl").exists()


def test_ingest_applies_validates_and_memoizes(engine, tmp_path):
    rep = build_catalog(engine, RAW, MAKES)
    prep = prepare(engine, rep.resolution, tmp_path / "ai")
    models, trims = _ids(prep.requests[0])
    t_id, t_model = trims["Pilot"]
    answer = {"models": [
        _model(models["CRV"], "rename", "CR-V", body="SUV", src="title"),
        _model(models["NEW HR-V"], "merge", "HR-V", merge=models["HR-V"]),
        _model(models["Pilot"], "keep", "Pilot", body="SUV", src="ai_knowledge"),
        _model(models["Odyssey"], "keep", "Odyssey", conf=0.5),
        _model("m99", "keep", "Ghost"),                                         # never asked: ignored
    ], "trims": [
        {"id": t_id, "model_id": t_model, "trim_name": "Touring Black Edition", "engine_displacement_l": None,
         "transmission_type": "Manual", "fuel_type": None, "drivetrain": None, "body_style": None, "doors": None,
         "confidence": 0.9, "note": ""},                                        # Manual contradicts listings
    ]}
    out = ingest(engine, [_result("honda-0", answer)], prep.run_id)
    assert (out.accepted, out.review, out.rejected, out.requeued) == (3, 2, 0, 0)
    assert out.usage["cache_read_input_tokens"] == 1100 and out.cost_usd > 0

    build_catalog(engine, RAW, MAKES)
    with engine.connect() as c:
        names = {n: (locked, body) for n, locked, body in c.execute(
            select(S.model.c.name, S.model.c.name_locked, S.model.c.default_body_style))}
        reviews = {(r.entity_type, r.reason) for r in c.execute(select(S.review_item))}
        hrv_listings = c.execute(select(S.listing.c.listing_id).join(S.variant, S.variant.c.id == S.listing.c.variant_id)
                                 .join(S.trim, S.trim.c.id == S.variant.c.trim_id)
                                 .join(S.model, S.model.c.id == S.trim.c.model_id)
                                 .where(S.model.c.name == "HR-V")).scalars().all()
    assert names["CR-V"] == (True, "SUV") and "CRV" not in names
    assert "NEW HR-V" not in names and sorted(hrv_listings) == ["c2", "g2"]     # merged and pruned
    assert names["Pilot"][1] is None                                             # knowledge waits for review
    assert {("model", "ai_knowledge_body"), ("model", "ai_model"), ("trim", "ai_trim")} <= reviews

    again = prepare(engine, build_catalog(engine, RAW, MAKES).resolution, tmp_path / "ai")
    assert again.requests == [] and again.skipped_memoized >= 3                 # nothing is asked twice


def test_failed_requests_are_requeued(engine, tmp_path):
    rep = build_catalog(engine, RAW, MAKES)
    prep = prepare(engine, rep.resolution, tmp_path / "ai")
    out = ingest(engine, [_result("honda-0", kind="errored")], prep.run_id)
    assert out.requeued == prep.n_models + prep.n_trims and out.accepted == 0
    again = prepare(engine, build_catalog(engine, RAW, MAKES).resolution, tmp_path / "ai")
    assert len(again.requests) == 1                                             # asked again next time


class _StreamingClient:
    """Mimics the SDK: results() streams over the client's connection, which closes when the client
    is closed or garbage-collected. No reference cycle, so a throwaway client dies right away."""
    def __init__(self, results, state):
        def retrieve(batch_id):
            return SimpleNamespace(id=batch_id, processing_status="ended", request_counts=SimpleNamespace(
                succeeded=len(results), processing=0, errored=0, expired=0, canceled=0))

        def stream(batch_id):
            for r in results:
                if state["closed"]:
                    raise OSError("[WinError 10038] An operation was attempted on something that is not a socket")
                yield r

        self.state = state
        self.messages = SimpleNamespace(batches=SimpleNamespace(retrieve=retrieve, results=stream))

    def close(self):
        self.state["closed"] = True

    __del__ = close

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_cli_ingest_keeps_the_client_open_while_streaming(engine, tmp_path, monkeypatch):
    from argparse import Namespace
    from sqlalchemy import update
    from vehicle_scraper.catalog import build, cli

    prep = prepare(engine, build_catalog(engine, RAW, MAKES).resolution, tmp_path / "ai")
    with engine.begin() as c:
        c.execute(update(S.ai_run).values(batch_id="msgbatch_test", status="submitted"))
    models, _ = _ids(prep.requests[0])
    results = [_result("honda-0", {"models": [_model(models["CRV"], "rename", "CR-V")], "trims": []})]
    state = {"closed": False}
    monkeypatch.setattr(cli, "_client", lambda: _StreamingClient(results, state))
    monkeypatch.setattr(build, "load_raw_rows", lambda path: RAW)
    raw_db = tmp_path / "vehicles.sqlite"
    raw_db.touch()
    args = Namespace(catalog_cmd="ai-ingest", db=str(engine.url), raw_db=str(raw_db), run=None)
    assert cli.run(args) == 0 and state["closed"]                               # closed only at the end
    with engine.connect() as c:
        assert c.execute(select(S.ai_run.c.status)).scalar() == "ingested"
        assert "CR-V" in set(c.execute(select(S.model.c.name)).scalars())


def test_review_round_trip(engine, tmp_path):
    rep = build_catalog(engine, RAW, MAKES)
    prep = prepare(engine, rep.resolution, tmp_path / "ai")
    models, _ = _ids(prep.requests[0])
    ingest(engine, [_result("honda-0", {"models": [_model(models["Pilot"], "keep", "Pilot", body="SUV",
                                                                 src="ai_knowledge")], "trims": []})], prep.run_id)
    xlsx = tmp_path / "review.xlsx"
    assert export_review(engine, xlsx) >= 1
    rows = read_xlsx(xlsx)
    target = next(r for r in rows if r["reason"] == "ai_knowledge_body")
    assert json.loads(target["proposal"])["body_style"] == "SUV"
    sheet = tmp_path / "review.csv"
    with sheet.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow(r | {"decision": "approve" if r is target else ""})
    counts = import_review(engine, sheet, reviewer="ana")
    assert counts["approved"] == 1 and not counts["errors"]
    build_catalog(engine, RAW, MAKES)
    with engine.connect() as c:
        src = c.execute(select(S.variant_field_source.c.value, S.variant_field_source.c.source)
                        .join(S.variant, S.variant.c.id == S.variant_field_source.c.variant_id)
                        .join(S.trim, S.trim.c.id == S.variant.c.trim_id)
                        .join(S.model, S.model.c.id == S.trim.c.model_id)
                        .where(S.model.c.name == "Pilot", S.variant_field_source.c.field == "body_style")).one()
        status = c.execute(select(S.review_item.c.status, S.review_item.c.decided_by)
                           .where(S.review_item.c.id == int(target["id"]))).one()
    assert tuple(src) == ("SUV", "ai_knowledge") and tuple(status) == ("approved", "ana")
