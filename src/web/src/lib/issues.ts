// What each kind of review case asks and what each decision does. The effects mirror
// `apply_decision` in src/vehicle_scraper/kb/review.py; keep both in sync.
export type Decision = "approved" | "rejected" | "corrected";
export type EntityType = "make" | "model" | "trim" | "listing" | "variant" | "spec";

export const DECISION_LABELS: Record<Decision, string> = {
  approved: "Aprobar",
  rejected: "Rechazar",
  corrected: "Corregir",
};

export const LEVELS: Record<number, string> = {
  1: "Marcas",
  2: "Modelos",
  3: "Años",
  4: "Variantes",
  5: "Fichas mecánicas",
  6: "Equipamiento",
};

export const ENTITY_LABELS: Record<EntityType, string> = {
  make: "Marca",
  model: "Modelo",
  trim: "Versión",
  listing: "Anuncio",
  variant: "Variante",
  spec: "Ficha",
};

/** How a corrected value is typed: a spec field value, or a name (identity). */
export type CorrectionKind = "field" | "make_name" | "model_name" | "trim_name";

export interface IssueInfo {
  title: string;
  question: string;
  effects: Partial<Record<Decision, string>>;
  correction?: CorrectionKind;
}

const RULE_FLAG: Pick<IssueInfo, "effects" | "correction"> = {
  effects: {
    approved: "El valor marcado es correcto: se publica y no se vuelve a marcar.",
    rejected: "El valor está mal: se descarta y el campo queda sin ese dato.",
    corrected: "El valor está mal: se publica el que escribas, como dato verificado por una persona.",
  },
  correction: "field",
};

const VARIANT_FLAG: Pick<IssueInfo, "effects"> = {
  effects: {
    approved: "Los datos de la variante son correctos: se acepta y sus fichas se publican.",
    rejected: "Los datos están mal: la variante queda rechazada y no se publica.",
  },
};

const AI_VALUE: Pick<IssueInfo, "effects" | "correction"> = {
  effects: {
    approved: "El valor que propone la IA es correcto: se publica.",
    rejected: "El valor de la IA está mal: se descarta.",
    corrected: "El valor de la IA está mal: se publica el que escribas.",
  },
  correction: "field",
};

export const ISSUES: Record<string, IssueInfo> = {
  unresolved_make: {
    title: "Marca sin confirmar",
    question: "¿Es una marca real? ¿Es otra forma de escribir una marca que ya existe?",
    effects: {
      approved: "Es una marca real: se acepta con el nombre propuesto.",
      rejected: "No es una marca de vehículos: sus anuncios quedan fuera de la base.",
      corrected: "Escribe el nombre correcto. Si coincide con una marca que ya existe, las dos se fusionan.",
    },
    correction: "make_name",
  },
  unresolved_model: {
    title: "Modelo sin confirmar",
    question: "¿Es un modelo real de esta marca? ¿Es el mismo que otro modelo ya existente?",
    effects: {
      approved: "Es un modelo real: se acepta y se aplica la propuesta (nombre, clase, años, fusión o marca correcta).",
      rejected: "No es un modelo real: sus anuncios quedan fuera de la base.",
      corrected: "Escribe el nombre canónico, o elige un modelo existente para fusionarlo con él.",
    },
    correction: "model_name",
  },
  year_out_of_range: {
    title: "Año imposible",
    question: "El año del anuncio es anterior a 1950 o posterior al año siguiente.",
    effects: {
      approved: "El año es correcto: el anuncio entra al consenso.",
      rejected: "El año está mal: el anuncio queda fuera del consenso.",
    },
  },
  year_outside_production: {
    title: "Año fuera de producción",
    question: "El año está fuera del periodo en que se fabricó el modelo.",
    effects: {
      approved: "El año es correcto: el anuncio entra al consenso.",
      rejected: "El año está mal: el anuncio queda fuera del consenso.",
    },
  },
  name_vs_displacement: {
    title: "Nombre contra cilindrada",
    question: "En esta moto, el número del nombre no coincide con los cc (ej. G 310 con 1.0 L).",
    ...VARIANT_FLAG,
  },
  title_vs_displacement: {
    title: "Versión contra cilindrada",
    question: "La cilindrada que dice la versión (ej. “1.8”) no coincide con la de la ficha.",
    ...VARIANT_FLAG,
  },
  ev_with_displacement: {
    title: "Eléctrico con cilindrada",
    question: "Un vehículo eléctrico no debería tener cilindrada.",
    ...VARIANT_FLAG,
  },
  listings_disagree: {
    title: "Los anuncios no coinciden",
    question: "Los anuncios de esta variante dan valores distintos (menos del 70 % de acuerdo).",
    effects: {
      approved: "Se publica el valor más votado.",
      rejected: "Ningún valor es confiable: el campo queda sin publicar.",
      corrected: "Se publica el valor que escribas, como dato verificado.",
    },
    correction: "field",
  },
  outlier_in_model: {
    title: "Valor atípico",
    question: "El valor se aleja mucho de las demás variantes del mismo modelo.",
    ...RULE_FLAG,
  },
  hp_per_litre: {
    title: "Potencia por litro imposible",
    question: "La potencia por litro está fuera de 15–260 hp/L.",
    ...RULE_FLAG,
  },
  seats_vs_body: {
    title: "Puestos contra carrocería",
    question: "Más de 9 puestos en un carro que no es van, minivan ni camión.",
    ...RULE_FLAG,
  },
  doors_on_motorcycle: {
    title: "Moto con puertas",
    question: "Una moto no debería tener puertas.",
    ...RULE_FLAG,
  },
  conflicts_with_human: {
    title: "Contradice un dato verificado",
    question: "Evidencia nueva contradice un valor que aprobó una persona.",
    effects: {
      approved: "La evidencia nueva tiene razón: se publica su valor.",
      rejected: "El valor verificado sigue siendo el correcto: no cambia nada.",
      corrected: "Ninguno de los dos: se publica el valor que escribas.",
    },
    correction: "field",
  },
  merge_human_conflict: {
    title: "Conflicto al fusionar",
    question: "Al fusionar dos variantes, sus valores verificados por personas no coinciden.",
    effects: {
      approved: "Se publica el valor propuesto.",
      rejected: "Se mantiene el valor actual.",
      corrected: "Se publica el valor que escribas.",
    },
    correction: "field",
  },
  ai_value: {
    title: "Valor crítico de la IA",
    question: "La IA propone un valor crítico sin consenso de anuncios.",
    ...AI_VALUE,
  },
  ai_value_sample: {
    title: "Muestra de un lote de IA",
    question: "Valor de la IA que cayó en la muestra. Con 95 % de aciertos se acepta todo el lote.",
    ...AI_VALUE,
  },
  ai_suspect_known: {
    title: "La IA duda de un valor",
    question: "La IA cree que un valor ya publicado está mal.",
    effects: {
      approved: "La IA tiene razón: se publica el valor que espera.",
      rejected: "El valor publicado es correcto: no cambia nada.",
      corrected: "Se publica el valor que escribas.",
    },
    correction: "field",
  },
};

export function issueInfo(issue: string | null | undefined): IssueInfo {
  return (
    (issue && ISSUES[issue]) || {
      title: issue ?? "Caso",
      question: "",
      effects: { approved: "Aprobar la propuesta.", rejected: "Rechazar la propuesta." },
    }
  );
}

/** The decisions that do something for this case (e.g. a variant flag can't be "corrected"). */
export function allowedDecisions(issue: string | null | undefined): Decision[] {
  return (Object.keys(issueInfo(issue).effects) as Decision[]).filter((d) =>
    ["approved", "rejected", "corrected"].includes(d),
  );
}

export function levelLabel(level: number | null | undefined): string {
  return (level && LEVELS[level]) || `Nivel ${level ?? "?"}`;
}

// Readable names for the keys found in review_item.proposed / current / evidence.
const KEY_LABELS: Record<string, string> = {
  value: "Valor",
  source: "Origen",
  top_value: "Valor más votado",
  agreement: "Acuerdo",
  support: "Anuncios que respaldan",
  model_median: "Mediana del modelo",
  hp_per_litre: "hp por litro",
  name: "Nombre",
  make: "Marca",
  model: "Modelo",
  year: "Año",
  years: "Años vistos",
  vehicle_class: "Clase",
  sites: "Portales",
  listings: "Anuncios",
  spellings: "Grafías",
  sample_models: "Modelos de ejemplo",
  sample_trims: "Versiones de ejemplo",
  ai_allowed: "Se puede enviar a la IA",
  confidence: "Confianza",
  canonical_name: "Nombre canónico",
  engine_displacement_l: "Cilindrada (L)",
  title_litres: "Litros en la versión",
  name_number: "Número del nombre",
  expected_value: "Valor esperado",
  reason: "Razón",
  merge_into_id: "Fusionar con (id)",
  is_real_model: "¿Modelo real?",
  is_vehicle_make: "¿Marca de vehículos?",
  same_as_known_make: "Igual a la marca",
  wrong_make: "Marca correcta",
  year_from: "Desde",
  year_to: "Hasta",
  seats: "Puestos",
  body_style: "Carrocería",
  status: "Estado",
};

export function keyLabel(key: string): string {
  return KEY_LABELS[key] ?? key;
}
