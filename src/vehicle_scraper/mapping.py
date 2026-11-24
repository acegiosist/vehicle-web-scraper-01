"""Label → schema-field mapping (Spanish + English) and the RecordBuilder.

Sites expose data in three shapes, all handled here:
  1. label/value pairs   ("Cilindrada (c.c³)": "2656", "Frenos ABS": "Sí")
  2. feature lists       ("Tapicería en cuero", "Cámara de reversa", ...)
  3. free text           (seller comments / descriptions)

To support a new label, add a regex to LABEL_RULES or FEATURE_PATTERNS.
Labels are matched after ``normalize.norm`` (lowercase, no accents).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, Iterable, Optional

from . import normalize as N
from .models import BOOLEAN_FIELDS, VehicleRecord

# ---------------------------------------------------------------------------
# 1) Label rules: (field, include regex, exclude regex or None). First match wins,
#    so more specific rules go first.
# ---------------------------------------------------------------------------
_NOT_BRAKE_TYPE = (r"abs|asist|assist|emergenc|mano|estacionamiento|parking|control|electronic|regenera|distribu"
                   r"|diamet|rotor|caliper|pinza|size|tamano|width|ancho|thickness|espesor|swept|area")
_NOT_HEADLIGHT = (r"niebla|antiniebla|fog|exploradora|trasera|rear|tail|auto|altura|nivel|level|lavafaros|washer"
                  r"|diurn|daytime|drl|direccional|adaptativ|on/off")
LABEL_RULES: list[tuple[str, str, Optional[str]]] = [
    ("listing_skip", r"valvulas|velocidad maxima|aceleracion|torque|par motor|relacion|compresion|peso|largo|ancho|alto|diametro|suspension|amortigu|codigo|placa|color|ubicacion|blindaje|armored|garantia|warranty|direccion$|steering|cinturon", None),
    ("make", r"^(marca|brand|make|fabricante)$", None),
    ("trim", r"^(version|versión|trim|variante|acabado|edicion|linea version)$", None),
    ("model", r"^(modelo|model|linea|line|model / line)$", None),
    ("model_year", r"^(ano|anio|year|ano modelo|ano del modelo|model year|vehicle year|año)$", None),
    ("body_style", r"carroceria|bodywork|body ?(type|style)?$|tipo de vehiculo|tipo de carroceria|segmento|categoria", None),
    ("country_of_manufacture", r"pais|origen|ensambl|assembly|hecho en|procedencia|manufactur|fabricado en", None),
    ("engine_cylinders", r"cilindros|cylinders|configuracion de cilindros", r"cilindrada|valvulas"),
    ("engine_displacement_l", r"cilindrada|cilindraje|displacement|^motor$|^engine$|capacidad del motor|tamano del motor|motor \(l\)", None),
    ("horsepower_hp", r"potencia|horsepower|caballos|^hp$|^power$|potencia maxima|potencia \(h\.?p\)", r"carga|peso|charging|electrica de carga"),
    ("fuel_type", r"combustible|fuel ?(type)?$|tipo de alimentacion combustible|energia", r"tanque|tank|consumo|capacidad|economy"),
    ("fuel_tank_capacity_l", r"tanque|tank|deposito de combustible|capacidad de combustible", None),
    ("transmission_type", r"transmision|^caja|tipo de caja|gearbox|^box$|cambios$|transmission", r"cantidad de cambios|numero de cambios|velocidades"),
    ("drivetrain", r"traccion|drivetrain|wheel drive|^drive( type)?$|tipo de traccion|sistema de traccion", r"control de traccion"),
    ("brake_front", r"frenos? delanter|freno delantero|front brakes?|brakes?,? front", _NOT_BRAKE_TYPE),
    ("brake_rear", r"frenos? traser|freno trasero|frenos? posterior|rear brakes?|brakes?,? rear", _NOT_BRAKE_TYPE),
    ("headlight_type", r"tipo de (faros|farolas|luces|iluminacion)|faros delanteros|farolas delanteras|luces delanteras"
                       r"|^faros$|^farolas$|^luces$|headlamps?( type)?$|headlights?( type)?$", _NOT_HEADLIGHT),
    ("seats", r"asientos|plazas|pasajeros|seats|seating|capacidad de personas|passenger",
     r"cuero|electric|calefact|ventil|memoria|abatib|plegab|fold|split|divid|fila|\brow|ajust|lumbar"
     r"|power|heat|cool|memory|leather|material|driver|conductor"
     r"|cargo|baul|maletero|cajuela|trunk|volume|volumen|in place"),
    ("doors", r"puertas|doors?$", None),
    ("cargo_capacity_l", r"baul|maletero|cajuela|cargo|trunk|boot|portaequipaje|volumen de carga", r"carga util|payload|kg"),
    ("tire_size", r"llanta|neumatic|tire|tyre|cubierta", r"material|aleacion|life|vida"),   # not "tyre life left"
    ("wheel_size_in", r"\brin\b|rines|^aro|wheel size|dimensiones rin|tamano de rin|\brims?\b", r"material|aleacion|aluminio"),
    ("fuel_economy_kml", r"consumo|rendimiento|fuel economy|average consumption|km ?/ ?l|eficiencia", None),
    ("ev_range_km", r"autonomia|^range$|alcance electrico|ev range", None),
    ("ev_charging_speed_kw", r"carga rapida|potencia de carga|charging|carga dc|velocidad de carga", None),
    ("airbags_count", r"airbag|air bag|bolsas de aire|numero de airbags|airbag number", None),
    ("screen_size_in", r"pantalla|screen|display", None),
    ("mileage_km", r"kilometraje|kilometros|mileage|odometer|recorrido|^km$", None),
]
_LABEL_RULES = [(f, re.compile(i), re.compile(e) if e else None) for f, i, e in LABEL_RULES]
_CYLINDERS_ONLY_RE = re.compile(r"\s*\d{1,2}\s*-?\s*(cyl|cyls|cylinders?|cilindros?)\.?\s*")

# ---------------------------------------------------------------------------
# 2) Feature keyword patterns. Used for feature lists, boolean labels and text.
# ---------------------------------------------------------------------------
FEATURE_PATTERNS: dict[str, list[str]] = {
    "abs": [r"\babs\b", r"antibloqueo"],
    # "esp." followed by a word is the Spanish abbreviation of "espejos" (mirrors), not ESP.
    "stability_control": [r"control (electronico )?de estabilidad",
                          r"\besp\b(?!\.\s*[a-z]|\s+(electric|retrovis|lateral|abatib|plegab|calefact|exterior))",
                          r"\besc\b", r"\bvsc\b", r"\bvdc\b", r"stability control"],
    "traction_control": [r"control de traccion", r"\btcs\b", r"\basr\b", r"traction control"],
    "adaptive_cruise_control": [r"crucero adaptativo", r"control de crucero adaptativo", r"adaptive cruise", r"\bacc\b"],
    "lane_assist": [r"carril", r"lane (keep|assist|depart)", r"\blka\b", r"\blkas\b"],
    "automatic_emergency_braking": [r"frenado (autonomo|automatico|de emergencia)", r"\baeb\b", r"emergency brak", r"pre-?colision", r"pre-?collision",
                                    r"(front|forward) collision mitigation"],   # "warning" alone doesn't brake
    "blind_spot_monitoring": [r"punto ciego", r"angulo muerto", r"blind ?spot", r"\bbsm\b", r"\bblis\b"],
    "led_lights": [r"\bled\b", r"\bleds\b"],
    "fog_lights": [r"exploradoras", r"antiniebla", r"neblinero", r"fog ?(light|lamp)", r"faros? de niebla"],
    "panoramic_roof": [r"panoramic"],
    "sunroof": [r"sunroof", r"quemacocos", r"techo solar", r"techo corredizo", r"moonroof", r"techo electrico", r"panoramic"],
    "roof_rails": [r"barras? (de techo|portaequipaje)", r"rieles? de techo", r"roof ?(rails?|rack)", r"barras? longitudinales", r"portaequipajes de techo",
                   r"luggage rack"],
    "alloy_wheels": [r"(rines|rin|llantas|aros|ruedas) de (aleacion|aluminio|magnesio)", r"alloy", r"alumin(um|ium) wheels?",
                     r"material (de )?(los )?(rines|rin|llantas|aros|ruedas) (aleacion|aluminio|magnesio)"],
    "leather_seats": [r"cuero", r"leather", r"\bpiel\b", r"cojineria en cuero", r"tapiceria en cuero"],
    "power_seats": [r"(asiento|silla|butaca)s? (del conductor )?electric", r"power seats?",
                    r"power (driver|passenger|front|adjustable)\b.{0,20}seat", r"ajuste electrico de (asiento|silla)"],
    "heated_seats": [r"calefact", r"heated seats?", r"calefaccion de asientos"],
    "cooled_seats": [r"(asientos?|sillas?) (ventilad|refriger|enfriad)", r"cooled seats?", r"ventilated seats?"],
    "memory_seats": [r"memoria", r"memory"],
    "climate_control": [r"climatizador", r"control de clima", r"climate control", r"aire acondicionado automatico", r"\bclimatronic\b", r"climatizado"],
    "dual_zone_ac": [r"bizona", r"bi-zona", r"doble zona", r"dual[- ]?zone", r"multi[- ]?zone", r"tri[- ]?zone", r"dos zonas"],
    # "Keyless Start" is a push-button start, not keyless entry.
    "keyless_entry": [r"keyless(?! (start|ignition))", r"sin llave", r"acceso inteligente", r"llave inteligente", r"smart ?key", r"entrada sin llave", r"apertura sin llave"],
    "push_button_start": [r"push[- ]?(button|start)", r"keyless (start|ignition)", r"boton de (encendido|arranque)", r"encendido por boton", r"arranque por boton", r"start/stop button", r"start button"],
    "bluetooth": [r"bluetooth"],
    "apple_carplay": [r"carplay", r"car play"],
    "android_auto": [r"android ?auto"],
    "navigation": [r"navegador", r"navegacion", r"\bgps\b", r"navigation"],
    "wireless_charger": [r"(cargador|carga|cargadores) (de celular(es)? |de telefono(s)? |para celular(es)? )?inalambric",
                         r"wireless (phone |device |smartphone )?charg", r"inductive charg", r"carga por induccion"],
    "camera_360": [r"360", r"aerial view", r"surround[- ]view", r"bird'?s[- ]eye view"],
    "front_camera": [r"camara (frontal|delantera)", r"front camera"],
    "reverse_camera": [r"camara (de )?(reversa|retroceso|trasera|posterior|parqueo|estacionamiento)", r"rear(view)? camera", r"back[- ]?up camera", r"reverse camera", r"camara de retro"],
    "parking_sensors": [r"sensor(es)? de (parqueo|estacionamiento|reversa|retroceso|proximidad)", r"parking sensors?", r"park(ing)? aid", r"park distance", r"sensores? (delanteros|traseros)"],
    "automatic_parking": [r"(parqueo|estacionamiento|aparcamiento) (automatico|asistido)", r"park ?assist", r"auto ?park", r"automatic parking", r"self[- ]park"],
    "alarm": [r"alarma", r"\balarm\b", r"security system", r"anti[- ]?theft (system|alarm)"],
    "immobilizer": [r"inmoviliz", r"immobili"],
    "tow_package": [r"\btiro\b", r"enganche", r"gancho de remolque", r"\btow(?!\s*hooks?\b)", r"bola de remolque", r"kit de arrastre", r"tiron"],
    "bed_liner": [r"bed ?liner", r"protector de (platon|batea|caja)", r"forro de (platon|batea)", r"cubre ?(platon|batea)", r"liner"],
}
_FEATURE_RES = {f: [re.compile(p) for p in ps] for f, ps in FEATURE_PATTERNS.items()}

# Words that negate a feature mention in free text: "sin sunroof", "no tiene alarma".
_NEGATION = re.compile(r"\b(sin|no tiene|no incluye|no cuenta con|without|no)\s+(\w+\s+){0,2}$")


def match_label(label: str) -> Optional[str]:
    lab = N.norm(label)
    lab = re.sub(r"[:*]+$", "", lab).strip()
    for field, inc, exc in _LABEL_RULES:
        if inc.search(lab) and not (exc and exc.search(lab)):
            return None if field == "listing_skip" else field
    return None


_LIGHT_WORD = re.compile(r"\b(faros?|farolas?|luces|luz|headl(ight|amp)s?|projector|proyector(es)?|iluminacion)\b")
_NOT_HEADLIGHT_TEXT = re.compile(_NOT_HEADLIGHT)


def match_equipment(text: str) -> dict:
    """Valued equipment an item states: headlight type and brakes per axle ("LED Headlights",
    "Faros de xenón", "4-Wheel Disc Brakes", "Front Disc/Rear Drum Brakes"). Negated items and
    other lights (fog, tail, DRL) give nothing."""
    t = N.norm(text)
    if re.search(r"\b(sin|no tiene|no incluye|no cuenta con|without)\b", t):
        return {}
    out = dict(N.brakes_from_text(t))
    if _LIGHT_WORD.search(t) and not _NOT_HEADLIGHT_TEXT.search(t):
        kind = N.to_headlight(t)
        if kind:
            out["headlight_type"] = kind
    return out


def match_features(text: str) -> set[str]:
    """Boolean feature fields mentioned (non-negated) in ``text``."""
    t = N.norm(text)
    found: set[str] = set()
    for field, regs in _FEATURE_RES.items():
        for r in regs:
            m = r.search(t)
            if m and not _NEGATION.search(t[max(0, m.start() - 25):m.start()]):
                found.add(field)
                break
    # A panoramic roof is a sunroof, but a plain 360 mention must be a camera.
    if "camera_360" in found and not re.search(r"camara|camera|vision|vista|view", t):
        found.discard("camera_360")
    if "memory_seats" in found and not re.search(r"asiento|silla|butaca|seat|conductor", t):
        found.discard("memory_seats")
    # "Volante en cuero" / "Espejos calefactados" describe other parts, not the seats.
    if _NON_SEAT_PART.search(t) and not _SEAT_WORD.search(t):
        found -= {"leather_seats", "heated_seats"}
    return found


_SEAT_WORD = re.compile(r"asiento|silla|butaca|seat|cojineria|tapiceria|tapizad|interior")
_NON_SEAT_PART = re.compile(r"volante|timon|palanca|pomo|manubrio|espejo|retrovisor|parabrisas|luneta"
                            r"|steering|mirror|shift|gear ?knob|windshield")


# ---------------------------------------------------------------------------
# Converters per field: (raw value, label/unit hint) -> normalized value
# ---------------------------------------------------------------------------
Conv = Callable[[Any, str], Any]


def _model_year(v: Any, h: str) -> Optional[int]:
    # Same bounds as VehicleRecord's validator: out-of-range -> null + warning, not a rejected record.
    y = N.to_year(v)
    return y if y is not None and 1900 <= y <= datetime.now().year + 2 else None


def _seats(v: Any, h: str) -> Optional[int]:
    if re.search(r"\d\s*/\s*\d", str(v)):    # "60/40" is a split ratio, not a seat count
        return None
    n = N.parse_int(v)
    return n if n and 1 <= n <= 60 else None


CONVERTERS: dict[str, Conv] = {
    "make": lambda v, h: N.clean(v),
    "model": lambda v, h: N.clean(v),
    "trim": lambda v, h: N.clean(v),
    "model_year": _model_year,
    "body_style": lambda v, h: N.to_body(v),
    # "Motorcycle" only when a scraper passes it explicitly (e.g. carroya's category "Motos").
    "vehicle_type": lambda v, h: "Motorcycle" if N.norm(v) == "motorcycle" else N.to_body(v),
    "country_of_manufacture": lambda v, h: N.to_country(v),
    "engine_displacement_l": N.to_displacement_l,
    "engine_cylinders": lambda v, h: N.to_cylinders(v),
    "horsepower_hp": N.to_hp,
    "fuel_type": lambda v, h: N.to_fuel(v),
    "fuel_tank_capacity_l": N.to_liters,
    "transmission_type": lambda v, h: N.to_transmission(v),
    "drivetrain": lambda v, h: N.to_drivetrain(v),
    "seats": _seats,
    "doors": lambda v, h: (lambda n: n if n and 2 <= n <= 6 else None)(N.parse_int(v)),
    "cargo_capacity_l": lambda v, h: (lambda n: int(n) if n and 50 <= n <= 10000 else None)(N.to_liters(v, h)),
    "wheel_size_in": lambda v, h: (lambda n: int(n) if n else None)(N.to_inches(v)),
    "tire_size": lambda v, h: N.to_tire_size(v),
    "fuel_economy_kml": N.to_kml,
    "ev_range_km": lambda v, h: (lambda n: n if n and 20 <= n <= 1500 else None)(N.to_km(v, h)),
    "ev_charging_speed_kw": lambda v, h: N.to_kw(v),
    "airbags_count": lambda v, h: (lambda n: n if n and 1 <= n <= 14 else None)(N.parse_int(v)),
    "screen_size_in": lambda v, h: (lambda n: n if n and 3 <= n <= 20 else None)(N.parse_number(v)),
    "headlight_type": lambda v, h: N.to_headlight(v),
    "brake_front": lambda v, h: N.to_brake(v),
    "brake_rear": lambda v, h: N.to_brake(v),
    "mileage_km": N.to_km,
    "price": lambda v, h: N.parse_number(v),
    "currency": lambda v, h: N.clean(v),
}
for _f in BOOLEAN_FIELDS:
    CONVERTERS[_f] = lambda v, h: N.to_bool(v)

# Used instead of CONVERTERS once vehicle_type is "Motorcycle": small engines are plausible.
MOTO_CONVERTERS: dict[str, Conv] = {
    "engine_displacement_l": lambda v, h: N.to_displacement_l(v, h, moto=True),
    "horsepower_hp": lambda v, h: N.to_hp(v, h, moto=True),
}

_VALUED_LABELS = {"headlight_type", "brake_front", "brake_rear"}
_NUMERIC_FIELDS = {
    "engine_displacement_l", "engine_cylinders", "horsepower_hp", "fuel_tank_capacity_l", "seats", "doors",
    "cargo_capacity_l", "wheel_size_in", "tire_size", "fuel_economy_kml", "ev_range_km", "ev_charging_speed_kw",
    "airbags_count", "screen_size_in", "mileage_km",
}


class RecordBuilder:
    """Collects candidate values from several sources; the first valid value wins.

    Feed it the most reliable source first (structured API/JSON), then spec
    tables, then feature lists, then free text.
    """

    def __init__(self, source_site: str, source_url: str, listing_id: str):
        self.meta = {"source_site": source_site, "source_url": source_url, "listing_id": str(listing_id)}
        self.values: dict[str, Any] = {}
        self.warnings: list[str] = []
        self.unmapped: dict[str, str] = {}
        self.displacement_misses: list[str] = []   # unparsed displacements; build() warns unless EV
        self.zero_cylinders: list[str] = []        # "0 Cyl" values; build() warns unless EV
        self.body_fallback: Optional[str] = None   # vague body ("Deportivo"), used only if nothing else

    # -- primitives ---------------------------------------------------------
    def set(self, field: str, raw: Any, hint: str = "") -> bool:
        if raw is None or raw == "" or field in self.values:
            return False
        moto = self.values.get("vehicle_type") == "Motorcycle"
        conv = (moto and MOTO_CONVERTERS.get(field)) or CONVERTERS.get(field)
        value = conv(raw, hint) if conv else raw
        if value is None:
            if field == "engine_displacement_l":
                self.displacement_misses.append(N.clean(raw) or "")
            elif field == "engine_cylinders" and N.parse_number(raw) == 0:
                self.zero_cylinders.append(N.clean(raw) or "")   # "0 Cyl": an EV, see build()
            elif field in ("body_style", "vehicle_type") and N.body_fallback(raw):
                self.body_fallback = self.body_fallback or N.body_fallback(raw)   # applied in build()
            elif field not in BOOLEAN_FIELDS:
                self.warn(f"could not parse {field} from '{N.clean(raw)}'")
            return False
        self.values[field] = value
        return True

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    # -- higher level -------------------------------------------------------
    def add_pair(self, label: str, value: Any) -> Optional[str]:
        """Map a label/value pair. Returns the field it was mapped to (if any)."""
        if value is None or N.clean(value) is None:
            return None
        if isinstance(value, str) and value.strip().lower() == "null":
            return None    # some APIs (carroya) send the literal string "null" for unset fields
        field = match_label(label)
        hint = f"{label} {value}"
        if field == "model" and N.to_year(value) and re.fullmatch(r"\s*\d{4}\s*", str(value)):
            field = "model_year"            # In Colombia "Modelo: 2010" means the year
        if field in _VALUED_LABELS and N.to_bool(value) is not None:
            field = None                      # "Faros delanteros": "Sí" says nothing about the type
        if field in _NUMERIC_FIELDS and N.to_bool(value) is not None:
            field = None                      # "Con airbags": "Sí" is a feature flag, not a count
        if field == "engine_displacement_l" and _CYLINDERS_ONLY_RE.fullmatch(N.norm(value)):
            field = "engine_cylinders"        # "Engine: 6 Cyl" is a cylinder count, not 6 litres
        if field == "airbags_count" and not re.search(r"\d", str(value)):
            field = None                      # "Side Airbags": "Front and Rear" is a location, not a count
        # Rim and tire sizes entered under each other's label: "Llantas: R16", "Rin: 245-60".
        if field == "tire_size" and N.to_tire_size(value) is None and N.rim_from_tire_text(value):
            field, value = "wheel_size_in", N.rim_from_tire_text(value)
        elif field == "wheel_size_in" and N.to_inches(value) is None \
                and N.to_tire_size(str(value).replace("-", "/")):
            field, value = "tire_size", N.to_tire_size(str(value).replace("-", "/"))
        if field:
            if field == "body_style":
                self.set("vehicle_type", value)
            self.set(field, value, hint)
            return field
        # Boolean feature expressed as a pair: "Control de frenos ABS": "S"
        b = N.to_bool(value)
        if b is True:                         # "Frenos de disco en las 4 ruedas": "S"
            for f, v in match_equipment(label).items():
                self.set(f, v)
        feats = match_features(label)
        if feats and b is not None:
            for f in feats:
                self.set(f, b)
            return next(iter(feats))
        if feats and b is None:              # "Material rines": "Aleación" etc.
            for f in match_features(f"{label} {value}"):
                self.set(f, True)
            return next(iter(feats))
        if not feats:
            for f in match_features(f"{label} {value}"):
                if f == "alloy_wheels":
                    self.set(f, True)
        self.unmapped[N.clean(label) or label] = N.clean(value) or ""
        return None

    def add_pairs(self, pairs: Iterable[tuple[str, Any]]) -> None:
        for label, value in pairs:
            self.add_pair(label, value)

    def add_feature_list(self, items: Iterable[str]) -> None:
        """Items listed as present equipment -> True."""
        for item in items:
            for f in match_features(item):
                self.set(f, True)
            for f, v in match_equipment(item).items():
                self.set(f, v)
            m = re.search(r"(\d{1,2})\s*(air ?bags?|bolsas de aire)", N.norm(item))
            if m:
                self.set("airbags_count", m.group(1))

    def add_title(self, *parts: Optional[str]) -> None:
        """Listing title / model / trim name: reads only explicit body, drivetrain and door
        tokens ("Sedan", "Doble Cabina", "4x4", "4Matic", "5 Puertas"). Call it after the
        structured sources, so a real spec field always wins."""
        text = " ".join(p for p in parts if p)
        if not text:
            return
        body = N.body_from_title(text)
        if body:
            self.set("body_style", body)
            self.set("vehicle_type", body)
        drive = N.drivetrain_from_title(text)
        if drive:
            self.set("drivetrain", drive)
        disp = N.displacement_from_title(text)          # "1.4 LS Mecanico": fallback only
        if disp:
            n = len(self.displacement_misses)
            self.set("engine_displacement_l", disp)
            del self.displacement_misses[n:]             # an implausible title token isn't a warning
        doors = N.doors_from_title(text)
        if doors:
            self.set("doors", doors)

    def add_free_text(self, text: Optional[str]) -> None:
        """Seller comments: only sets True for clearly mentioned features."""
        if not text:
            return
        for line in re.split(r"[\n\r,;•·|]+", text):
            if line.strip():
                self.add_feature_list([line])
                m = re.match(r"^\s*(tipo de )?carroceria\s*:?\s*(.+)$", N.norm(line))
                if m:
                    self.set("body_style", m.group(2))
                    self.set("vehicle_type", m.group(2))
                if ":" in line:
                    label, _, value = line.partition(":")
                    f = match_label(label)
                    if f in ("seats", "doors", "airbags_count", "engine_displacement_l", "horsepower_hp"):
                        self.set(f, value, line)

    def build(self) -> VehicleRecord:
        data = dict(self.values)
        tire, rim = data.get("tire_size"), data.get("wheel_size_in")
        if tire and "R" not in tire and rim:
            data["tire_size"] = f"{tire}R{rim}"
        if self.body_fallback and "body_style" not in data and data.get("vehicle_type") != "Motorcycle":
            data["body_style"] = self.body_fallback
        if "vehicle_type" not in data and "body_style" in data:
            data["vehicle_type"] = data["body_style"]
        if data.get("fuel_type") != "EV":
            for f in ("ev_range_km", "ev_charging_speed_kw"):
                if f in data and data.get("fuel_type") not in (None, "Hybrid"):
                    data.pop(f)
        # An EV has no combustion engine: "0.0l" or a motor description ("Motor sincrónico de
        # imán permanente") under a displacement label is expected, not worth a warning.
        if data.get("fuel_type") != "EV":
            for raw in self.displacement_misses:
                if N.parse_number(raw) == 0 and "engine_displacement_l" in data:
                    continue                             # a "0.0l" placeholder, but the size is known
                self.warn(f"could not parse engine_displacement_l from '{raw}'")
            for raw in self.zero_cylinders:
                self.warn(f"could not parse engine_cylinders from '{raw}'")
        return VehicleRecord(**self.meta, **data, parse_warnings=self.warnings)
