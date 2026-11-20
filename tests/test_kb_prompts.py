"""Prompts are deterministic (cache + memoization) and schemas are strict."""
import pytest

pytest.importorskip("psycopg")

from vehicle_scraper.kb.ai_batch import parse_message
from vehicle_scraper.kb.prompts import (IDENTITY_SCHEMA, SPECS_SCHEMA, identity_user, input_hash,
                                        request_params, specs_user)


def _strict(schema):
    if "anyOf" in schema:
        for s in schema["anyOf"]:
            _strict(s)
    if schema.get("type") == "object":
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        for s in schema["properties"].values():
            _strict(s)
    if schema.get("type") == "array":
        _strict(schema["items"])


def test_schemas_are_strict():
    _strict(IDENTITY_SCHEMA)
    _strict(SPECS_SCHEMA)


def test_identity_prompt_is_byte_stable():
    models = [{"id": 2, "spellings": {"Rav4", "RAV 4"}, "n": 3, "years": [2018, 2020], "sites": {"carroya"}},
              {"id": 1, "spellings": {"Prado"}, "n": 1, "years": None, "sites": {"cars24", "carroya"}}]
    a = identity_user({"name": "Toyota"}, models, [{"id": 9, "name": "Hilux"}], [])
    b = identity_user({"name": "Toyota"}, list(reversed(models)), [{"id": 9, "name": "Hilux"}], [])
    assert a == b and a.index("\n1\t") < a.index("\n2\t")
    p1, p2 = request_params("identity", a, "low"), request_params("identity", b, "low")
    assert input_hash(p1) == input_hash(p2)
    assert input_hash(p1) != input_hash(request_params("identity", a, "medium"))


def test_request_params_shape():
    p = request_params("specs", specs_user("Toyota", "Hilux", "Colombia", []), "medium")
    assert p["model"] == "claude-opus-5-5"
    assert "thinking" not in p and "temperature" not in p             # Opus 5.5: adaptive, no sampling params
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert p["output_config"]["effort"] == "medium"
    assert p["output_config"]["format"]["type"] == "json_schema"


def test_parse_message():
    ok = {"stop_reason": "end_turn", "content": [{"type": "thinking", "thinking": ""},
                                                 {"type": "text", "text": '{"variants": []}'}]}
    assert parse_message(ok) == ({"variants": []}, "end_turn")
    assert parse_message({"stop_reason": "refusal", "content": []}) == (None, "refusal")
    assert parse_message({"stop_reason": "max_tokens", "content": [{"type": "text", "text": '{"var'}]}) == (None, "max_tokens")
