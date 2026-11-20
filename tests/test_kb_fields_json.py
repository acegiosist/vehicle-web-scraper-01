"""The review website validates corrections with a copy of the field catalog
(src/web/src/generated/kb-fields.json). It must match kb/fields.py; regenerate it with
`python -m vehicle_scraper kb fields-json` when the schema changes."""
import json
from pathlib import Path

from vehicle_scraper.kb.fields import RANGES, SPEC_FIELDS, fields_catalog

GENERATED = Path(__file__).resolve().parents[1] / "src" / "web" / "src" / "generated" / "kb-fields.json"


def test_generated_catalog_is_current():
    assert GENERATED.exists(), "run: python -m vehicle_scraper kb fields-json"
    assert json.loads(GENERATED.read_text(encoding="utf-8")) == fields_catalog(), \
        "kb-fields.json is stale: run python -m vehicle_scraper kb fields-json"


def test_catalog_covers_every_reviewable_field():
    fields = fields_catalog()["fields"]
    assert set(SPEC_FIELDS) <= set(fields)
    assert fields["horsepower_hp"] == {"kind": "int", "group": "mech", "critical": True, "unit": "hp",
                                       "range": list(RANGES["horsepower_hp"])}
    assert fields["fuel_type"]["values"] == ["Gasoline", "Diesel", "Hybrid", "EV", "CNG"]
