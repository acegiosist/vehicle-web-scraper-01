// Validation of a decision before it is queued. Pure (no database), so it is unit-tested and
// runs the same way in the Server Action whatever the browser sent.
import { z } from "zod";

import { validateFieldValue } from "./fields";
import { allowedDecisions, type Decision, issueInfo } from "./issues";
import { VEHICLE_CLASSES } from "./knowledge";

export const decisionFormSchema = z.object({
  itemId: z.string().regex(/^\d{1,18}$/, "Caso inválido."),
  decision: z.enum(["approved", "rejected", "corrected"], { error: "Elige una decisión." }),
  corrected: z.string().max(500, "Máximo 500 caracteres.").optional(),
  note: z.string().max(2000, "La nota admite máximo 2000 caracteres.").optional(),
});

export type DecisionForm = z.infer<typeof decisionFormSchema>;

export interface CaseForValidation {
  issue: string | null;
  field: string | null;
  entity_type: string | null;
}

const NAME = /^[\p{L}\p{N}][\p{L}\p{N} .&'/+-]{0,79}$/u;

export type CheckedDecision =
  { ok: true; decision: Decision; corrected: string | null; note: string | null } | { ok: false; error: string };

/** Is this decision possible for this case, and is the corrected value well formed? */
export function checkDecision(item: CaseForValidation, form: DecisionForm): CheckedDecision {
  const allowed = allowedDecisions(item.issue);
  if (!allowed.includes(form.decision)) {
    return { ok: false, error: "Esa decisión no aplica a este tipo de caso." };
  }
  const note = form.note?.trim() || null;
  if (form.decision !== "corrected") return { ok: true, decision: form.decision, corrected: null, note };

  const raw = form.corrected?.trim() ?? "";
  if (!raw) return { ok: false, error: "Escribe el valor correcto." };
  const kind = issueInfo(item.issue).correction;
  if (kind === "field") {
    if (!item.field) return { ok: false, error: "Este caso no tiene un campo que corregir." };
    const v = validateFieldValue(item.field, raw);
    return v.ok ? { ok: true, decision: "corrected", corrected: v.value, note } : { ok: false, error: v.error };
  }
  // "split:" / "split:heavy": the model is a family, the version's leading number is the model
  // (mirrors apply_decision in src/vehicle_scraper/kb/review.py)
  if (kind === "model_name" && raw.toLowerCase().startsWith("split:")) {
    const cls = raw.slice(6).trim().toLowerCase();
    return cls === "" || (VEHICLE_CLASSES as readonly string[]).includes(cls)
      ? { ok: true, decision: "corrected", corrected: `split:${cls}`, note }
      : { ok: false, error: "Clase de vehículo inválida." };
  }
  if (kind === "model_name" && raw.toLowerCase().startsWith("merge:")) {
    const target = raw.slice(6).trim();
    return NAME.test(target)
      ? { ok: true, decision: "corrected", corrected: `merge:${target}`, note }
      : { ok: false, error: "Elige el modelo con el que se fusiona." };
  }
  if (!NAME.test(raw)) {
    return { ok: false, error: "El nombre admite letras, números, espacios y . & ' / + - (máx. 80)." };
  }
  return { ok: true, decision: "corrected", corrected: raw, note };
}
