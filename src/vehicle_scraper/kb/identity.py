"""Identity helpers for ``kb clean``: spelling keys, display names, the make list, and the
token splitting that moves mechanical words out of model and trim names.

Adapted from the earlier knowledge base branch (``feat/knowledge-base``): ``compact_key``,
``display_name``, the make seed and ``split_number`` are the same ideas; ``split_tokens`` now
also returns the attribute each removed word stands for, so the cleaner can fill an empty
field from it or flag a conflict with the listing's structured field.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Optional

import yaml

from .. import normalize as N

SEED_PATH = Path(__file__).resolve().parents[3] / "config" / "kb" / "makes.yaml"
IN_SCOPE_CLASSES = ("car", "motorcycle")
# Make class -> kb.exclusion_reason code for makes whose listings are out of scope.
EXCLUDED_CLASSES = {"heavy": "Heavy", "machinery": "Machinery", "golf_cart": "GolfCart",
                    "bicycle": "Bicycle", "trailer": "Trailer", "atv": "ATV"}
MAKE_CLASSES = IN_SCOPE_CLASSES + tuple(EXCLUDED_CLASSES)


def compact_key(text: object) -> str:
    """Spelling-insensitive key: 'Rav 4' / 'RAV4' / 'rav-4' -> 'rav4'."""
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def slugify(text: object) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "unknown"


def display_name(spellings: Counter) -> str:
    """Most frequent spelling, preferring one that isn't ALL CAPS; an all-caps name is
    title-cased word by word, except short or alphanumeric tokens (GTI, CX-30, RAV4)."""
    mixed = [(n, s) for s, n in spellings.items() if s and not s.isupper()]
    if mixed:
        return max(mixed)[1].strip()
    best = max(((n, s) for s, n in spellings.items() if s), default=(0, ""))[1].strip()

    def fix(word: str) -> str:
        return word if len(word) <= 3 or any(c.isdigit() for c in word) else word.capitalize()
    return " ".join("-".join(fix(p) for p in w.split("-")) for w in best.split())


# --- make list ------------------------------------------------------------------------------
def load_seed(path: Path = SEED_PATH) -> dict:
    """``{"makes": [...], "split_models": [...]}`` from makes.yaml, validated."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    makes = data.get("makes") or []
    seen: dict[str, str] = {}
    for m in makes:
        if m.get("class") not in MAKE_CLASSES:
            raise ValueError(f"{path}: make {m.get('name')!r} has unknown class {m.get('class')!r}")
        for spelling in [m["name"], *(m.get("aliases") or [])]:
            k = compact_key(spelling)
            if k in seen and seen[k] != m["name"]:
                raise ValueError(f"{path}: {spelling!r} is listed under {seen[k]!r} and {m['name']!r}")
            seen[k] = m["name"]
    return {"makes": makes, "split_models": data.get("split_models") or []}


# --- token splitting ------------------------------------------------------------------------
# Multi-word phrases first, rewritten to one token so the word loop below sees them.
_PHRASES = [
    (r"\bpick[ -]?up\b", "pickup"),
    (r"\bdoble cabina\b|\bdouble cab\b|\bcrew cab\b|\bsupercrew\b", "dc"),
    (r"\bcabina (sencilla|simple)\b|\bregular cab\b|\bsingle cab\b", "cs"),
    (r"\baire acondicionado\b|\ba/a\b", "aa"),
    (r"\bfull equipo\b", "full"),
    (r"\b([2-5]) ?(puertas|ptas|doors?)\b", r"\1p"),
]
_DISPLACEMENT = re.compile(r"^\d[.,]\d{1,2}[lt]?$")
_ATTRS: dict[str, tuple[str, object]] = {
    # drivetrain
    "4x4": ("drivetrain", "4WD"), "4wd": ("drivetrain", "4WD"), "awd": ("drivetrain", "AWD"),
    "4matic": ("drivetrain", "AWD"), "quattro": ("drivetrain", "AWD"), "xdrive": ("drivetrain", "AWD"),
    "4motion": ("drivetrain", "AWD"), "4x2": ("drivetrain", "2WD"), "2wd": ("drivetrain", "2WD"),
    "2x4": ("drivetrain", "2WD"), "fwd": ("drivetrain", "FWD"), "rwd": ("drivetrain", "RWD"),
    # transmission
    "aut": ("transmission_type", "Automatic"), "auto": ("transmission_type", "Automatic"),
    "automatica": ("transmission_type", "Automatic"), "automatico": ("transmission_type", "Automatic"),
    "automatic": ("transmission_type", "Automatic"), "at": ("transmission_type", "Automatic"),
    "tiptronic": ("transmission_type", "Automatic"), "steptronic": ("transmission_type", "Automatic"),
    "mt": ("transmission_type", "Manual"), "mec": ("transmission_type", "Manual"),
    "mecanica": ("transmission_type", "Manual"), "mecanico": ("transmission_type", "Manual"),
    "manual": ("transmission_type", "Manual"), "cvt": ("transmission_type", "CVT"),
    "ivt": ("transmission_type", "CVT"), "dct": ("transmission_type", "DCT"), "dsg": ("transmission_type", "DCT"),
    # fuel
    "diesel": ("fuel_type", "Diesel"), "turbodiesel": ("fuel_type", "Diesel"), "crdi": ("fuel_type", "Diesel"),
    "tdi": ("fuel_type", "Diesel"), "hybrid": ("fuel_type", "Hybrid"), "hibrido": ("fuel_type", "Hybrid"),
    "hibrida": ("fuel_type", "Hybrid"), "hev": ("fuel_type", "Hybrid"), "phev": ("fuel_type", "Hybrid"),
    "mhev": ("fuel_type", "Hybrid"), "gasolina": ("fuel_type", "Gasoline"), "electrico": ("fuel_type", "EV"),
    "electrica": ("fuel_type", "EV"), "electric": ("fuel_type", "EV"), "ev": ("fuel_type", "EV"),
    "gnv": ("fuel_type", "CNG"), "cng": ("fuel_type", "CNG"), "flex": ("fuel_type", "Flex"),
    # body
    "sedan": ("body_style", "Sedan"), "hatchback": ("body_style", "Hatchback"), "hb": ("body_style", "Hatchback"),
    "suv": ("body_style", "SUV"), "coupe": ("body_style", "Coupe"), "wagon": ("body_style", "Wagon"),
    "van": ("body_style", "Van"), "furgon": ("body_style", "Van"), "pickup": ("body_style", "Pickup"),
    "dc": ("body_style", "Pickup"), "cs": ("body_style", "Pickup"), "convertible": ("body_style", "Convertible"),
    "cabriolet": ("body_style", "Convertible"),
    # doors
    "2p": ("doors", 2), "3p": ("doors", 3), "4p": ("doors", 4), "5p": ("doors", 5),
    # engine
    "turbo": ("turbo", True),
}
# Removed from names without saying anything about the car.
_NOISE = {"new", "nuevo", "nueva", "full", "equipo", "aa", "dh", "fe", "cab", "cabina", "platon",
          "chasis", "traccion", "gas", "petrol", "puertas", "ptas"}
# Only these are taken out of a *model* name: a model like "Wagon R" or "Sport" keeps its words.
_MODEL_FIELDS = {"drivetrain", "fuel_type", "engine_displacement_l", "engine_cylinders"}
_MODEL_NOISE = {"new", "nuevo", "nueva"}


def _norm_token(token: str) -> str:
    return N.norm(token).strip(".,;:()[]")


def split_tokens(raw: Optional[str], *, model: bool = False, moto: bool = False) -> tuple[Optional[str], dict]:
    """Name without mechanical words, plus what those words said.

    Trim: ``'Touring 2.0 Suv Automatico 4x2'`` -> ``('Touring', {engine_displacement_l: 2.0,
    body_style: SUV, transmission_type: Automatic, drivetrain: 2WD})``; a trim of nothing but
    attributes (``'2.8 DC 4x4 Diésel'``) gives ``None`` as the name.

    ``model=True`` is stricter (only drivetrain, fuel, displacement and V6/V8 come out): ``'RAV4
    HYBRID 4X4'`` -> ``('RAV4', {...})``. The name is ``None`` when nothing else is left
    (``'1.3'``, ``'5.2 V8'``). ``moto``: numbers stay in the name (``'150 FI'``).
    The first value of each attribute wins (``'2.0 1.8'`` gives 2.0)."""
    text = str(raw or "")
    low = N.norm(text)
    for pattern, repl in _PHRASES:
        low = re.sub(pattern, repl, low)
    # Map normalized tokens back to the original spelling for the kept words.
    orig = [t for t in re.split(r"\s+", text.strip()) if t]
    orig_by_norm: dict[str, str] = {}
    for t in orig:
        orig_by_norm.setdefault(_norm_token(t), t)
    kept, attrs = [], {}
    removed_word = False
    for tok in [t for t in re.split(r"\s+", low.strip()) if t]:
        n = tok.strip(".,;:()[]")
        if not n:
            continue
        attr = None
        if _DISPLACEMENT.match(n) and not moto:
            attr = ("engine_displacement_l", float(n.rstrip("lt").replace(",", ".")))
        elif re.fullmatch(r"v(6|8|10|12)", n):
            attr = ("engine_cylinders", int(n[1:]))
        elif n in _ATTRS:
            attr = _ATTRS[n]
        if attr and (not model or attr[0] in _MODEL_FIELDS):
            attrs.setdefault(attr[0], attr[1])
            removed_word = removed_word or n in _ATTRS
            continue
        if (n in _MODEL_NOISE) if model else (n in _NOISE or re.fullmatch(r"\d{1,2}v", n) or attr):
            continue                                  # "16V", "Full Equipo", "A/A"
        kept.append(orig_by_norm.get(n, tok))
    name = " ".join(kept).strip(" -/.,")
    if model and not name and removed_word:
        return text.strip() or None, {}               # the word *is* the model: Ford "Flex"
    return (name or None), attrs


_MODEL_NUMBER = re.compile(r"^\d{2,4}$")


def split_number(label: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Leading model number of a (cleaned) trim label: '150 Bus' -> ('150', 'Bus'),
    '452' -> ('452', None), 'LS 150' -> (None, 'LS 150'). Used only for model families."""
    toks = str(label or "").split()
    if toks and _MODEL_NUMBER.match(toks[0]):
        return toks[0], " ".join(toks[1:]) or None
    return None, label
