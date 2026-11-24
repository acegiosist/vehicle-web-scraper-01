"""``kb review export`` / ``kb review import``: deciding review cases in an Excel file.

Export writes the pending cases to a .xlsx with a "Casos" sheet (one row per case, with
drop-downs for the decision and the make class) and an "Instrucciones" sheet that explains
what approving, rejecting or correcting means for each kind of case.

Import reads the "decisión" column back (aprobar / rechazar / corregir), validates each row
(a correction must fit its field: a catalog value, a number in range, an existing make...)
and records the decision with the reviewer's name. A row that doesn't validate is reported
and its case stays pending; the other rows are still saved. A case decided before is never
overwritten. Then, unless ``rebuild=False``, ``kb clean`` and ``kb build`` run in the same
transaction, so the decisions show at once and a failure leaves nothing half done.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from ..xlsx import Sheet, read_sheet, write_workbook
from .clean import BOUNDS
from .db import take_writer_lock
from .identity import compact_key
from .levels import BOOLEAN, RANGES

SHEET = "Casos"
HEADERS = ["id", "tipo", "qué revisar", "entidad", "campo", "valor actual", "valor propuesto", "anuncios",
           "evidencia", "enlace", "decisión", "valor corregido", "clase", "nota"]
DECISIONS = {"aprobar": "approved", "approve": "approved", "rechazar": "rejected", "reject": "rejected",
             "corregir": "corrected", "correct": "corrected"}
CLASSES = {"auto": "car", "moto": "motorcycle", "pesado": "heavy", "maquinaria": "machinery", "golf": "golf_cart",
           "bicicleta": "bicycle", "remolque": "trailer", "cuatrimoto": "atv"}
CATALOG_FIELDS = {"body_style": "body_style", "fuel_type": "fuel_type", "transmission_type": "transmission_type",
                  "drivetrain": "drivetrain", "headlight_type_code": "headlight_type",
                  "brake_front_code": "brake_type", "brake_rear_code": "brake_type"}
TEXT_FIELDS = {"tire_size", "country_of_manufacture"}
# Order of the rows: identity first (it unblocks the most), then levels, then listings.
ISSUE_ORDER = ["unknown_make", "missing_make", "weak_model", "model_is_attributes", "generation_split",
               "spec_disagreement", "evolution_note", "field_conflict", "implausible_value"]

# issue: (what to check, approve, reject, correct)
ISSUES = {
    "unknown_make": ("Marca que no está en la lista de marcas.",
                     "Es una marca real: elegir en \"clase\" qué fabrica (obligatorio).",
                     "No es una marca de vehículos: sus anuncios no pasan a los niveles.",
                     "Es otra escritura de una marca existente: escribir su nombre (p. ej. Changan)."),
    "missing_make": ("Anuncio sin marca.", "Dejarlo sin marca.", "Dejarlo sin marca.",
                     "Escribir la marca (debe existir)."),
    "weak_model": ("Nombre de modelo visto en pocos anuncios (menos de 5 y un solo sitio).",
                   "Es un modelo real: se acepta.", "No es un modelo: sus anuncios no pasan a los niveles.",
                   "Escribir el nombre correcto: si ya existe en la marca se unen, si no se renombra."),
    "model_is_attributes": ("El modelo del anuncio es solo mecánica (p. ej. \"1.3\").",
                            "Dejarlo sin modelo.", "Dejarlo sin modelo.", "Escribir el modelo de ese anuncio."),
    "generation_split": ("El motor cambia entre años: se propone dividir la generación desde el año propuesto.",
                         "Dividir en el año propuesto.", "No dividir.", "Escribir el año correcto del corte."),
    "spec_disagreement": ("Los anuncios no coinciden en un dato mecánico (más de 10 % de diferencia).",
                          "El valor propuesto es correcto.", "No fijar el valor (siguen votando los anuncios).",
                          "Escribir el valor correcto."),
    "evolution_note": ("Un equipamiento cambia desde un año en esta variante: se propone una nota de evolución.",
                       "Crear la nota (campo, valor y año propuestos).", "No crear la nota.",
                       "Escribir el año correcto desde el que aplica."),
    "field_conflict": ("El campo del anuncio dice una cosa y el nombre de la versión otra.",
                       "Vale lo que dice el nombre (valor propuesto).", "Vale el campo del anuncio (valor actual).",
                       "Escribir el valor correcto."),
    "implausible_value": ("Valor imposible o fuera de rango.", "El valor es correcto, se conserva.",
                          "El valor está mal: se borra.", "Escribir el valor correcto."),
}


class InvalidDecision(ValueError):
    pass


# --- export ---------------------------------------------------------------------------------
def _show(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_show(v)}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(str(_show(v)) for v in value)
    return str(value)


def _labels(cur) -> dict[tuple[str, str], tuple[str, Optional[str]]]:
    """(entity_type, entity_key) -> (readable entity, link) for every pending case."""
    out = {}
    queries = {
        "make": "SELECT r.entity_key, k.name, NULL FROM kb.review_item r JOIN kb.make k ON k.id::text = r.entity_key "
                "WHERE r.entity_type = 'make' AND r.status = 'pending'",
        "model": "SELECT r.entity_key, k.name || ' ' || m.name, NULL FROM kb.review_item r "
                 "JOIN kb.model m ON m.id::text = r.entity_key JOIN kb.make k ON k.id = m.make_id "
                 "WHERE r.entity_type = 'model' AND r.status = 'pending'",
        "listing": """
SELECT r.entity_key, concat_ws(' ', s.data->>'make', s.data->>'model', s.data->>'trim', s.data->>'model_year',
                               '(' || s.source_site || ':' || s.listing_id || ')'), s.data->>'source_url'
FROM kb.review_item r JOIN staging.current_listing s ON s.source_site || ':' || s.listing_id = r.entity_key
WHERE r.entity_type = 'listing' AND r.status = 'pending'""",
        "generation": """
SELECT r.entity_key, k.name || ' ' || g.name || ' ' || coalesce(g.observed_year_from::text, '?') || '-'
                     || coalesce(g.observed_year_to::text, '?'), NULL
FROM kb.review_item r JOIN kb.generation g ON g.id::text = r.entity_key JOIN kb.model m ON m.id = g.model_id
JOIN kb.make k ON k.id = m.make_id WHERE r.entity_type = 'generation' AND r.status = 'pending'""",
        "powertrain": """
SELECT r.entity_key, k.name || ' ' || g.name || ' / ' || p.match_key, NULL
FROM kb.review_item r JOIN kb.powertrain p ON p.id::text = r.entity_key JOIN kb.generation g ON g.id = p.generation_id
JOIN kb.model m ON m.id = g.model_id JOIN kb.make k ON k.id = m.make_id
WHERE r.entity_type = 'powertrain' AND r.status = 'pending'""",
        "variant": """
SELECT r.entity_key, k.name || ' ' || g.name || ' / ' || p.match_key || ' / ' || v.country_code || ' / '
                     || coalesce(v.trim_name, '(sin versión)'), NULL
FROM kb.review_item r JOIN kb.commercial_variant v ON v.id::text = r.entity_key
JOIN kb.powertrain p ON p.id = v.powertrain_id JOIN kb.generation g ON g.id = v.generation_id
JOIN kb.model m ON m.id = g.model_id JOIN kb.make k ON k.id = m.make_id
WHERE r.entity_type = 'variant' AND r.status = 'pending'""",
    }
    for etype, sql in queries.items():
        cur.execute(sql)
        for key, label, link in cur.fetchall():
            out[(etype, key)] = (label, link)
    return out


def export_review(conn, path: Path, issues: Optional[list[str]] = None, limit: Optional[int] = None) -> dict:
    with conn.cursor() as cur:
        labels = _labels(cur)
        cur.execute("""
SELECT id, issue, entity_type, entity_key, field, current_value, proposed_value, listings_affected, evidence
FROM kb.review_item WHERE status = 'pending' AND (%s::text[] IS NULL OR issue = ANY(%s::text[]))""",
                    (issues, issues))
        cases = cur.fetchall()
    cases.sort(key=lambda c: (ISSUE_ORDER.index(c[1]) if c[1] in ISSUE_ORDER else 99, -c[7], c[0]))
    if limit:
        cases = cases[:limit]
    rows = []
    for cid, issue, etype, ekey, fname, current, proposed, n, evidence in cases:
        label, link = labels.get((etype, ekey), (f"{etype} {ekey}", None))
        evidence_text = _show(evidence)
        rows.append([cid, issue, ISSUES.get(issue, ("",))[0], label, fname or None, _show(current), _show(proposed),
                     n, evidence_text[:500] if evidence_text else None, link, None, None, None, None])
    instructions = [[issue, what, approve, reject, correct] for issue, (what, approve, reject, correct) in ISSUES.items()]
    instructions += [[], ["Cómo llenar", "Escribir en \"decisión\": aprobar, rechazar o corregir. Las filas sin "
                          "decisión no cambian nada.", "\"valor corregido\" solo con corregir.",
                          "\"clase\" solo para marcas desconocidas que se aprueban: " + ", ".join(CLASSES),
                          "Valores sí/no: sí, no. Números con punto o coma decimal."]]
    write_workbook(path, [
        Sheet(SHEET, HEADERS, rows, lists={10: ["aprobar", "rechazar", "corregir"], 12: list(CLASSES)},
              widths={2: 40, 3: 50, 8: 50, 9: 30}),
        Sheet("Instrucciones", ["tipo", "qué significa", "aprobar", "rechazar", "corregir"], instructions,
              widths={0: 20, 1: 60, 2: 45, 3: 45, 4: 50}, table=False),
    ])
    return {"file": str(path), "cases": len(rows), "by_issue": dict(Counter(r[1] for r in rows))}


# --- import ---------------------------------------------------------------------------------
_YES = {"si", "sí", "yes", "true", "1", "verdadero", "x"}
_NO = {"no", "false", "0", "falso"}


def _catalog(cur, table: str) -> dict[str, str]:
    cur.execute(f"SELECT code, name_es, name_en FROM kb.{table}")
    out = {}
    for code, es, en in cur.fetchall():
        for spelling in (code, es, en):
            out[compact_key(spelling)] = code
    return out


def parse_value(cur, field_name: str, raw) -> object:
    """A reviewer's correction as the field's type, or InvalidDecision."""
    if raw is None or str(raw).strip() == "":
        raise InvalidDecision("falta el valor corregido")
    text = str(raw).strip()
    if field_name in CATALOG_FIELDS:
        code = _catalog(cur, CATALOG_FIELDS[field_name]).get(compact_key(text))
        if not code:
            raise InvalidDecision(f"{text!r} no está en el catálogo de {field_name}")
        return code
    if field_name in BOOLEAN:
        low = text.lower()
        if low in _YES:
            return True
        if low in _NO:
            return False
        raise InvalidDecision(f"{text!r} no es sí/no")
    if field_name in TEXT_FIELDS:
        return text
    try:
        n = float(text.replace(",", ".")) if not isinstance(raw, (int, float)) else float(raw)
    except ValueError:
        raise InvalidDecision(f"{text!r} no es un número")
    lo, hi = RANGES.get(field_name) or BOUNDS.get(field_name) or (float("-inf"), float("inf"))
    if not lo <= n <= hi:
        raise InvalidDecision(f"{text} está fuera del rango {lo}-{hi} de {field_name}")
    return int(n) if n.is_integer() and field_name != "engine_displacement_l" else round(n, 3)


def _year(raw) -> int:
    try:
        y = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        raise InvalidDecision(f"{raw!r} no es un año")
    if not 1900 <= y <= 2100:
        raise InvalidDecision(f"{y} no es un año válido")
    return y


def _make_named(cur, name) -> int:
    cur.execute("SELECT a.make_id FROM kb.make_alias a JOIN kb.make k ON k.id = a.make_id "
                "WHERE a.alias_key = %s AND k.status = 'accepted'", (compact_key(name),))
    row = cur.fetchone()
    if not row:
        raise InvalidDecision(f"no hay una marca aceptada llamada {name!r}")
    return row[0]


def decide(cur, case: dict, decision: str, corrected, klass) -> tuple[str, object]:
    """(status, corrected_value) for one row, or InvalidDecision."""
    status = DECISIONS.get(str(decision).strip().lower())
    if not status:
        raise InvalidDecision(f"decisión {decision!r}: usar aprobar, rechazar o corregir")
    issue, fname = case["issue"], case["field"]
    if status == "rejected":
        return status, None
    if issue == "unknown_make":
        if status == "approved":
            cls = CLASSES.get(str(klass or "").strip().lower())
            if not cls:
                raise InvalidDecision("para aprobar una marca hay que elegir su clase: " + ", ".join(CLASSES))
            return status, {"class": cls}
        target = _make_named(cur, corrected)
        if str(target) == case["entity_key"]:
            raise InvalidDecision("la corrección es la misma marca")
        return status, {"merge": target, "name": str(corrected).strip()}
    if status == "approved":
        return status, None
    # corrected
    if issue == "missing_make":
        _make_named(cur, corrected)
        return status, {"make": str(corrected).strip()}
    if issue in ("weak_model", "model_is_attributes"):
        name = str(corrected or "").strip()
        if not compact_key(name):
            raise InvalidDecision("falta el nombre del modelo")
        return status, {"name": name} if issue == "weak_model" else {"model": name}
    if issue == "generation_split":
        return status, {"year_from": _year(corrected)}
    if issue == "evolution_note":
        return status, {"value": (case["proposed"] or {}).get("value"), "year_from": _year(corrected)}
    return status, parse_value(cur, fname, corrected)


def import_review(conn, path: Path, reviewer: str, rebuild: bool = True) -> dict:
    if not reviewer.strip():
        raise ValueError("reviewer name is required")
    table = read_sheet(Path(path), SHEET)
    if not table:
        raise ValueError(f"{path}: the {SHEET!r} sheet is empty")
    header = [str(h or "").strip().lower() for h in table[0]]
    col = {h: i for i, h in enumerate(header)}
    for needed in ("id", "decisión", "valor corregido", "clase", "nota"):
        if needed not in col:
            raise ValueError(f"{path}: column {needed!r} is missing from {SHEET!r}")

    def cell(row, name):
        i = col[name]
        return row[i] if i < len(row) else None

    stats: Counter = Counter()
    errors: list[dict] = []
    with conn.transaction(), conn.cursor() as cur:
        take_writer_lock(cur)
        for n, row in enumerate(table[1:], start=2):
            decision = cell(row, "decisión")
            if decision is None or str(decision).strip() == "":
                continue
            try:
                case_id = int(cell(row, "id"))
            except (TypeError, ValueError):
                errors.append({"row": n, "error": "id inválido"})
                continue
            cur.execute("SELECT issue, entity_type, entity_key, field, status, proposed_value, current_value "
                        "FROM kb.review_item WHERE id = %s FOR UPDATE", (case_id,))
            found = cur.fetchone()
            if not found:
                errors.append({"row": n, "id": case_id, "error": "el caso no existe"})
                continue
            case = dict(zip(("issue", "entity_type", "entity_key", "field", "status", "proposed", "current"), found))
            if case["status"] != "pending":
                stats["already_decided"] += 1
                continue
            try:
                status, value = decide(cur, case, decision, cell(row, "valor corregido"), cell(row, "clase"))
            except InvalidDecision as e:
                errors.append({"row": n, "id": case_id, "error": str(e)})
                continue
            note = cell(row, "nota")
            cur.execute("UPDATE kb.review_item SET status = %s, corrected_value = %s, decided_by = %s, "
                        "decided_at = now(), note = %s, updated_at = now() WHERE id = %s",
                        (status, json.dumps(value) if value is not None else None, reviewer.strip(),
                         str(note) if note not in (None, "") else None, case_id))
            stats[status] += 1
        summary = {"file": str(path), "decided": dict(stats), "errors": errors}
        if rebuild and (stats["approved"] or stats["rejected"] or stats["corrected"]):
            from .build import build
            from .clean import clean
            summary["clean"] = clean(conn)
            summary["build"] = build(conn)
    return summary
