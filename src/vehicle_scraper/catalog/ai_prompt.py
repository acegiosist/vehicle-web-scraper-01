"""Prompt, output schema and request rendering for the AI catalog step (stage 3).

Token budget rules baked in here:
* SYSTEM_PROMPT is static and byte-identical in every request, so it is cached once
  (``cache_control`` with a 1-hour TTL) and read at a fraction of the price afterwards.
  Never interpolate dates, counts or IDs into it.
* The per-request data is compact TSV, one line per unique model / unique raw model+trim
  string of one make, never one line per listing.
* The answer is constrained JSON with short fields; the model returns decisions only for the
  lines it is asked about.
Bump PROMPT_VERSION whenever SYSTEM_PROMPT or OUTPUT_SCHEMA changes: memoized decisions are keyed
by it, so a new version re-asks only when you want it to.
"""
from __future__ import annotations

from typing import get_args

from ..models import Drivetrain, FuelType, TransmissionType, VehicleType

PROMPT_VERSION = "v1"
MODEL = "claude-opus-5-5"
EFFORT = "low"          # thinking can't be turned off on Opus 5.5; effort is the cost control
MAX_TOKENS = 16000

_BODY = [b for b in get_args(VehicleType) if b != "Motorcycle"]
_ENUMS = {
    "body_style": _BODY,
    "fuel_type": list(get_args(FuelType)),
    "transmission_type": list(get_args(TransmissionType)),
    "drivetrain": list(get_args(Drivetrain)),
    "vehicle_class": ["car", "moto", "heavy"],
}

SYSTEM_PROMPT = f"""You normalize a used-vehicle catalog for a Latin American and Indian car marketplace.
Listings were scraped from several sites (Colombia, Guatemala, India, United States). Rules already
cleaned the obvious noise; you get only the cases they could not settle, for ONE make per request.

The user message has up to three TSV sections:
- MODELS: model clusters to decide. Columns: id, name (current display name), spellings (raw
  spellings seen, "/"-separated), n (listings), markets (country codes), years (min-max),
  body (most common body style in listings, "-" if none), class (car/moto/heavy), flags
  ("unverified" = only seen on sites without a separate trim field, so the model name may
  still contain a trim, or may not be a real model name).
- KNOWN: models of this make that are already settled, as "id=Name" pairs, for context only.
  Use them to detect duplicates (merge_into) and to assign trims; never return decisions for them.
- TRIMS: unique raw model/trim strings to decide. Columns: id, model (id of its current model),
  raw_model, raw_trim, parsed_trim (what the rules kept as the trim), n, years, and the evidence
  from listings: cc (engine litres), fuel, gear, body, drive ("-" = unknown).

For every MODELS line return one model decision:
- action: "keep" (name is right), "rename" (same model, better official name, e.g. "Rav 4" ->
  "RAV4", "CRV" -> "CR-V", "New Wagon-R" -> "Wagon R"), "merge" (duplicate of another model id from
  MODELS or KNOWN; set merge_into), or "not_a_model" (the name is a trim, a typo you cannot map, or
  not a vehicle model of this make).
- canonical_name: the official model name as the manufacturer writes it in that market, without
  engine size, gearbox, drivetrain, fuel or trim words ("Fortuner", not "FORTUNER SRV 4X4").
  If the cluster name contains a trim, keep the model part and say so in note.
- vehicle_class: car, moto or heavy (trucks, buses, tractor units).
- body_style and body_source: the usual body style of this model. body_source = "title" when the
  names or spellings state it (e.g. "Doble Cabina"), "ai_knowledge" when it comes from what you know
  about the model, null when you are not sure (then body_style is null). Use null for motorcycles.
- confidence: 0 to 1. Use < 0.7 whenever you are guessing.

For every TRIMS line return one trim decision:
- model_id: the id (from MODELS or KNOWN) of the model this string belongs to. Usually the line's
  own model; change it only when the raw text clearly names another model.
- trim_name: the trim/version name only, in the manufacturer's casing ("XEi-L", "LTZ", "Highline",
  "VXi"), with engine size, gearbox, body, drivetrain, fuel, door count and equipment words
  ("Aire Acondicionado", "Full Equipo", "Techo") removed. Empty string when the text has no trim.
- engine_displacement_l, transmission_type, fuel_type, drivetrain, body_style, doors: ONLY values
  written in raw_model/raw_trim (not your knowledge); null otherwise. Spanish hints: "Mecánica" /
  "MT" = Manual, "Automática" / "AT" / "Aut" = Automatic, "4x2" = 2WD, "4x4" = 4WD, "Diésel" /
  "ACPM" = Diesel, "Híbrido" = Hybrid, "Eléctrico" / "EV" = EV, "GNV" = CNG.
- confidence: 0 to 1.

Rules:
- Never invent a model, trim or spec. When unsure, lower confidence and explain in note (max 15 words).
- Listing evidence wins: if a value written in the text contradicts the evidence columns, still
  report what the text says, set confidence < 0.7 and mention the conflict in note.
- Allowed values: body_style {", ".join(_BODY)}; fuel_type {", ".join(_ENUMS["fuel_type"])};
  transmission_type {", ".join(_ENUMS["transmission_type"])}; drivetrain {", ".join(_ENUMS["drivetrain"])}
  ("2WD" = 4x2 with front/rear not stated).
- Return exactly one decision per MODELS line and per TRIMS line, using the ids given; nothing else.

Example. MODELS line "m1\tCRV\tCRV/CR-V/CR-V VTEC 4X4\t24\tCO,IN\t2008-2022\tSUV\tcar\t" ->
{{"id":"m1","action":"rename","canonical_name":"CR-V","merge_into":null,"vehicle_class":"car",
"body_style":"SUV","body_source":"title","confidence":0.97,"note":""}}.
TRIMS line "t1\tm1\tCR-V 1.5T 5DR 2WDEX\t-\t1.5T 5Dr 2WDEX\t2\t2019\t1.5\tGasoline\tAutomatic\t-\t-" ->
{{"id":"t1","model_id":"m1","trim_name":"EX","engine_displacement_l":1.5,"transmission_type":null,
"fuel_type":null,"drivetrain":"2WD","body_style":null,"doors":5,"confidence":0.85,"note":"1.5T turbo, 5 doors"}}.
"""


def _nullable_enum(values: list[str]) -> dict:
    return {"anyOf": [{"type": "string", "enum": values}, {"type": "null"}]}


_NUM_OR_NULL = {"anyOf": [{"type": "number"}, {"type": "null"}]}
_INT_OR_NULL = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
_STR_OR_NULL = {"anyOf": [{"type": "string"}, {"type": "null"}]}

_MODEL_ITEM = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "action": {"type": "string", "enum": ["keep", "rename", "merge", "not_a_model"]},
        "canonical_name": {"type": "string"},
        "merge_into": _STR_OR_NULL,
        "vehicle_class": {"type": "string", "enum": _ENUMS["vehicle_class"]},
        "body_style": _nullable_enum(_BODY),
        "body_source": _nullable_enum(["title", "ai_knowledge"]),
        "confidence": {"type": "number"},
        "note": {"type": "string"},
    },
    "required": ["id", "action", "canonical_name", "merge_into", "vehicle_class", "body_style",
                 "body_source", "confidence", "note"],
    "additionalProperties": False,
}
_TRIM_ITEM = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "model_id": {"type": "string"},
        "trim_name": {"type": "string"},
        "engine_displacement_l": _NUM_OR_NULL,
        "transmission_type": _nullable_enum(_ENUMS["transmission_type"]),
        "fuel_type": _nullable_enum(_ENUMS["fuel_type"]),
        "drivetrain": _nullable_enum(_ENUMS["drivetrain"]),
        "body_style": _nullable_enum(_BODY),
        "doors": _INT_OR_NULL,
        "confidence": {"type": "number"},
        "note": {"type": "string"},
    },
    "required": ["id", "model_id", "trim_name", "engine_displacement_l", "transmission_type", "fuel_type",
                 "drivetrain", "body_style", "doors", "confidence", "note"],
    "additionalProperties": False,
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"models": {"type": "array", "items": _MODEL_ITEM},
                   "trims": {"type": "array", "items": _TRIM_ITEM}},
    "required": ["models", "trims"],
    "additionalProperties": False,
}

MODEL_COLUMNS = ["id", "name", "spellings", "n", "markets", "years", "body", "class", "flags"]
TRIM_COLUMNS = ["id", "model", "raw_model", "raw_trim", "parsed_trim", "n", "years", "cc", "fuel", "gear",
                "body", "drive"]


def _cell(v) -> str:
    if v is None or v == "":
        return "-"
    return str(v).replace("\t", " ").replace("\n", " ").strip() or "-"


def render_user(make_name: str, models: list[dict], known: list[tuple[str, str]], trims: list[dict]) -> str:
    """The per-request message. ``models``/``trims`` are dicts keyed by MODEL_COLUMNS/TRIM_COLUMNS."""
    out = [f"MAKE: {make_name}"]
    if models:
        out += ["", "MODELS", "\t".join(MODEL_COLUMNS)] + ["\t".join(_cell(m.get(c)) for c in MODEL_COLUMNS) for m in models]
    if known:
        out += ["", "KNOWN", ", ".join(f"{i}={name}" for i, name in known)]
    if trims:
        out += ["", "TRIMS", "\t".join(TRIM_COLUMNS)] + ["\t".join(_cell(t.get(c)) for c in TRIM_COLUMNS) for t in trims]
    return "\n".join(out)


def request_params(user_text: str) -> dict:
    """Messages API params for one batch request (same shape for count_tokens)."""
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        "messages": [{"role": "user", "content": user_text}],
        "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    }
