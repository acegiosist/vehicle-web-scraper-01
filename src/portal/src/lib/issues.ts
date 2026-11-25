/**
 * Kinds of review case and what each decision does. Mirrors src/vehicle_scraper/kb/review.py
 * (ISSUES, CLASSES, ISSUE_ORDER): the Excel file and the portal must say the same thing.
 * tests/test_portal_sync.py fails when a text here and there differ.
 */
export const ISSUE_ORDER = [
  "unknown_make",
  "missing_make",
  "weak_model",
  "model_is_attributes",
  "generation_split",
  "year_outside_generation",
  "spec_disagreement",
  "evolution_note",
  "field_conflict",
  "implausible_value",
] as const;
export type Issue = (typeof ISSUE_ORDER)[number];

export interface IssueInfo {
  label: string;
  what: string;
  approve: string;
  reject: string;
  correct: string;
}

export const ISSUES: Record<Issue, IssueInfo> = {
  unknown_make: {
    label: "Marca desconocida",
    what: "Marca que no está en la lista de marcas.",
    approve: 'Es una marca real: elegir en "clase" qué fabrica (obligatorio).',
    reject: "No es una marca de vehículos: sus anuncios no pasan a los niveles.",
    correct: "Es otra escritura de una marca existente: escribir su nombre (p. ej. Changan).",
  },
  missing_make: {
    label: "Anuncio sin marca",
    what: "Anuncio sin marca.",
    approve: "Dejarlo sin marca.",
    reject: "Dejarlo sin marca.",
    correct: "Escribir la marca (debe existir).",
  },
  weak_model: {
    label: "Modelo poco visto",
    what: "Nombre de modelo visto en pocos anuncios (menos de 5 y un solo sitio).",
    approve: "Es un modelo real: se acepta.",
    reject: "No es un modelo: sus anuncios no pasan a los niveles.",
    correct: "Escribir el nombre correcto: si ya existe en la marca se unen, si no se renombra.",
  },
  model_is_attributes: {
    label: "Modelo que es solo mecánica",
    what: 'El modelo del anuncio es solo mecánica (p. ej. "1.3").',
    approve: "Dejarlo sin modelo.",
    reject: "Dejarlo sin modelo.",
    correct: "Escribir el modelo de ese anuncio.",
  },
  generation_split: {
    label: "Corte de generación",
    what: "El motor cambia entre años: se propone dividir la generación desde el año propuesto.",
    approve: "Dividir en el año propuesto.",
    reject: "No dividir.",
    correct: "Escribir el año correcto del corte.",
  },
  year_outside_generation: {
    label: "Año fuera del ciclo",
    what: "Hay anuncios de años fuera del ciclo de esta generación: se propone extender su año de inicio o de fin.",
    approve: "Extender el ciclo hasta el año propuesto (los anuncios entran al recalcular).",
    reject: "No extender: esos anuncios siguen sin asignar.",
    correct: "Escribir el año correcto de inicio o de fin.",
  },
  spec_disagreement: {
    label: "Discrepancia de datos",
    what: "Los anuncios no coinciden en un dato mecánico (más de 10 % de diferencia), o cambiarían un valor de una entidad verificada.",
    approve: "El valor propuesto es correcto.",
    reject: "No fijar el valor (siguen votando los anuncios; en una verificada se queda el actual).",
    correct: "Escribir el valor correcto.",
  },
  evolution_note: {
    label: "Nota de evolución",
    what: "Un equipamiento cambia desde un año en esta variante: se propone una nota de evolución.",
    approve: "Crear la nota (campo, valor y año propuestos).",
    reject: "No crear la nota.",
    correct: "Escribir el año correcto desde el que aplica.",
  },
  field_conflict: {
    label: "Conflicto campo / nombre",
    what: "El campo del anuncio dice una cosa y el nombre de la versión otra.",
    approve: "Vale lo que dice el nombre (valor propuesto).",
    reject: "Vale el campo del anuncio (valor actual).",
    correct: "Escribir el valor correcto.",
  },
  implausible_value: {
    label: "Valor imposible",
    what: "Valor imposible o fuera de rango.",
    approve: "El valor es correcto, se conserva.",
    reject: "El valor está mal: se borra.",
    correct: "Escribir el valor correcto.",
  },
};

export function isIssue(value: unknown): value is Issue {
  return typeof value === "string" && (ISSUE_ORDER as readonly string[]).includes(value);
}

/** Make classes a reviewer picks when approving an unknown make (review.CLASSES keys). */
export const MAKE_CLASSES = {
  auto: "Automóviles",
  moto: "Motos",
  pesado: "Pesados (camión, bus)",
  maquinaria: "Maquinaria",
  golf: "Carritos de golf",
  bicicleta: "Bicicletas",
  remolque: "Remolques",
  cuatrimoto: "Cuatrimotos",
} as const;
export type MakeClass = keyof typeof MAKE_CLASSES;

export const DECISIONS = { aprobar: "Aprobar", rechazar: "Rechazar", corregir: "Corregir" } as const;
export type Decision = keyof typeof DECISIONS;

export const ENTITY_LABELS: Record<string, string> = {
  make: "Marca",
  model: "Modelo",
  listing: "Anuncio",
  generation: "Generación",
  powertrain: "Tren motriz",
  variant: "Variante",
};
