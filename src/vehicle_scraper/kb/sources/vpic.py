"""NHTSA vPIC, Canadian Vehicle Specifications: a generation's dimensions by make, model and year.

``GetCanadianVehicleSpecifications`` (no VIN needed) returns one record per version, e.g.
"SPORTAGE AWD 4DR SUV", with overall length ``OL``, width ``OW``, height ``OH`` and wheelbase
``WB`` in cm (metric units). Records whose name starts with the model's name are kept; when some
of them name the generation's body (SUV, SEDAN, HATCH, ...), only those. Each dimension is the
value most records give (cm -> mm); disagreements are shown to the person who accepts.
"""
from __future__ import annotations

from urllib.parse import urlencode

from ..identity import compact_key
from . import MAX_YEARS, Proposal, Target, most_common

URL = "https://vpic.nhtsa.dot.gov/api/vehicles/GetCanadianVehicleSpecifications/"
FIELDS = {"OL": "length_mm", "OW": "width_mm", "OH": "height_mm", "WB": "wheelbase_mm"}
# Words vPIC uses in a version's name for each body style.
BODY_WORDS = {"SUV": ("SUV",), "Sedan": ("SEDAN",), "Hatchback": ("HATCH",), "Coupe": ("COUPE",),
              "Convertible": ("CONVERTIBLE", "CABRIOLET"), "Wagon": ("WAGON",), "Van": ("VAN",),
              "Minivan": ("VAN",), "Pickup": ("PICKUP", "CAB")}


def _specs(record: dict) -> dict:
    return {s.get("Name"): s.get("Value") for s in record.get("Specs") or []}


def propose(target: Target, responses: dict[int, list[dict]]) -> tuple[list[Proposal], list[str]]:
    """``responses``: year -> the API's ``Results``. Returns the proposals and notes for the person."""
    model = compact_key(target.model)
    rows = []                                        # (year, name, specs)
    for year, results in sorted(responses.items()):
        for r in results:
            specs = _specs(r)
            name = str(specs.get("Model") or "").strip()
            if model and compact_key(name).startswith(model):
                rows.append((year, name, specs))
    words = BODY_WORDS.get(target.body_style or "", ())
    with_body = [r for r in rows if any(w in r[1].upper().split() for w in words)]
    if with_body:
        rows = with_body
    notes = []
    if not rows:
        notes.append(f"vPIC no tiene versiones de {target.make} {target.model} en esos años")
    proposals = []
    for code, column in FIELDS.items():
        values = []
        for year, name, specs in rows:
            try:
                cm = float(str(specs.get(code)).replace(",", "."))
            except (TypeError, ValueError):
                continue
            if cm > 0:
                values.append((int(round(cm * 10)), year, name))
        p = most_common("generation", target.generation_id, column, values)
        if p:
            proposals.append(p)
    return proposals, notes


def lookup(client, target: Target) -> tuple[list[Proposal], list[str]]:
    responses = {}
    for year in target.years[-MAX_YEARS:]:
        query = urlencode({"Year": year, "Make": target.make, "Model": target.model, "units": "", "format": "json"})
        responses[year] = client.get(f"{URL}?{query}").json().get("Results") or []
    return propose(target, responses)
