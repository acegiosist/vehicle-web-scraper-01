"""Unit conversion, number parsing and enum/boolean normalization.

Every function returns ``None`` when it can't interpret a value: the scraper
never guesses.
"""
from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def to_datetime(value: object) -> Optional[datetime]:
    """ISO-8601 date/datetime -> timezone-aware UTC datetime.

    Accepts '2026-11-14T20:40:46.000Z', '2026-11-19T21:41:39.000+0000', '2026-10-02' etc.
    A value without a timezone is taken as UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip().replace("Z", "+00:00")
    s = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", s)          # +0000 -> +00:00 (py3.10 fromisoformat)
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)                    # >6 fractional digits
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).astimezone(timezone.utc)

def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm(text: object) -> str:
    """Lowercase, accent-free, HTML-unescaped, single-spaced text."""
    if text is None:
        return ""
    s = html.unescape(str(text))
    s = strip_accents(s).lower().replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def clean(text: object) -> Optional[str]:
    if text is None:
        return None
    s = re.sub(r"\s+", " ", html.unescape(str(text))).strip(" :-–|\t\n")
    return s or None


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
_NUM_RE = re.compile(r"-?\d[\d.,]*")


def parse_number(value: object) -> Optional[float]:
    """Parse the first number in a string, handling ES/EN thousand separators.

    "27,770 km" -> 27770 | "44.900.000" -> 44900000 | "2.700" -> 2700
    "1.5l" -> 1.5 | "14,5 km/l" -> 14.5 | "9,102858" -> 9.102858
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUM_RE.search(html.unescape(str(value)))
    if not m:
        return None
    s = m.group(0).rstrip(".,")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):          # 44.900.000 / 2.700
        s = s.replace(".", "")
    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+", s):         # 27,770
        s = s.replace(",", "")
    elif "," in s and "." in s:                            # 1.234,5 or 1,234.5
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(value: object) -> Optional[int]:
    n = parse_number(value)
    return int(round(n)) if n is not None else None


# ---------------------------------------------------------------------------
# Unit conversions (label/unit text is used as a hint)
# ---------------------------------------------------------------------------
GAL_TO_L = 3.78541
MPG_TO_KML = 0.425144
CUFT_TO_L = 28.3168
MI_TO_KM = 1.60934
KW_TO_HP = 1.34102
PS_TO_HP = 0.98632


# Cylinder, valve and stroke counts: "V6", "16V", "4 cilindros", "1 cilindro", "6 Cyl", "4 tiempos", "4-stroke".
_ENGINE_LAYOUT_RE = re.compile(r"\b[vlhiw]-?\d{1,2}\b"
                               r"|(?<![\d.,])\d{1,2} ?-?(v|cilindros?|valvulas|cyl|cylinders?|valves|tiempos|strokes?)\b")


_LITRES_RE = re.compile(r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,3})?)\s?(?:l|lts?|litros?|liters?|litres?)\b")


def to_displacement_l(value: object, hint: str = "", moto: bool = False) -> Optional[float]:
    """Litres; ``moto`` accepts small engines (from 50 cc) and keeps exact cc (3 decimals)."""
    m = _LITRES_RE.search(norm(value)) if isinstance(value, str) else None
    if m:                                                 # explicit litres win: "1.5 L (1.496 cc)"
        n = parse_number(m.group(1))
    else:
        # Drop cylinder/valve tokens first: "V6 3.5" -> 3.5, "16V 2.0" -> 2.0 (not 6 or 16).
        n = parse_number(_ENGINE_LAYOUT_RE.sub(" ", norm(value)) if isinstance(value, str) else value)
        h = norm(f"{hint} {value}")
        # Word-bounded: a bare "cc" would also match inside "inyeccion" (injection).
        if n is not None and (n >= 50 or re.search(r"\bc\.?c\b|cm3", h)):       # cubic centimetres
            n = n / 1000
    if n is None or n <= 0:
        return None
    if moto:
        return round(n, 3) if 0.05 <= n <= 10 else None
    return round(n, 1) if 0.5 <= n <= 10 else None


# Explicit "d.d" engine size in a title/trim: "1.4 LS Mecanico", "Oroch 1.3T", "2,0L". Not "77.4 kWh",
# "5.000 km" or "Serie 3 320i".
_TITLE_DISPLACEMENT_RE = re.compile(r"(?<![\w.,])(\d[.,]\d)(?:\s?(?:l|t))?(?![\w.,])")


def displacement_from_title(value: object) -> Optional[str]:
    m = _TITLE_DISPLACEMENT_RE.search(norm(value))
    return m.group(1) if m else None


_NUMBER_WORDS = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
                 "nueve": 9, "diez": 10, "once": 11, "doce": 12}


def to_cylinders(value: object) -> Optional[int]:
    v = norm(value)
    m = re.search(r"\b([vlhiw])\s?-?(\d{1,2})\b", v)         # V6, L4, I-4, H4, W12
    if m:
        return int(m.group(2))
    n = parse_int(v)                                          # "6 en V", "4"
    if n is None:                                             # "cuatro en linea"
        m = re.search(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", v)
        n = _NUMBER_WORDS[m.group(1)] if m else None
    return n if n and 1 <= n <= 16 else None


def to_hp(value: object, hint: str = "", moto: bool = False) -> Optional[int]:
    """``moto`` accepts small engines (from 3 hp)."""
    n = parse_number(value)                                   # "175/6000" -> 175
    if n is None:
        return None
    h = norm(f"{hint} {value}")
    # The unit right after the number wins over other units in the text: "10Hp (7.5Kw)" is 10 hp.
    m = re.match(r"\D*?\d[\d.,]*\s*([a-z]*)", norm(value))
    unit = m.group(1) if m else ""
    if unit in ("hp", "bhp"):
        pass
    elif unit == "kw" or (unit not in ("cv", "ps") and re.search(r"\bkw\b", h)):
        n *= KW_TO_HP
    elif unit in ("cv", "ps") or re.search(r"\b(cv|ps)\b", h):
        n *= PS_TO_HP
    n = int(round(n))
    return n if (3 if moto else 30) <= n <= 2000 else None


def to_liters(value: object, hint: str = "") -> Optional[float]:
    n = parse_number(value)
    if n is None or n <= 0:
        return None
    h = norm(f"{hint} {value}")
    if re.search(r"galon|gallon|\bgal\b", h):
        n *= GAL_TO_L
    elif re.search(r"cu\.? ?ft|pies cubicos|ft3", h):
        n *= CUFT_TO_L
    return round(n, 1)


def to_km(value: object, hint: str = "") -> Optional[int]:
    n = parse_number(value)
    if n is None or n < 0:
        return None
    if re.search(r"\b(mi|millas|miles)\b", norm(f"{hint} {value}")):
        n *= MI_TO_KM
    return int(round(n))


def to_kml(value: object, hint: str = "") -> Optional[float]:
    n = parse_number(value)
    if n is None or n <= 0:
        return None
    h = norm(f"{hint} {value}")
    if "mpg" in h or "millas por galon" in h:
        n *= MPG_TO_KML
    elif re.search(r"l ?/ ?100|litros ?/ ?100", h):
        n = 100 / n
    elif re.search(r"km ?/ ?gal", h):
        n /= GAL_TO_L
    return round(n, 1) if 2 <= n <= 60 else None


def to_kw(value: object) -> Optional[float]:
    n = parse_number(value)
    return round(n, 1) if n and 1 <= n <= 1000 else None


def to_inches(value: object) -> Optional[float]:
    v = norm(value)
    m = re.search(r"r\s?(\d{2}(?:\.\d)?)", v)                 # "R16" or "235/60R16"
    n = float(m.group(1)) if m else parse_number(v)
    return n if n and 5 <= n <= 30 else None


def to_tire_size(value: object, rim: Optional[float] = None) -> Optional[str]:
    v = norm(value).upper().replace(" ", "")
    m = re.search(r"(\d{3})/(\d{2})Z?R?(\d{2})?", v)
    if not m:
        return None
    width, profile, r = m.groups()
    r = r or (str(int(rim)) if rim else None)
    return f"{width}/{profile}R{r}" if r else f"{width}/{profile}"


_INCH = r"(?:\"|”|''|¿|pulg(?:adas)?\b|inch(?:es)?\b|in\b)"
_RIM_PATTERNS = [
    re.compile(r"^r\s?(\d{2})$"),                             # "R16"
    re.compile(r"\b(\d{2})\s*" + _INCH),                      # '16" x 6,5J', "aluminio de 16¿" (mangled ")
    re.compile(r"\b(\d{2})\s*x\s*\d+(?:[.,]\d+)?\s*j\b"),     # "13 x 4.5J" (diameter x width J)
]


def rim_from_tire_text(value: object) -> Optional[int]:
    """A rim size written where a tire size was expected ("R16", '16" x 6,5J'). A bare number
    ("14") is not read: under a tire label it may as well be a width or profile."""
    v = norm(value)
    for rx in _RIM_PATTERNS:
        m = rx.search(v)
        if m and 10 <= int(m.group(1)) <= 26:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Booleans and enums
# ---------------------------------------------------------------------------
_TRUE = {"s", "si", "yes", "y", "true", "1", "incluido", "incluida", "con", "x", "✓", "✔", "disponible", "estandar", "standard", "serie", "de serie"}
_FALSE = {"n", "no", "false", "0", "sin", "-", "–", "✗", "✘", "no disponible", "no incluido", "no aplica", "n/a", "na", "ninguno"}


def to_bool(value: object) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    v = norm(value)
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


def _first_match(value: object, table: list[tuple[str, str]]) -> Optional[str]:
    v = norm(value)
    if not v:
        return None
    for pattern, result in table:
        if re.search(pattern, v):
            return result
    return None


_FUEL = [
    (r"hibrid|hybrid|\bhev\b|\bphev\b|\bmhev\b", "Hybrid"),
    (r"electric|\bev\b|\bbev\b", "EV"),
    (r"diesel|acpm|gasoil|gasoleo", "Diesel"),
    (r"\bflex\b|flex ?fuel|\be85\b|etanol|ethanol", "Flex"),    # gasoline/ethanol, before Gasoline
    (r"gasolin|nafta|bencina|petrol|gasoline|\bgas\b", "Gasoline"),
]
_TRANSMISSION = [
    (r"\bcvt\b|continuamente variable|variable continua", "CVT"),
    (r"\bdct\b|\bdsg\b|doble embrague|dual[- ]clutch|\bpdk\b", "DCT"),
    (r"manual|mecanic|estandar|standard|sincronic", "Manual"),
    (r"automat|\bat\b|tiptronic|steptronic|secuencial|automatic", "Automatic"),
]
_DRIVETRAIN = [
    (r"\bawd\b|integral|all[- ]wheel|4matic|quattro|xdrive|4motion|sh-awd", "AWD"),
    (r"4x4|4wd|doble traccion|four[- ]wheel|^doble$", "4WD"),   # "Traccion: Doble"
    (r"\bfwd\b|delanter|front", "FWD"),
    (r"\brwd\b|traser|rear|propulsion", "RWD"),
    (r"4x2|\b2wd\b|2x4", "2WD"),        # last: "4x2 delantera" stays FWD
]
_BODY = [
    # US cab styles ("Crew Cab", "SuperCrew", "Chassis Cab") only exist on pickups.
    (r"pick ?-?up|doble cabina|cabina (sencilla|simple|doble|extendida)|camioneta de platon|platon"
     r"|\b(crew|extended|regular|double|quad|king|access|mega|super) ?cab\b|\bsupercrew\b|\bchassis ?cab\b",
     "Pickup"),     # (same cab list as _PICKUP_CAB below)
    (r"minivan|monovolumen", "Minivan"),
    (r"station ?wagon|familiar|rural\b|estate|break\b", "Wagon"),
    (r"\bsuv\b|crossover|todoterreno|todo terreno|campero|\bwagon\b|camioneta", "SUV"),
    (r"\bvans?\b|furgon|panel", "Van"),
    (r"hatch|hb\b|5 ?p(uertas)?\b", "Hatchback"),
    (r"sedan|berlina|4 ?p(uertas)?\b", "Sedan"),
    (r"coupe|cupe", "Coupe"),
    (r"convertible|cabrio|roadster|descapotable", "Convertible"),
    (r"camion|truck|\bchass?is\b", "Truck"),     # "Chassis": a chassis cab, a truck without a bed
    # Last, so "camion de carga" stays Truck: carroya's bare "Carga"/"Pasajeros".
    (r"\bcarga\b|\bpasajeros\b", "Van"),
]
# Vague body values, used only when no other source gives a body style: a "Deportivo"
# (sports car) may well be a roadster that the seller's comments call "convertible".
_BODY_FALLBACK = [
    (r"\bdeportivo\b", "Coupe"),
]


_NATURAL_GAS_RE = re.compile(r"gas natural|gas licuado|\b(gnv|gnc|glp|cng|lpg)\b|propano")
_CNG_RE = re.compile(r"gas natural|\b(gnv|gnc|cng)\b")
_COMBUSTION_RE = re.compile(r"gasolin|diesel|nafta|bencina|petrol|gasoline")


# Strict matchers for titles / trim names ("Mazda 3 2.0 Sedan Touring Aut"): only explicit
# tokens count. The generic tables above would misread names ("Frontier" -> FWD) or guess
# from door counts ("5 puertas" -> Hatchback), which is fine for a body-type field but not here.
_PICKUP_CAB = r"\b(crew|extended|regular|double|quad|king|access|mega|super) ?cab\b|\bsupercrew\b|\bchassis ?cab\b"
_BODY_EXPLICIT = [
    (r"pick ?-?up|doble cabina|cabina (sencilla|simple|doble|extendida)|" + _PICKUP_CAB, "Pickup"),
    (r"\bminivan\b|monovolumen", "Minivan"),
    (r"station ?wagon", "Wagon"),
    (r"\bsuv\b|\bcrossover\b", "SUV"),
    (r"\bvan\b|\bfurgon\b", "Van"),
    (r"hatch ?back|\bhatch\b", "Hatchback"),
    (r"\bsedan\b", "Sedan"),
    (r"\bcoupe\b|\bcupe\b", "Coupe"),
    (r"\bconvertible\b|\bcabrio(let)?\b|\broadster\b|descapotable", "Convertible"),
]
_DRIVETRAIN_EXPLICIT = [
    (r"\bawd\b|4matic|quattro|xdrive|4motion|sh-awd|traccion integral", "AWD"),
    (r"\b4x4\b|\b4wd\b", "4WD"),
    (r"\bfwd\b", "FWD"),
    (r"\brwd\b", "RWD"),
    (r"\b(4x2|2wd|2x4)\b", "2WD"),
]


def body_from_title(value: object) -> Optional[str]:
    return _first_match(value, _BODY_EXPLICIT)


def drivetrain_from_title(value: object) -> Optional[str]:
    return _first_match(value, _DRIVETRAIN_EXPLICIT)


def doors_from_title(value: object) -> Optional[int]:
    m = re.search(r"\b([2-5]) ?(p|ptas|puertas|doors?)\b", norm(value))
    return int(m.group(1)) if m else None


def to_fuel(value: object) -> Optional[str]:
    v = norm(value)
    # Bi-fuel (gasoline + gas) and LPG have no schema value -> None, never "Gasoline".
    if (_COMBUSTION_RE.search(v) and _NATURAL_GAS_RE.search(v)) or (re.search(r"gasolin", v) and re.search(r"\bgas\b", v)):
        return None
    if _CNG_RE.search(v):
        return "CNG"
    if _NATURAL_GAS_RE.search(v):
        return None
    # "Gasolina y eléctrico" is a hybrid powertrain, not an EV.
    if re.search(r"electric", v) and _COMBUSTION_RE.search(v):
        return "Hybrid"
    return _first_match(v, _FUEL)


def to_transmission(value: object) -> Optional[str]:
    return _first_match(value, _TRANSMISSION)


def to_drivetrain(value: object) -> Optional[str]:
    """4x2 / 2WD without front/rear stated -> "2WD" (never guessed as FWD or RWD)."""
    return _first_match(value, _DRIVETRAIN)


def to_body(value: object) -> Optional[str]:
    return _first_match(value, _BODY)


def body_fallback(value: object) -> Optional[str]:
    return _first_match(value, _BODY_FALLBACK)


# Matrix/pixel first ("LED matricial" is not plain LED), then xenon, LED, halogen.
_HEADLIGHT = [
    (r"matri[cx]|pixel|multibeam|digital light|adaptive (driving beam|led)|\badb\b", "MatrixLED"),
    (r"xenon|\bhid\b|bi-?xenon|descarga de gas", "Xenon"),
    (r"\bfull[- ]?led\b|\bleds?\b", "LED"),
    (r"halogen", "Halogen"),
]


def to_headlight(value: object) -> Optional[str]:
    """Headlight technology: Halogen | Xenon | LED | MatrixLED, or None."""
    return _first_match(value, _HEADLIGHT)


def to_brake(value: object) -> Optional[str]:
    """Brake type of one axle: Disc | Drum. Both words ("disco/tambor") is not one axle's
    answer, so it gives None."""
    v = norm(value)
    disc, drum = bool(re.search(r"disco|discos|\bdiscs?\b", v)), bool(re.search(r"tambor|\bdrums?\b", v))
    if disc == drum:
        return None
    return "Disc" if disc else "Drum"


_FRONT = r"(delanter[oa]s?|front)"
_REAR = r"(traser[oa]s?|posterior(es)?|rear)"
_ALL_WHEELS = r"(\b4[- ]?(wheel|ruedas)|cuatro ruedas|four[- ]wheel|all[- ]wheel|\b4 discos)"
_DISC = r"(disco|discos|discs?)"
_DRUM = r"(tambor|tambores|drums?)"
_NOT_BRAKE_TYPE = re.compile(r"\babs\b|asist|assist|emergenc|mano|estacionamiento|parking|control|electronic"
                             r"|regenera|distribu|ebd|\bbas\b|pastilla|pad|liquido|fluid"
                             r"|diamet|rotor|caliper|pinza|size|tamano|width|thickness|espesor|swept")


def brakes_from_text(value: object) -> dict:
    """{"brake_front": .., "brake_rear": ..} from an equipment text such as "4-Wheel Disc Brakes",
    "Front Disc/Rear Drum Brakes" or "Frenos de disco delanteros"; only what it states."""
    v = norm(value)
    if not re.search(r"fren|brake", v) or _NOT_BRAKE_TYPE.search(v):
        return {}
    if re.search(_ALL_WHEELS, v) and re.search(_DISC, v):
        return {"brake_front": "Disc", "brake_rear": "Disc"}
    out = {}
    # First "<axle> <type>" ("Front Disc/Rear Drum", "delanteros de disco"), then "<type> <axle>"
    # ("discos delanteros y tambores traseros") for an axle still unknown; at most one word between.
    for pattern in ("{side}\\W+(\\w+\\W+)?{word}", "{word}\\W+(\\w+\\W+)?{side}"):
        for axle, side in (("brake_front", _FRONT), ("brake_rear", _REAR)):
            if axle in out:
                continue
            kinds = [k for k, w in (("Disc", _DISC), ("Drum", _DRUM))
                     if re.search(pattern.format(side=side, word=w), v)]
            if len(kinds) == 1:
                out[axle] = kinds[0]
    return out


_COUNTRIES = {
    "japon": "Japan", "japan": "Japan", "corea": "South Korea", "korea": "South Korea",
    "mexico": "Mexico", "brasil": "Brazil", "brazil": "Brazil", "estados unidos": "United States",
    "usa": "United States", "eeuu": "United States", "ee.uu": "United States", "united states": "United States",
    "alemania": "Germany", "germany": "Germany", "china": "China", "india": "India",
    "tailandia": "Thailand", "thailand": "Thailand", "colombia": "Colombia", "argentina": "Argentina",
    "espana": "Spain", "spain": "Spain", "francia": "France", "france": "France", "italia": "Italy",
    "italy": "Italy", "reino unido": "United Kingdom", "inglaterra": "United Kingdom", "uk": "United Kingdom",
    "suecia": "Sweden", "sweden": "Sweden", "indonesia": "Indonesia", "turquia": "Turkey",
    "ecuador": "Ecuador", "chile": "Chile", "hungria": "Hungary", "eslovaquia": "Slovakia",
    "republica checa": "Czech Republic", "canada": "Canada", "sudafrica": "South Africa",
    "taiwan": "Taiwan", "vietnam": "Vietnam", "malasia": "Malaysia", "filipinas": "Philippines",
    "uruguay": "Uruguay", "peru": "Peru", "venezuela": "Venezuela", "portugal": "Portugal",
    "belgica": "Belgium", "austria": "Austria", "polonia": "Poland", "rumania": "Romania",
}


def to_country(value: object) -> Optional[str]:
    v = norm(value)
    for key, name in _COUNTRIES.items():
        if re.search(rf"\b{re.escape(key)}\b", v):
            return name
    return None


def to_year(value: object) -> Optional[int]:
    m = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b", str(value))
    return int(m.group(1)) if m else None
