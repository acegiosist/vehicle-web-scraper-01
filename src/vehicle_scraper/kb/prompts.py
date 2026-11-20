"""Prompts and output schemas for the Claude batches. Deterministic on purpose: the same
input gives the same bytes, so the cached system prefix is reused and input hashes are
stable (memoization: an identical request is never sent twice)."""
from __future__ import annotations

import hashlib

from .db import dumps
from .fields import EQUIP_FIELDS, MECH_FIELDS, enum_values

PROMPT_VERSION = "2026-11-20.1"

FUEL = enum_values("fuel_type")
TRANSMISSION = enum_values("transmission_type")
DRIVETRAIN = enum_values("drivetrain")
BODY = [b for b in enum_values("body_style") if b != "Motorcycle"]
CLASSES = ["car", "motorcycle", "heavy"]

IDENTITY_SYSTEM = f"""Eres un experto en catálogos de vehículos de los mercados de Colombia, Guatemala e India
(carros, motos y vehículos pesados). Recibes, para UNA marca, nombres de modelos y versiones
tal como los escribieron vendedores de autos usados, con número de anuncios y años vistos.
Unas reglas ya unificaron mayúsculas, acentos y espacios: solo ves lo que ellas no resolvieron.
KNOWN_MODELS son modelos de esta marca ya aceptados; puedes fusionar con ellos.

Para la MARCA (solo si viene marcada como unresolved) decide:
- canonical_name: nombre oficial del fabricante.
- is_vehicle_make: false si no es un fabricante de vehículos (remolques, carrocerías,
  maquinaria agrícola o de construcción, nombres genéricos).
- same_as_known_make: si es otra grafía o submarca de una marca conocida, su nombre; si no, null.

Para cada MODELO decide:
- canonical_name: nombre comercial del fabricante ("RAV4", "Land Cruiser Prado").
- is_real_model: si es un modelo que esta marca vendió. Si parece de otra marca, dilo en wrong_make.
- merge_into_id: id de otro grupo (de MODELS o KNOWN_MODELS) que sea el mismo modelo, o null.
- moved_attributes: atributos que estaban en el nombre y no son el modelo ("4X4", "HYBRID", "2.8").
- vehicle_class: car | motorcycle | heavy.
- year_from / year_to: periodo de producción en estos mercados, si lo sabes (si no, null).
- suspicious_years: años de la lista fuera de ese periodo.
Para cada VERSIÓN decide:
- canonical_trim: el nombre de la versión sin atributos técnicos ("SRV", "LTZ"), o null.

Reglas:
- Si no estás seguro, status = "unsure" con una razón corta. Nunca adivines.
- source = "text" si sale del texto recibido, "knowledge" si sale de tu conocimiento.
- confidence entre 0 y 1.
- Enums permitidos: fuel_type {'|'.join(FUEL)}; transmission_type {'|'.join(TRANSMISSION)};
  drivetrain {'|'.join(DRIVETRAIN)} (4x2 sin más datos = 2WD); body_style {'|'.join(BODY)}.
Responde solo con el JSON del esquema."""

SPECS_SYSTEM = """Eres ingeniero de producto automotriz y conoces las fichas técnicas de fábrica de los
vehículos vendidos en Colombia, Guatemala e India. Recibes variantes de UN modelo
(marca, modelo, versión, año, mercado y las especificaciones ya conocidas, con su origen).
Completa SOLO los campos listados en "missing" de cada variante.

Reglas:
- Todas las variantes son de UN mercado (país). El equipamiento debe ser el de ese país;
  la parte mecánica puede venir de cualquier mercado donde se vendió esa misma configuración.
- Usa la ficha de fábrica de ese mercado y año. Si la versión tuvo varias configuraciones y
  no puedes saber cuál es, omite el campo.
- Unidades: litros (motor, tanque, maletero), hp, km/L, pulgadas (rin, pantalla), km, kW.
  Escribe el valor con su unidad ("65 L", "150 hp", "17 in", "15.2 km/L").
- Equipamiento: "true" solo si es de serie en esa versión; "false" solo si sabes que no lo
  trae; si no lo sabes, omite el campo. No marques opcionales como de serie.
- Da confidence (0-1) por campo. Si es menor a 0.6, omite el campo.
- Si un valor ya conocido parece erróneo (ej. moto BMW G 310 con 1.0 L), repórtalo en
  suspect_known con el valor que esperarías y por qué. No lo cambies tú.
Responde solo con el JSON del esquema."""


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_STATUS = {"type": "string", "enum": ["ok", "unsure"]}

IDENTITY_SCHEMA = _obj({
    "make": _nullable(_obj({
        "canonical_name": {"type": "string"},
        "is_vehicle_make": {"type": "boolean"},
        "same_as_known_make": _nullable({"type": "string"}),
        "status": _STATUS, "confidence": {"type": "number"}, "reason": {"type": "string"},
    })),
    "models": {"type": "array", "items": _obj({
        "id": {"type": "integer"},
        "canonical_name": {"type": "string"},
        "is_real_model": {"type": "boolean"},
        "wrong_make": _nullable({"type": "string"}),
        "merge_into_id": _nullable({"type": "integer"}),
        "moved_attributes": {"type": "array", "items": {"type": "string"}},
        "vehicle_class": {"type": "string", "enum": CLASSES},
        "year_from": _nullable({"type": "integer"}),
        "year_to": _nullable({"type": "integer"}),
        "suspicious_years": {"type": "array", "items": {"type": "integer"}},
        "status": _STATUS, "confidence": {"type": "number"},
        "source": {"type": "string", "enum": ["text", "knowledge"]},
        "reason": {"type": "string"},
    })},
    "trims": {"type": "array", "items": _obj({
        "id": {"type": "integer"},
        "canonical_trim": _nullable({"type": "string"}),
        "status": _STATUS, "confidence": {"type": "number"},
    })},
})

SPECS_FIELDS = MECH_FIELDS + EQUIP_FIELDS
SPECS_SCHEMA = _obj({
    "variants": {"type": "array", "items": _obj({
        "id": {"type": "integer"},
        "values": {"type": "array", "items": _obj({
            "field": {"type": "string", "enum": SPECS_FIELDS},
            "value": {"type": "string"},
            "confidence": {"type": "number"},
        })},
        "suspect_known": {"type": "array", "items": _obj({
            "field": {"type": "string"},
            "known_value": {"type": "string"},
            "expected_value": {"type": "string"},
            "reason": {"type": "string"},
        })},
    })},
})


def _tsv(header: list[str], rows: list[list]) -> str:
    def cell(v):
        if v is None:
            return ""
        if isinstance(v, (list, tuple)):
            return " / ".join(str(x) for x in v)
        return str(v).replace("\t", " ").replace("\n", " ")
    return "\n".join(["\t".join(header)] + ["\t".join(cell(v) for v in r) for r in rows])


def identity_user(make: dict, models: list[dict], known: list[dict], trims: list[dict]) -> str:
    """make: {name, unresolved}; models: [{id, spellings, n, years, sites}];
    known: [{id, name}]; trims: [{id, model_id, raw, n}]. Rows sorted for byte stability."""
    parts = [f"MARCA: {make['name']}" + (" (unresolved)" if make.get("unresolved") else "")]
    parts.append("MODELS\n" + _tsv(["id", "spellings", "n", "years", "sites"],
                                  [[m["id"], sorted(m["spellings"]), m["n"], m["years"], sorted(m["sites"])]
                                   for m in sorted(models, key=lambda m: m["id"])]))
    if known:
        parts.append("KNOWN_MODELS\n" + _tsv(["id", "name"], [[k["id"], k["name"]] for k in sorted(known, key=lambda k: k["id"])]))
    if trims:
        parts.append("TRIMS\n" + _tsv(["id", "model_id", "raw", "n"],
                                     [[t["id"], t["model_id"], t["raw"], t["n"]]
                                      for t in sorted(trims, key=lambda t: (t["model_id"], t["id"]))]))
    return "\n\n".join(parts)


def specs_user(make: str, model: str, country: str, variants: list[dict]) -> str:
    """variants: [{id, trim, year, displacement_l, fuel_type, transmission_type, drivetrain,
    known: {field: [value, source]}, missing: [field]}]"""
    rows = []
    for v in sorted(variants, key=lambda v: v["id"]):
        known = "; ".join(f"{f}={val} ({src})" for f, (val, src) in sorted(v["known"].items()))
        rows.append([v["id"], v.get("trim"), v["year"], v.get("displacement_l"), v.get("fuel_type"),
                     v.get("transmission_type"), v.get("drivetrain"), known, ",".join(sorted(v["missing"]))])
    return (f"MARCA: {make}\nMODELO: {model}\nMERCADO: {country}\n\nVARIANTS\n"
            + _tsv(["id", "trim", "year", "displacement_l", "fuel_type", "transmission_type", "drivetrain",
                    "known", "missing"], rows))


def request_params(kind: str, user: str, effort: str, model: str = "claude-opus-5-5") -> dict:
    system, schema, max_tokens = ((IDENTITY_SYSTEM, IDENTITY_SCHEMA, 16000) if kind == "identity"
                                  else (SPECS_SYSTEM, SPECS_SCHEMA, 32000))
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    }


def input_hash(params: dict) -> str:
    return hashlib.sha256(f"{PROMPT_VERSION}|{dumps(params)}".encode()).hexdigest()
