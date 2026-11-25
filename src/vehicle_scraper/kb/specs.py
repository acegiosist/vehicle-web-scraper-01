"""``kb specs export`` / ``kb specs import``: capturing what listings don't carry, from a source.

Export writes a .xlsx with the generations and powertrains that have listings and lack at least
one value, most listings first, each row pre-filled with what the base has now:

* "Generaciones": the official cycle (year from / to), segment, dimensions, doors, seats, cargo
  and fuel tank;
* "Trenes motrices": engine code and name, power, torque, gears, cylinders, fuel economy, EV
  range and charging;
* "Instrucciones".

A person fills the gaps from a source (a maker's sheet, a magazine) and writes it in "fuente"
(required on every row that changes something). Import reads the file back:

* a value different from the current one becomes **external evidence, accepted**, with the
  source, the person and the note in its ``detail`` and ``source_code = 'captura'``: it beats
  the listings and the automatic sources (``kb/sources``) and loses to a manual value
  (``levels.SOURCE_RANK``). Importing again replaces the earlier captured value;
* blank cells and unchanged values do nothing (a blank never deletes);
* the cycle is the generation's identity, so a different cycle opens a ``generation_cycle``
  case instead (migration 0014); listings move only after a person approves it;
* every value is validated (numbers in range, a segment that fits the model's class and body,
  a year range); a row with an error is reported and skipped, the other rows are saved.

Then, unless ``rebuild=False``, ``kb build`` runs in the same transaction, so the values publish
at once and a failure leaves nothing half done.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from typing import Optional

from ..xlsx import Sheet, read_sheet, write_workbook
from .db import take_writer_lock
from .identity import compact_key
from .levels import RANGES
from .review import InvalidDecision, _year, check_cycle, parse_value

GENERATIONS, POWERTRAINS = "Generaciones", "Trenes motrices"
CYCLE = ("year_from", "year_to")
# sheet header -> column, in display order
GENERATION_FIELDS = [("año inicio", "year_from"), ("año fin", "year_to"), ("segmento", "segment_code"),
                     ("largo mm", "length_mm"), ("ancho mm", "width_mm"), ("alto mm", "height_mm"),
                     ("distancia entre ejes mm", "wheelbase_mm"), ("puertas", "doors"), ("asientos", "seats"),
                     ("maletero L", "cargo_capacity_l"), ("tanque L", "fuel_tank_capacity_l")]
POWERTRAIN_FIELDS = [("código de motor", "engine_code"), ("nombre de motor", "engine_name"),
                     ("potencia hp", "horsepower_hp"), ("torque Nm", "torque_nm"), ("velocidades", "gears"),
                     ("cilindros", "engine_cylinders"), ("consumo km/L", "fuel_economy_kml"),
                     ("autonomía eléctrica km", "ev_range_km"), ("carga rápida kW", "ev_charging_speed_kw")]
GENERATION_KEYS = ["id", "marca", "modelo", "generación", "carrocería", "años vistos", "anuncios"]
POWERTRAIN_KEYS = ["id", "marca", "generación", "cilindraje L", "combustible", "transmisión", "tracción",
                   "anuncios"]
TAIL = ["fuente", "nota"]
TEXT = {"engine_code", "engine_name"}
TEXT_MAX = 80
# Plausible ranges for captured numbers (cars and motorcycles); the rest come from levels.RANGES.
SPEC_RANGES = {"length_mm": (1200, 7000), "width_mm": (500, 2700), "height_mm": (700, 3000),
               "wheelbase_mm": (900, 4500), "torque_nm": (10, 2500), "gears": (1, 12)}
LEVELS = {GENERATIONS: ("generation", "kb.generation", GENERATION_KEYS, GENERATION_FIELDS),
          POWERTRAINS: ("powertrain", "kb.powertrain", POWERTRAIN_KEYS, POWERTRAIN_FIELDS)}

INSTRUCTIONS = [
    ["Qué es", "Datos que los anuncios no traen. Cada fila muestra lo que la base tiene hoy; completar o "
               "corregir con lo que diga una fuente."],
    ["fuente", "Obligatoria en cada fila que cambie algo: la ficha del fabricante, una revista, un enlace."],
    ["Qué pasa al importar", "Cada valor nuevo queda publicado como fuente externa: gana a los anuncios y "
                             "pierde ante un valor manual. Si los anuncios lo contradicen en más de 10 %, se "
                             "abre un caso de revisión."],
    ["Años del ciclo", "No se fijan al importar: abren un caso \"Ciclo de una fuente\" y los anuncios se "
                       "mueven solo cuando una persona lo aprueba. \"año fin\" vacío = sigue vigente."],
    ["Celdas vacías", "No borran nada: una celda vacía o igual a la actual no cambia nada."],
    ["Segmento", "Un código del catálogo (A-F para autos; pickups y motos tienen los suyos), acorde a la "
                 "clase del modelo y la carrocería."],
    ["Números", "Con punto o coma decimal, sin unidades (están en el encabezado)."],
]


# --- export ---------------------------------------------------------------------------------
def _filters(make: Optional[str], country: Optional[str], gen_alias: str) -> tuple[str, list]:
    sql, args = "", []
    if make:
        sql += " AND k.id IN (SELECT make_id FROM kb.make_alias WHERE alias_key = %s)"
        args.append(compact_key(make))
    if country:
        sql += (f" AND EXISTS (SELECT 1 FROM kb.listing_level ll JOIN kb.clean_listing l USING (source_site, "
                f"listing_id) WHERE ll.generation_id = {gen_alias}.id AND l.country_code = %s)")
        args.append(country.upper())
    return sql, args


def export_specs(conn, path: Path, make: Optional[str] = None, country: Optional[str] = None,
                 limit: int = 500) -> dict:
    with conn.cursor() as cur:
        return write_template(cur, path, make=make, country=country, limit=limit)


def write_template(cur, path: Path, make: Optional[str] = None, country: Optional[str] = None,
                   limit: int = 500) -> dict:
    """The template for ``make`` / ``country`` (both optional), at most ``limit`` rows per sheet;
    the terminal and the portal (through ``kb worker``) both write it here."""
    gen_cols = [c for _, c in GENERATION_FIELDS]
    pt_cols = [c for _, c in POWERTRAIN_FIELDS]
    extra, args = _filters(make, country, "g")
    cur.execute(f"""
SELECT g.id, k.name, m.name, g.name, b.name_es, g.observed_year_from, g.observed_year_to, g.listings,
       {", ".join(f"g.{c}" for c in gen_cols)}
FROM kb.generation g JOIN kb.model m ON m.id = g.model_id JOIN kb.make k ON k.id = m.make_id
LEFT JOIN kb.body_style b ON b.code = g.body_style_code
WHERE g.listings > 0 AND g.status <> 'rejected' AND ({" OR ".join(f"g.{c} IS NULL" for c in gen_cols)}){extra}
ORDER BY g.listings DESC, g.id LIMIT %s""", (*args, limit))
    gens = cur.fetchall()
    cur.execute(f"""
SELECT p.id, k.name, g.name, p.engine_displacement_l, f.name_es, t.name_es, d.name_es, p.listings,
       {", ".join(f"p.{c}" for c in pt_cols)}
FROM kb.powertrain p JOIN kb.generation g ON g.id = p.generation_id JOIN kb.model m ON m.id = g.model_id
JOIN kb.make k ON k.id = m.make_id
LEFT JOIN kb.fuel_type f ON f.code = p.fuel_type_code
LEFT JOIN kb.transmission_type t ON t.code = p.transmission_type_code
LEFT JOIN kb.drivetrain d ON d.code = p.drivetrain_code
WHERE p.listings > 0 AND p.status <> 'rejected' AND g.status <> 'rejected'
  AND ({" OR ".join(f"p.{c} IS NULL" for c in pt_cols)}){extra}
ORDER BY p.listings DESC, p.id LIMIT %s""", (*args, limit))
    pts = cur.fetchall()
    cur.execute("SELECT code FROM kb.segment ORDER BY vehicle_class_code, sort_order")
    segments = [r[0] for r in cur.fetchall()]

    def num(v):
        return float(v) if v is not None and not isinstance(v, (int, float, str)) else v
    gen_rows = [[gid, mk, mo, gname, body, f"{oyf or '?'}–{oyt or '?'}", n, *[num(v) for v in vals], None, None]
                for gid, mk, mo, gname, body, oyf, oyt, n, *vals in gens]
    pt_rows = [[pid, mk, gname, num(disp), fuel, trans, drive, n, *[num(v) for v in vals], None, None]
               for pid, mk, gname, disp, fuel, trans, drive, n, *vals in pts]
    gen_headers = GENERATION_KEYS + [h for h, _ in GENERATION_FIELDS] + TAIL
    pt_headers = POWERTRAIN_KEYS + [h for h, _ in POWERTRAIN_FIELDS] + TAIL
    write_workbook(path, [
        Sheet(GENERATIONS, gen_headers, gen_rows, lists={gen_headers.index("segmento"): segments},
              widths={gen_headers.index("fuente"): 40, gen_headers.index("nota"): 30}),
        Sheet(POWERTRAINS, pt_headers, pt_rows,
              widths={pt_headers.index("fuente"): 40, pt_headers.index("nota"): 30}),
        Sheet("Instrucciones", ["tema", "qué hacer"], INSTRUCTIONS, widths={0: 22, 1: 100}, table=False),
    ])
    return {"file": str(path), "generations": len(gen_rows), "powertrains": len(pt_rows)}


# --- import ---------------------------------------------------------------------------------
def _segment(cur, gen_id: int, raw) -> str:
    """A segment code (or its Spanish name) that fits the generation's model class and body,
    the same rules as the kb.generation trigger, checked here to report the row instead."""
    cur.execute("SELECT code, name_es, vehicle_class_code, body_style_code FROM kb.segment")
    by_key = {}
    for code, name, cls, body in cur.fetchall():
        by_key[compact_key(code)] = by_key[compact_key(name)] = (code, cls, body)
    hit = by_key.get(compact_key(str(raw)))
    if not hit:
        raise InvalidDecision(f"{raw!r} no está en el catálogo de segmentos")
    code, cls, body = hit
    cur.execute("SELECT m.vehicle_class_code, g.body_style_code FROM kb.generation g JOIN kb.model m "
                "ON m.id = g.model_id WHERE g.id = %s", (gen_id,))
    model_class, gen_body = cur.fetchone()
    if model_class and cls != model_class:
        raise InvalidDecision(f"el segmento {code} es para {cls}, no para un modelo {model_class}")
    if body and body != gen_body:
        raise InvalidDecision(f"el segmento {code} solo aplica a carrocería {body}")
    if gen_body == "Pickup" and body != "Pickup":
        raise InvalidDecision(f"una pickup necesita un segmento de pickup, no {code}")
    return code


def _value(cur, entity_id: int, column: str, raw):
    if column == "segment_code":
        return _segment(cur, entity_id, raw)
    if column in TEXT:
        text = str(raw).strip()
        if len(text) > TEXT_MAX:
            raise InvalidDecision(f"{column}: más de {TEXT_MAX} caracteres")
        return text
    value = parse_value(cur, column, raw)
    lo, hi = SPEC_RANGES.get(column) or RANGES.get(column) or (float("-inf"), float("inf"))
    if not lo <= float(value) <= hi:
        raise InvalidDecision(f"{raw} está fuera del rango {lo}-{hi} de {column}")
    return value


def _same(a, b) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def _blank(v) -> bool:
    return v is None or str(v).strip() == ""


def _cycle_case(cur, gen_id: int, current: dict, proposed: dict, evidence: dict) -> str:
    """Open (or update) the generation_cycle case. A decided one is asked again only for a
    different cycle, with the earlier decision kept in its evidence."""
    cur.execute("SELECT id, status, proposed_value, decided_by, decided_at FROM kb.review_item "
                "WHERE entity_type = 'generation' AND entity_key = %s AND field = '' AND issue = 'generation_cycle'",
                (str(gen_id),))
    row = cur.fetchone()
    if row and row[1] not in ("pending", "obsolete"):
        if row[2] == proposed:
            return "already_decided"
        evidence = {**evidence, "previous": {"status": row[1], "proposed": row[2], "decided_by": row[3],
                                             "decided_at": row[4].isoformat() if row[4] else None}}
    cur.execute("""
INSERT INTO kb.review_item (entity_type, entity_key, field, issue, current_value, proposed_value, evidence,
                            listings_affected)
SELECT 'generation', %s, '', 'generation_cycle', %s, %s, %s, listings FROM kb.generation WHERE id = %s
ON CONFLICT (entity_type, entity_key, field, issue) DO UPDATE SET
    current_value = EXCLUDED.current_value, proposed_value = EXCLUDED.proposed_value, evidence = EXCLUDED.evidence,
    listings_affected = EXCLUDED.listings_affected, status = 'pending', corrected_value = NULL, decided_by = NULL,
    decided_at = NULL, note = NULL, updated_at = now()""",
                (str(gen_id), json.dumps(current), json.dumps(proposed), json.dumps(evidence), gen_id))
    return "opened"


def _import_sheet(cur, table_rows: list, sheet: str, by: str, file: str, stats: Counter, errors: list) -> None:
    entity_type, table, keys, fields = LEVELS[sheet]
    if not table_rows:
        return
    header = [str(h or "").strip().lower() for h in table_rows[0]]
    col = {h: i for i, h in enumerate(header)}
    for needed in ["id", *[h for h, _ in fields], *TAIL]:
        if needed.lower() not in col:
            raise ValueError(f"{file}: column {needed!r} is missing from {sheet!r}")

    def cell(row, name):
        i = col[name.lower()]
        return row[i] if i < len(row) else None

    columns = [c for _, c in fields]
    for n, row in enumerate(table_rows[1:], start=2):
        if not row or all(_blank(v) for v in row):
            continue
        try:
            eid = int(cell(row, "id"))
        except (TypeError, ValueError):
            errors.append({"sheet": sheet, "row": n, "error": "id inválido"})
            continue
        cur.execute(f"SELECT {', '.join(columns)} FROM {table} WHERE id = %s", (eid,))
        found = cur.fetchone()
        if not found:
            errors.append({"sheet": sheet, "row": n, "id": eid, "error": "no existe"})
            continue
        current = dict(zip(columns, found))
        try:
            changes = {}
            for header_name, column in fields:
                raw = cell(row, header_name)
                if column in CYCLE:
                    continue
                if _blank(raw):
                    continue
                value = _value(cur, eid, column, raw)
                if not _same(value, current[column]):
                    changes[column] = value
            cycle = None
            if entity_type == "generation":
                years = {}
                for header_name, column in fields:
                    if column in CYCLE:
                        raw = cell(row, header_name)
                        years[column] = None if _blank(raw) else _year(raw)
                was = {c: current[c] for c in CYCLE}
                if years["year_from"] is not None or years["year_to"] is not None:
                    proposed = check_cycle(years["year_from"], years["year_to"])
                    if proposed != was:
                        cycle = (was, proposed)
            source = cell(row, "fuente")
            if (changes or cycle) and _blank(source):
                raise InvalidDecision("falta la fuente")
        except InvalidDecision as e:
            errors.append({"sheet": sheet, "row": n, "id": eid, "error": str(e)})
            continue
        detail = {"source": str(source).strip() if source else None, "captured_by": by, "file": file,
                  **({"note": str(cell(row, "nota")).strip()} if not _blank(cell(row, "nota")) else {})}
        for column, value in changes.items():
            cur.execute("""
INSERT INTO kb.spec_evidence (entity_type, entity_id, field, source_kind, source_code, value, status, support,
                              detail)
VALUES (%s, %s, %s, 'external', 'captura', %s, 'accepted', 0, %s)
ON CONFLICT (entity_type, entity_id, field, source_kind, source_code) DO UPDATE SET
    value = EXCLUDED.value, status = 'accepted', detail = EXCLUDED.detail, updated_at = now()""",
                        (entity_type, eid, column, json.dumps(value), json.dumps(detail)))
            stats[f"{entity_type}_values"] += 1
        if cycle:
            stats[f"cycle_{_cycle_case(cur, eid, cycle[0], cycle[1], detail)}"] += 1
        if changes or cycle:
            stats[f"{entity_type}_rows"] += 1


def read_template(path: Path) -> dict[str, list]:
    """The template's two sheets, or ValueError when the file isn't one (not an .xlsx, a sheet
    missing)."""
    try:
        return {name: read_sheet(Path(path), name) for name in LEVELS}
    except KeyError as e:
        raise ValueError(f"no es la plantilla de captura: {e.args[0]}") from None
    except (zipfile.BadZipFile, ET.ParseError):
        raise ValueError("no es un archivo .xlsx válido") from None


def save_template(cur, sheets: dict[str, list], by: str, file_name: str) -> dict:
    """Save a filled template under the caller's writer lock: {saved, errors}. Used by
    ``import_specs`` and by ``kb worker`` (portal uploads)."""
    stats: Counter = Counter()
    errors: list[dict] = []
    for name, rows in sheets.items():
        _import_sheet(cur, rows, name, by.strip(), file_name, stats, errors)
    return {"saved": dict(stats), "errors": errors}


def import_specs(conn, path: Path, by: str, rebuild: bool = True) -> dict:
    if not by.strip():
        raise ValueError("who captured the values (--by) is required")
    sheets = read_template(path)
    with conn.transaction(), conn.cursor() as cur:
        take_writer_lock(cur)
        summary = {"file": str(path), **save_template(cur, sheets, by, Path(path).name)}
        if rebuild and (summary["saved"].get("generation_values") or summary["saved"].get("powertrain_values")):
            from .build import build
            summary["build"] = build(conn)
    return summary
