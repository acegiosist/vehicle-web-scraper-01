"""fueleconomy.gov (EPA / DOE): each powertrain's combined economy, cylinders, gears and EV range.

Its public web service, per model year: ``menu/model`` lists the make's models (the EPA names
carry the drive, "Sportage FWD"), ``menu/options`` lists each model's engines ("Auto (S6), 4
cyl, 2.4 L") with a record id, and ``vehicle/{id}`` gives the record (``displ``, ``cylinders``,
``trany``, ``drive``, ``fuelType1``, ``atvType``, ``comb08`` mpg, ``range`` miles). Only models
whose name starts with ours are read, and only engines that can match one of the generation's
powertrains. A record matches a powertrain when its year is one the powertrain was sold in
(in the source's countries) and its fuel, transmission, drivetrain and displacement are
compatible, the same rules ``kb build`` uses for listings. The person sees every value.
Credit: "Courtesy of FuelEconomy.gov, U.S. Dept. of Energy".
"""
from __future__ import annotations

import re
from urllib.parse import urlencode

from ..identity import compact_key
from . import MAX_YEARS, PowertrainTarget, Proposal, Target, most_common

BASE = "https://www.fueleconomy.gov/ws/rest/vehicle"
HEADERS = {"Accept": "application/json"}
MPG_TO_KML = 0.425144
MI_TO_KM = 1.609344
DRIVES = {"front-wheel drive": "FWD", "rear-wheel drive": "RWD", "all-wheel drive": "AWD",
          "4-wheel drive": "4WD", "part-time 4-wheel drive": "4WD", "4-wheel or all-wheel drive": "AWD",
          "2-wheel drive": "2WD"}
ATV_FUELS = {"EV": "EV", "Hybrid": "Hybrid", "Plug-in Hybrid": "Hybrid", "Diesel": "Diesel", "CNG": "CNG",
             "Bifuel (CNG)": "CNG", "FFV": "Flex"}


def _items(menu) -> list[dict]:
    """A menu's items: the service returns an object instead of a list when there is one."""
    items = (menu or {}).get("menuItem") or []
    return items if isinstance(items, list) else [items]


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fuel_of(rec: dict) -> str:
    atv = str(rec.get("atvType") or "").strip()
    if atv in ATV_FUELS:
        return ATV_FUELS[atv]
    f1 = str(rec.get("fuelType1") or "").lower()
    return "Diesel" if "diesel" in f1 else "EV" if "electric" in f1 else "Gasoline"


def transmission_of(trany: str):
    t = str(trany or "")
    if "(AV" in t or "variable" in t.lower():
        return "CVT"
    if "(AM" in t:
        return "DCT"
    return "Manual" if t.startswith("Manual") else "Automatic" if t.startswith("Auto") else None


def gears_of(trany: str):
    if transmission_of(trany) == "CVT":
        return None
    m = re.search(r"(\d+)", str(trany or ""))
    n = int(m.group(1)) if m else None
    return n if n and 2 <= n <= 12 else None


def _drive_ok(ours, theirs) -> bool:
    if not ours or not theirs or ours == theirs:
        return True
    pair = {ours, theirs}
    return ("2WD" in pair and pair <= {"2WD", "FWD", "RWD"}) or pair == {"AWD", "4WD"}


def compatible(rec: dict, pt: PowertrainTarget) -> bool:
    """The record could be this powertrain (build's rules: Automatic~CVT/DCT, 2WD~FWD/RWD,
    AWD~4WD, 0.1 L)."""
    year = int(rec.get("year") or 0)
    if pt.years and year not in pt.years:
        return False
    fuel = fuel_of(rec)
    if pt.fuel and not (pt.fuel == fuel or (pt.fuel == "Gasoline" and fuel == "Flex")):
        return False
    trans = transmission_of(rec.get("trany"))
    if pt.transmission and trans and not (pt.transmission == trans
                                          or (pt.transmission == "Automatic" and trans in ("CVT", "DCT"))):
        return False
    if not _drive_ok(pt.drivetrain, DRIVES.get(str(rec.get("drive") or "").strip().lower())):
        return False
    displ = _float(rec.get("displ"))
    if pt.displacement is not None:
        if displ is None or abs(displ - pt.displacement) > 0.1 + 1e-9:
            return False
    elif pt.cylinders and str(rec.get("cylinders") or "").isdigit() and int(rec["cylinders"]) != pt.cylinders:
        return False
    return True


def values_of(rec: dict) -> dict:
    """Level columns this record gives."""
    out = {}
    fuel = fuel_of(rec)
    if fuel != "EV":
        # the label's rounded mpg, so the same car in another year or trim gives the same value
        mpg = _float(rec.get("comb08")) or _float(rec.get("comb08U"))
        if mpg and mpg > 0:
            out["fuel_economy_kml"] = round(mpg * MPG_TO_KML, 1)
        if str(rec.get("cylinders") or "").isdigit():
            out["engine_cylinders"] = int(rec["cylinders"])
    else:
        miles = _float(rec.get("range"))
        if miles and miles > 0:
            out["ev_range_km"] = int(round(miles * MI_TO_KM))
    gears = gears_of(rec.get("trany"))
    if gears:
        out["gears"] = gears
    return out


def _name(rec: dict) -> str:
    return f"{rec.get('year')} {rec.get('model')} {rec.get('trany')}, {rec.get('displ') or '-'} L"


def propose(target: Target, records: list[dict]) -> tuple[list[Proposal], list[str]]:
    """``records``: vehicle records already narrowed to the model (``lookup``)."""
    proposals, notes = [], []
    for pt in target.powertrains:
        matched = [r for r in records if compatible(r, pt)]
        if not matched:
            notes.append(f"Tren motriz {pt.id}: ningún registro de la EPA coincide")
            continue
        by_field: dict[str, list] = {}
        for r in matched:
            for column, value in values_of(r).items():
                by_field.setdefault(column, []).append((value, int(r.get("year") or 0), _name(r)))
        for column, values in sorted(by_field.items()):
            p = most_common("powertrain", pt.id, column, values)
            if p:
                proposals.append(p)
    return proposals, notes


def _could_match(option_text: str, target: Target) -> bool:
    """Skip engines no powertrain can be (by the displacement in the option's text)."""
    m = re.search(r"(\d+(?:\.\d+)?) L", option_text)
    displ = float(m.group(1)) if m else None
    for pt in target.powertrains:
        if pt.displacement is None or displ is None or abs(displ - pt.displacement) <= 0.1 + 1e-9:
            return True
    return False


def lookup(client, target: Target) -> tuple[list[Proposal], list[str]]:
    model = compact_key(target.model)
    years = sorted({y for pt in target.powertrains for y in pt.years} or set(target.years))[-MAX_YEARS:]
    records, notes = [], []
    for year in years:
        menu = client.get(f"{BASE}/menu/model?{urlencode({'year': year, 'make': target.make})}", headers=HEADERS)
        names = [i.get("value") for i in _items(menu.json()) if compact_key(i.get("value") or "").startswith(model)]
        for name in names:
            options = client.get(f"{BASE}/menu/options?{urlencode({'year': year, 'make': target.make, 'model': name})}",
                                 headers=HEADERS)
            for item in _items(options.json()):
                if _could_match(str(item.get("text") or ""), target):
                    records.append(client.get(f"{BASE}/{item.get('value')}", headers=HEADERS).json())
    if not records:
        notes.append(f"fueleconomy.gov no tiene {target.make} {target.model} en {years[0]}–{years[-1]}"
                     if years else "sin años para consultar")
    proposals, more = propose(target, records)
    return proposals, notes + more
