"""Deterministic canonicalization of raw make / model / trim strings (stage 1, no AI, no tokens).

    parse_names("JEEP", "COMPASS 4X4", "Limited 2.4 Automatica")
      -> make Jeep, model "COMPASS" (key "compass"), trim "Limited",
         attrs {drivetrain: 4WD, engine_displacement_l: 2.4, transmission_type: Automatic}

Rules only remove what they can name: engine size, gearbox, body, drivetrain, fuel, door and
equipment tokens ("Aire Acondicionado", "Full Equipo"). Whatever is left is the trim. Anything
ambiguous (an unknown make, a model only seen on sites without a trim field) is flagged so the
AI step (catalog/ai_batch.py) or a person can decide; rules never guess between two models.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .. import normalize as N

MAKES_YAML = next((p for p in (Path("config/catalog/makes.yaml"),
                               Path(__file__).resolve().parents[3] / "config" / "catalog" / "makes.yaml")
                   if p.exists()), Path("config/catalog/makes.yaml"))


def key(text: object) -> str:
    """Matching key: lowercase, no accents, letters and digits only ("Rav 4" -> "rav4")."""
    return re.sub(r"[^a-z0-9]", "", N.norm(text))


def slugify(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", N.norm(text)).strip("-") or "_"


# ---------------------------------------------------------------------------
# Makes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MakeInfo:
    name: str
    slug: str
    country: Optional[str] = None
    heavy: bool = False          # builds only trucks/buses
    in_seed: bool = False        # listed in makes.yaml (an unknown make goes to review)


class MakeTable:
    def __init__(self, entries: dict):
        self._by_key: dict[str, MakeInfo] = {}
        for name, info in (entries or {}).items():
            info = info or {}
            mk = MakeInfo(name, slugify(name), info.get("country"), info.get("class") == "heavy", True)
            for alias in [name, *(info.get("aliases") or [])]:
                self._by_key[key(alias)] = mk

    @classmethod
    def load(cls, path: Path = MAKES_YAML) -> "MakeTable":
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {})

    def resolve(self, raw: object) -> MakeInfo:
        found = self._by_key.get(key(raw))
        if found:
            return found
        name = display_case(N.clean(raw) or "Unknown")
        return MakeInfo(name, slugify(name))


# ---------------------------------------------------------------------------
# Token tables (matched on lowercase, accent-free text)
# ---------------------------------------------------------------------------
_DISPLACEMENT = r"(?<![\w.,])\d[.,]\d(?:\s?(?:l|t|lts?))?(?![\w.,])|\b\d{3,4} ?(?:cc|c\.c\.?|cm3)(?!\w)"
_TRANSMISSION = (r"\b(?:automatic[oa]s?|automatica|automatic|autom|aut|a/t|at|mt|m/t|mecanic[oa]s?|"
                 r"manual|cvt|e-cvt|ivt|dsg|dct|tiptronic|steptronic|secuencial|sincronic[oa])\b\.?")
_FUEL = r"\b(?:gasolina|gasoline|petrol|diesel|hibrid[oa]|hybrid|hev|phev|mhev|electric[oa]|ev|gnv|gnc|cng)\b"
_BODY = (r"\b(?:sedan|suv|hatch ?back|hatch|hb|coupe|cupe|convertible|cabrio(?:let)?|station ?wagon|"
         r"minivan|pick ?-?up|doble cabina|cabina (?:sencilla|simple|doble)|crossover)\b")
_DRIVE = r"\b(?:4x4|4x2|2x4|4wd|2wd|awd|fwd|rwd)\b"
_DOORS = r"\b[2-5] ?(?:p|ptas|puertas|doors?)\b"
_EQUIPMENT = (r"\b(?:aire acondicionado|a\.? ?a\.?|a/c|full equipo|full equip|f\.? ?e\.?|full|"
              r"con techo|techo(?: corredizo| panoramico| solar| electrico)?|sunroof|blindad[oa]|"
              r"nivel \d)(?!\w)")
_CLASS_WORDS = {"clase", "class", "serie", "series"}        # "Clase C" == "C Class", "Serie 3" == "3 SERIES"
_STOP_WORDS = {"de", "del", "la", "el", "y", "con", "en", "the", "and", "of", "for", "plus"}

_TOKEN_RES = [re.compile(p) for p in (_EQUIPMENT, _DISPLACEMENT, _TRANSMISSION, _FUEL, _BODY, _DRIVE, _DOORS)]
_MODEL_STRIP_RES = [re.compile(p) for p in (_DRIVE, _DISPLACEMENT)]


def _fold(s: str) -> str:
    """Same length as ``s``: each char accent-stripped and lowercased, so spans map back 1:1."""
    return "".join(((N.strip_accents(c) or c)[:1]).lower() for c in s)


def _cut(s: str, regexes) -> str:
    folded = _fold(s)
    spans = sorted((m.start(), m.end()) for rx in regexes for m in rx.finditer(folded))
    out, pos = [], 0
    for a, b in spans:
        if a >= pos:
            out.append(s[pos:a])
            pos = b
        elif b > pos:
            pos = b
    out.append(s[pos:])
    return _tidy(" ".join(out))


def _tidy(s: str) -> str:
    s = re.sub(r"\(\s*\)|\[\s*\]", " ", s)
    s = re.sub(r"\s*([/,+-])\s*(?=[/,+-]|$)", " ", s)            # dangling separators
    s = re.sub(r"\s+", " ", s).strip(" -/,.+|:;")
    return s


def display_case(text: str) -> str:
    """Consistent casing for names: 'LIMITED' / 'limited' -> 'Limited', 'ltz' -> 'LTZ';
    mixed-case and alphanumeric tokens are kept ('XEi-L', '320i', 'Grand i10')."""
    def part(p: str, first: bool) -> str:
        alpha = re.sub(r"[^A-Za-z]", "", p)
        if not alpha or any(c.isdigit() for c in p) or not (p.isupper() or p.islower()):
            return p
        if p.lower() in _STOP_WORDS and not first:
            return p.lower()
        return p.upper() if len(alpha) <= 3 else p[:1].upper() + p[1:].lower()

    out = []
    for tok in text.split():
        if not (tok.isupper() or tok.islower()):
            out.append(tok)                                  # mixed case: the seller's casing
        else:                                                 # "T-CROSS" -> "T-Cross", "x-trail" -> "X-Trail"
            out.append("-".join(part(p, not out and i == 0) for i, p in enumerate(tok.split("-"))))
    return " ".join(out)


# ---------------------------------------------------------------------------
# Models and trims
# ---------------------------------------------------------------------------
def model_key(model_text: object) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", N.norm(model_text)) if w not in _CLASS_WORDS]
    return "".join(words) or key(model_text)


def title_attrs(text: str) -> dict:
    """Explicit attributes written in a model/trim text. Only clear tokens count."""
    t = N.norm(text)
    attrs: dict = {}
    disp = N.displacement_from_title(t)
    if disp is None:
        m = re.search(r"\b(\d{3,4}) ?(?:cc|c\.c|cm3)\b", t)
        disp = m and str(int(m.group(1)) / 1000)
    if disp:
        litres = N.parse_number(disp.replace(",", "."))
        if litres and 0.05 <= litres <= 10:
            attrs["engine_displacement_l"] = round(litres, 1) if litres >= 0.5 else round(litres, 3)
    m = re.search(_TRANSMISSION, t)
    if m:
        tok = m.group(0).rstrip(".")
        tr = "Automatic" if tok in ("aut", "autom", "a/t") else N.to_transmission(tok)
        if tok == "m/t":
            tr = "Manual"
        if tr:
            attrs["transmission_type"] = tr
    m = re.search(_FUEL, t)
    if m and (fuel := N.to_fuel(m.group(0))):
        attrs["fuel_type"] = fuel
    if body := N.body_from_title(t):
        attrs["body_style"] = body
    if drive := N.drivetrain_from_title(t):
        attrs["drivetrain"] = drive
    if doors := N.doors_from_title(t):
        attrs["doors"] = doors
    return attrs


def clean_model(raw_model: object) -> tuple[str, dict]:
    """Model text without drivetrain / engine-size tokens ('Q7 4X4' -> 'Q7'), plus those attrs."""
    text = html.unescape(N.clean(raw_model) or "")
    attrs = {k: v for k, v in title_attrs(text).items() if k in ("drivetrain", "engine_displacement_l")}
    return _cut(text, _MODEL_STRIP_RES) or text, attrs


def clean_trim(raw_trim: object, model_text: str = "") -> tuple[str, dict]:
    """Trim text with spec/equipment tokens removed and consistent casing, plus the specs found."""
    text = html.unescape(N.clean(raw_trim) or "")
    if not text:
        return "", {}
    attrs = title_attrs(text)
    rest = _cut(text, _TOKEN_RES)
    if model_text and _fold(rest).startswith(_fold(model_text) + " "):   # "Corolla XEi" under Corolla
        rest = rest[len(model_text):].strip()
    return display_case(rest), attrs


def split_known_prefix(model_text: str, known_keys: set[str]) -> tuple[str, str]:
    """'TAHOE LTZ' with 'tahoe' known -> ('TAHOE', 'LTZ'). Longest known prefix wins;
    returns (model_text, '') when no proper prefix is a known model."""
    tokens = model_text.split()
    for i in range(len(tokens) - 1, 0, -1):
        if model_key(" ".join(tokens[:i])) in known_keys:
            return " ".join(tokens[:i]), " ".join(tokens[i:])
    return model_text, ""


@dataclass
class ParsedNames:
    make: MakeInfo
    model_text: str
    model_key: str
    trim_text: str
    trim_key: str
    attrs: dict = field(default_factory=dict)      # specs read from the model/trim text
    model_split: bool = False                       # trim words were moved out of the model text


def parse_names(raw_make: object, raw_model: object, raw_trim: object, makes: MakeTable,
                known_models: Optional[set[str]] = None) -> ParsedNames:
    """``known_models``: model keys of this make that are verified. When given and the model
    isn't one of them, a known model prefix is split off and the rest becomes trim text."""
    mk = makes.resolve(raw_make)
    model_text, attrs = clean_model(raw_model)
    split = False
    if known_models is not None and model_key(model_text) not in known_models:
        head, rest = split_known_prefix(model_text, known_models)
        if rest:
            model_text, raw_trim, split = head, f"{rest} {raw_trim or ''}".strip(), True
    trim_text, trim_attrs = clean_trim(raw_trim, model_text)
    attrs = {**trim_attrs, **attrs}
    return ParsedNames(mk, model_text, model_key(model_text), trim_text, key(trim_text), attrs, split)
