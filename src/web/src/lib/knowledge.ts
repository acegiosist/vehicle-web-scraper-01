// Labels and pure helpers for the knowledge base browser (/base). Usable on the server and in tests.

/** spec_evidence.source_kind, in the reviewer's words. */
const SOURCES: Record<string, string> = {
  listing_consensus: "Consenso de anuncios",
  listing_single: "Un solo anuncio",
  sibling_inference: "Heredado de años vecinos",
  ai_knowledge: "Conocimiento de la IA",
  manual: "Verificado por una persona",
};

export function sourceLabel(source: string | null | undefined): string {
  if (!source) return "—";
  return SOURCES[source] ?? source;
}

/** status of make / model / trim / variant and of spec_evidence. */
const STATUSES: Record<string, string> = {
  accepted: "Aceptada",
  accepted_sampled: "Aceptada por muestreo",
  pending_review: "En revisión",
  rejected: "Rechazada",
  unresolved: "Sin resolver",
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return STATUSES[status] ?? status;
}

/** verified_by of make / model / trim / variant. */
const VERIFIED: Record<string, string> = {
  seed: "Semilla",
  multi_source: "Varios portales",
  ai: "IA",
  human: "Persona",
  unverified: "Sin verificar",
};

export function verifiedLabel(verified: string | null | undefined): string {
  if (!verified) return "—";
  return VERIFIED[verified] ?? verified;
}

const CLASSES: Record<string, string> = { car: "Carro", motorcycle: "Moto", heavy: "Pesado" };

export function vehicleClassLabel(cls: string | null | undefined): string | null {
  if (!cls) return null;
  return CLASSES[cls] ?? cls;
}

// Same precedence as consensus.publish (src/vehicle_scraper/kb/consensus.py: RANK, PUBLISHED):
// the published value of a cell comes from its best accepted evidence.
const RANK: Record<string, number> = {
  manual: 5,
  listing_consensus: 4,
  listing_single: 3,
  sibling_inference: 2,
  ai_knowledge: 1,
};
const PUBLISHED = new Set(["accepted", "accepted_sampled"]);

export interface EvidenceLike {
  field: string;
  country: string;
  source_kind: string;
  status: string;
  confidence: number | null;
}

/** Key of a spec cell: mechanical fields use the empty country. */
export function cellKey(field: string, country = ""): string {
  return `${field}|${country}`;
}

/** The evidence each published cell comes from, keyed by ``cellKey(field, country)``. */
export function winningEvidence<T extends EvidenceLike>(evidence: readonly T[]): Map<string, T> {
  const best = new Map<string, T>();
  for (const e of evidence) {
    if (!PUBLISHED.has(e.status)) continue;
    const key = cellKey(e.field, e.country);
    const current = best.get(key);
    if (!current || compare(e, current) > 0) best.set(key, e);
  }
  return best;
}

function compare(a: EvidenceLike, b: EvidenceLike): number {
  const rank = (RANK[a.source_kind] ?? 0) - (RANK[b.source_kind] ?? 0);
  if (rank !== 0) return rank;
  return (a.confidence ?? 0) - (b.confidence ?? 0);
}

export interface VariantIdentity {
  make_name: string | null;
  model_name: string | null;
  trim_name: string | null;
  model_year: number | null;
  engine_displacement_l: number | string | null;
  fuel_type: string | null;
  transmission_type: string | null;
  drivetrain: string | null;
}

/** "Chevrolet Tracker LS 2020 1.8 L Gasoline Manual FWD": the same text kb.review_queue shows
 *  as the entity_label of a variant. */
export function variantLabel(v: VariantIdentity): string {
  return [v.make_name, v.model_name, v.trim_name, v.model_year, engineText(v)].filter(Boolean).join(" ");
}

/** "1.8 L Gasoline Manual FWD", or "" when nothing is known. */
export function engineText(v: Omit<VariantIdentity, "make_name" | "model_name" | "trim_name" | "model_year">): string {
  const displacement =
    v.engine_displacement_l === null || v.engine_displacement_l === undefined
      ? null
      : `${Number(v.engine_displacement_l)} L`;
  return [displacement, v.fuel_type, v.transmission_type, v.drivetrain].filter(Boolean).join(" ");
}
