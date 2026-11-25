"""Offline: the external sources' matching (kb/sources), against saved answers for a 2019 Kia Sportage."""
from __future__ import annotations

import json
from pathlib import Path

from vehicle_scraper.kb.sources import (CAPTURE, PowertrainTarget, Target, evidence_rank, fueleconomy,
                                        most_common, vpic)
from vehicle_scraper.kb.worker import FixtureClient

FIXTURE = Path(__file__).parent / "fixtures" / "sources" / "kia_sportage.json"
ANSWERS = json.loads(FIXTURE.read_text(encoding="utf-8"))


def pt(id_, disp, drive, *, trans="Automatic", fuel="Gasoline", years=(2019,), cyl=None):
    return PowertrainTarget(id_, disp, cyl, fuel, trans, drive, list(years))


def target(*pts, body="SUV"):
    return Target(7, "Kia", "Sportage", body, [2019], list(pts))


def by_key(proposals):
    return {(p.entity_type, p.entity_id, p.field): p for p in proposals}


def test_vpic_gives_the_generations_dimensions():
    url = next(u for u in ANSWERS if "vpic" in u and "Year=2019" in u)
    proposals, notes = vpic.propose(target(), {2019: ANSWERS[url]["Results"]})
    got = {p.field: (p.value, p.records) for p in proposals}
    assert got == {"length_mm": (4480, 3), "width_mm": (1860, 3), "height_mm": (1650, 3), "wheelbase_mm": (2670, 3)}
    assert notes == [] and proposals[0].years == [2019] and "SPORTAGE FWD 4DR SUV" in proposals[0].matched
    # another model's name, or a model vPIC doesn't have: nothing, and a note says so
    other = Target(7, "Kia", "Sorento", "SUV", [2019])
    assert vpic.propose(other, {2019: ANSWERS[url]["Results"]}) == ([], ["vPIC no tiene versiones de Kia Sorento en esos años"])


def test_fueleconomy_matches_records_to_powertrains():
    records = [v for u, v in ANSWERS.items() if "/vehicle/" in u and "/menu/" not in u]
    t = target(pt(1, 2.4, "FWD"), pt(2, 2.0, "AWD"), pt(3, 2.4, "2WD"), pt(4, 1.6, "FWD"), pt(5, 2.4, "FWD", years=[2021]))
    proposals, notes = fueleconomy.propose(t, records)
    got = by_key(proposals)
    # 2.4 FWD: the Sportage FWD and the Sportage FE FWD, both 25 mpg (10.6 km/L), 6 gears
    assert got[("powertrain", 1, "fuel_economy_kml")].value == 10.6
    assert got[("powertrain", 1, "fuel_economy_kml")].records == 2
    assert got[("powertrain", 1, "gears")].value == 6 and got[("powertrain", 1, "engine_cylinders")].value == 4
    # 2.0 AWD: only the turbo AWD (21 mpg)
    assert got[("powertrain", 2, "fuel_economy_kml")].value == round(21 * fueleconomy.MPG_TO_KML, 1)
    # 2WD (front or rear not stated) takes the FWD records, never the AWD ones
    assert got[("powertrain", 3, "fuel_economy_kml")].records == 2
    # no 1.6 in the EPA's Sportage, and a powertrain sold only in 2021 doesn't take 2019 records
    assert ("powertrain", 4, "gears") not in got and ("powertrain", 5, "gears") not in got
    assert notes == ["Tren motriz 4: ningún registro de la EPA coincide", "Tren motriz 5: ningún registro de la EPA coincide"]


def test_fueleconomy_reads_transmissions_and_drives():
    assert fueleconomy.transmission_of("Automatic (AV-S7)") == "CVT" and fueleconomy.gears_of("Automatic (AV-S7)") is None
    assert fueleconomy.transmission_of("Automatic (AM7)") == "DCT" and fueleconomy.gears_of("Automatic (AM7)") == 7
    assert fueleconomy.transmission_of("Manual 6-spd") == "Manual" and fueleconomy.gears_of("Manual 6-spd") == 6
    assert fueleconomy.gears_of("Automatic (variable gear ratios)") is None
    rec = {"year": "2019", "displ": "2.0", "trany": "Automatic (AV-S7)", "drive": "4-Wheel Drive",
           "fuelType1": "Regular Gasoline", "atvType": ""}
    assert fueleconomy.compatible(rec, pt(1, 2.0, "AWD"))                     # AWD ~ 4WD, Automatic ~ CVT
    assert not fueleconomy.compatible(rec, pt(1, 2.0, "FWD"))
    assert not fueleconomy.compatible(rec, pt(1, 2.0, "AWD", trans="Manual"))
    assert not fueleconomy.compatible(rec, pt(1, 2.0, "AWD", fuel="Diesel"))
    ev = {"year": "2019", "displ": None, "trany": "Automatic (A1)", "drive": "Front-Wheel Drive",
          "fuelType1": "Electricity", "atvType": "EV", "range": "239", "comb08": "112"}
    assert fueleconomy.compatible(ev, pt(1, None, "FWD", fuel="EV"))
    assert fueleconomy.values_of(ev) == {"ev_range_km": 385}                 # no km/L for an EV, 1 gear isn't kept


def test_fueleconomy_lookup_asks_only_for_matching_models_and_engines():
    client = FixtureClient(str(FIXTURE))
    asked = []
    get = client.get
    client.get = lambda url, **kw: (asked.append(url), get(url, **kw))[1]
    proposals, notes = fueleconomy.lookup(client, target(pt(1, 2.4, "FWD")))
    assert by_key(proposals)[("powertrain", 1, "fuel_economy_kml")].value == 10.6
    # the 2.0 turbo engines aren't read for a 2.4 powertrain; Sorento, Soul... never asked
    assert not any(u.endswith(("/40109", "/40113")) for u in asked)
    assert not any("Sorento" in u for u in asked) and notes == []


def test_most_common_keeps_the_others_as_alternatives():
    p = most_common("generation", 1, "length_mm", [(4480, 2019, "A"), (4480, 2020, "B"), (4500, 2021, "C")])
    assert (p.value, p.records, p.alternatives, p.years) == (4480, 2, {"4500": 1}, [2019, 2020])
    assert most_common("generation", 1, "length_mm", []) is None


def test_captured_values_win_among_external_ones():
    ranks = {CAPTURE: 0, "vpic_canada": 10, "fueleconomy": 20}
    order = sorted([("external", "fueleconomy"), ("listings", ""), ("external", CAPTURE), ("manual", ""),
                    ("external", "vpic_canada"), ("external", "gone"), ("ai", "")],
                   key=lambda k: evidence_rank(*k, ranks))
    assert order == [("manual", ""), ("external", CAPTURE), ("external", "vpic_canada"), ("external", "fueleconomy"),
                     ("external", "gone"), ("listings", ""), ("ai", "")]
