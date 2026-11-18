"""Generic extractors that work on most car sites.

* ``jsonld_vehicles``  – schema.org Car / Vehicle / Product objects
* ``html_pairs``       – label/value pairs from <dl>, <table>, and 2-column <li>/<div>
* ``html_feature_items`` – single-text list items (equipment lists)
* ``walk_json_pairs``  – label/value pairs hidden in embedded JSON (e.g. __NEXT_DATA__)
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterator, Optional

from bs4 import BeautifulSoup, Tag

from . import normalize as N
from .mapping import RecordBuilder, match_label

_MAX_LABEL = 60
_MAX_VALUE = 120


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------

def jsonld_objects(soup: BeautifulSoup) -> Iterator[dict]:
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or s.get_text() or "null")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, dict):
                if "@graph" in obj:
                    stack.extend(obj["@graph"] if isinstance(obj["@graph"], list) else [obj["@graph"]])
                yield obj
            elif isinstance(obj, list):
                stack.extend(obj)


def jsonld_vehicles(soup: BeautifulSoup) -> list[dict]:
    out = []
    for obj in jsonld_objects(soup):
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(x in ("Car", "Vehicle", "Motorcycle", "BusOrCoach") for x in types):
            out.append(obj)
        elif "Product" in types and any(k in obj for k in ("vehicleEngine", "mileageFromOdometer", "fuelType", "modelDate")):
            out.append(obj)
    return out


def _name(v: Any) -> Optional[str]:
    if isinstance(v, dict):
        return v.get("name") or v.get("value")
    if isinstance(v, list):
        return _name(v[0]) if v else None
    return v


def apply_jsonld(b: RecordBuilder, car: dict) -> None:
    """Map schema.org Car properties onto the builder."""
    b.set("make", _name(car.get("brand")) or _name(car.get("manufacturer")))
    b.set("model", _name(car.get("model")))
    b.set("trim", car.get("vehicleConfiguration"))
    b.set("model_year", car.get("vehicleModelDate") or car.get("modelDate") or car.get("productionDate"))
    b.set("body_style", car.get("bodyType"))
    b.set("vehicle_type", car.get("bodyType"))
    b.set("fuel_type", _name(car.get("fuelType")))
    b.set("transmission_type", car.get("vehicleTransmission"))
    b.set("drivetrain", _name(car.get("driveWheelConfiguration")))
    b.set("doors", car.get("numberOfDoors"))
    b.set("seats", _name(car.get("seatingCapacity")) or car.get("vehicleSeatingCapacity"))
    b.set("country_of_manufacture", _name(car.get("countryOfOrigin")) or _name(car.get("countryOfAssembly")))
    odo = car.get("mileageFromOdometer")
    if isinstance(odo, dict):
        b.set("mileage_km", odo.get("value"), "mi" if odo.get("unitCode") == "SMI" else "km")
    elif odo:
        b.set("mileage_km", odo)
    eng = car.get("vehicleEngine")
    for e in (eng if isinstance(eng, list) else [eng] if eng else []):
        if isinstance(e, dict):
            disp = e.get("engineDisplacement")
            if isinstance(disp, dict):
                b.set("engine_displacement_l", disp.get("value"), disp.get("unitCode", ""))
            elif disp:
                b.set("engine_displacement_l", disp)
            pw = e.get("enginePower")
            if isinstance(pw, dict):
                b.set("horsepower_hp", pw.get("value"), "kw" if pw.get("unitCode") == "KWT" else "hp")
            elif pw:
                b.set("horsepower_hp", pw)
            b.set("fuel_type", _name(e.get("fuelType")))
    tank = car.get("fuelCapacity")
    if isinstance(tank, dict):
        b.set("fuel_tank_capacity_l", tank.get("value"), "gal" if tank.get("unitCode") == "GLL" else "")
    cargo = car.get("cargoVolume")
    if isinstance(cargo, dict):
        b.set("cargo_capacity_l", cargo.get("value"), "cu ft" if cargo.get("unitCode") == "FTQ" else "")
    eff = car.get("fuelEfficiency")
    if isinstance(eff, dict):
        b.set("fuel_economy_kml", eff.get("value"), eff.get("unitText", "") or eff.get("unitCode", ""))
    offers = car.get("offers")
    offer = offers[0] if isinstance(offers, list) and offers else offers
    if isinstance(offer, dict):
        b.set("price", offer.get("price"))
        b.set("currency", offer.get("priceCurrency"))
    for prop in car.get("additionalProperty") or []:
        if isinstance(prop, dict):
            b.add_pair(str(prop.get("name", "")), prop.get("value"))


# ---------------------------------------------------------------------------
# HTML label/value pairs
# ---------------------------------------------------------------------------

def _txt(el: Tag) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def html_pairs(root: Tag) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(label: str, value: str) -> None:
        label, value = label.strip(" :"), value.strip()
        if label and value and len(label) <= _MAX_LABEL and len(value) <= _MAX_VALUE and label != value:
            key = (label.lower(), value.lower())
            if key not in seen:
                seen.add(key)
                pairs.append((label, value))

    for dl in root.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                add(_txt(dt), _txt(dd))
    for tr in root.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) == 2:
            add(_txt(cells[0]), _txt(cells[1]))
    for el in root.find_all(["li", "div", "p"]):
        kids = [c for c in el.find_all(recursive=False) if isinstance(c, Tag) and c.name not in ("svg", "img", "i", "picture")]
        texts = [_txt(c) for c in kids if _txt(c)]
        if len(texts) == 2 and len(_txt(el)) <= _MAX_LABEL + _MAX_VALUE:
            add(texts[0], texts[1])
        elif not kids or len(texts) == 1:
            t = _txt(el)
            m = re.match(r"^([^:]{2,%d}):\s*(.{1,%d})$" % (_MAX_LABEL, _MAX_VALUE), t)
            if m:
                add(m.group(1), m.group(2))
    return pairs


def html_feature_items(root: Tag) -> list[str]:
    """Short single-text <li> items (typical 'Equipamiento' lists)."""
    items = []
    for li in root.find_all("li"):
        t = _txt(li)
        if 2 < len(t) <= 80 and ":" not in t and len([c for c in li.find_all(recursive=False) if _txt(c)]) <= 1:
            items.append(t)
    return items


def apply_html(b: RecordBuilder, soup: BeautifulSoup, root_selector: Optional[str] = None) -> None:
    root = soup.select_one(root_selector) if root_selector else None
    root = root or soup.find("main") or soup.body or soup
    for tag in root.find_all(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    b.add_pairs(html_pairs(root))
    b.add_feature_list(html_feature_items(root))


# ---------------------------------------------------------------------------
# Embedded JSON (Next.js / Nuxt / window state)
# ---------------------------------------------------------------------------

def embedded_json(soup: BeautifulSoup) -> list[Any]:
    found = []
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd and nd.string:
        try:
            found.append(json.loads(nd.string))
        except json.JSONDecodeError:
            pass
    for s in soup.find_all("script"):
        text = s.string or ""
        m = re.search(r"window\.(__\w+__|__INITIAL_STATE__|__PRELOADED_STATE__)\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
        if m:
            try:
                found.append(json.loads(m.group(2)))
            except json.JSONDecodeError:
                pass
    return found


_LABEL_KEYS = ("name", "label", "title", "key", "attribute", "spec", "nombre")
_VALUE_KEYS = ("value", "value_name", "valueName", "description", "val", "valor", "text")


def walk_json_pairs(obj: Any, depth: int = 0) -> Iterator[tuple[str, Any]]:
    """Yield (label, value) from dicts like {"name": "Tracción", "value": "4x4"} and
    from plain spec dicts like {"fuelType": "Diesel"} whose key maps to a field."""
    if depth > 25:
        return
    if isinstance(obj, dict):
        lk = next((k for k in _LABEL_KEYS if isinstance(obj.get(k), str)), None)
        vk = next((k for k in _VALUE_KEYS if k in obj and isinstance(obj[k], (str, int, float, bool))), None)
        if lk and vk and lk != vk:
            yield obj[lk], obj[vk]
        for k, v in obj.items():
            if isinstance(v, (str, int, float, bool)):
                label = re.sub(r"(?<!^)(?=[A-Z])", " ", k).replace("_", " ")
                if match_label(label):
                    yield label, v
            elif isinstance(v, (dict, list)):
                yield from walk_json_pairs(v, depth + 1)
    elif isinstance(obj, list):
        for it in obj:
            yield from walk_json_pairs(it, depth + 1)


def detect_block(status: int, html: str, final_url: str = "") -> Optional[str]:
    """Return a reason string if the response is an anti-bot wall."""
    h = html[:20000].lower()
    if "captcha-delivery.com" in h or "datadome" in h and status in (403, 429):
        return "DataDome CAPTCHA"
    if status in (403, 503) and ("cloudflare" in h or "cf-chl" in h or "just a moment" in h or "attention required" in h):
        return "Cloudflare challenge"
    if "account-verification" in final_url or "/gz/account-verification" in h:
        return "Mercado Libre account verification"
    if status == 429:
        return "rate limited (HTTP 429)"
    if status == 403:
        return "HTTP 403 forbidden"
    return None
