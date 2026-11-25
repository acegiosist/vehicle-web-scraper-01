import { fieldLabel } from "./fields";

export const ACTION_LABELS: Record<string, string> = {
  decide_case: "Decisión",
  set_value: "Valor",
  split_generation: "Corte de generación",
  merge_generations: "Unión de generaciones",
  add_evolution_note: "Nota de evolución",
  catalog_upsert: "Catálogo",
  user_upsert: "Usuario",
  recalculate: "Recálculo",
  export_specs: "Plantilla de captura",
  import_specs: "Captura subida",
};

/** A short text of what a request asked for. */
export function describePayload(kind: string, payload: unknown): string {
  const p = (payload ?? {}) as Record<string, unknown>;
  switch (kind) {
    case "decide_case":
      return `caso #${p.case_id}: ${p.decision}${p.corrected_value ? ` → ${p.corrected_value}` : ""}`;
    case "set_value":
      return `${fieldLabel(String(p.field))} = ${p.value ?? "(quitar valor manual)"}`;
    case "split_generation":
      return `desde ${p.year_from}`;
    case "merge_generations":
      return `#${p.source_id} en #${p.target_id}`;
    case "add_evolution_note":
      return `${fieldLabel(String(p.field))} = ${p.value} desde ${p.year_from}`;
    case "catalog_upsert":
      return `${p.table}: ${p.code}`;
    case "user_upsert":
      return `${p.email}: ${p.role}${p.active === false ? " (inactivo)" : ""}`;
    case "export_specs":
      return [p.make, p.country, p.limit ? `${p.limit} filas` : null].filter(Boolean).join(" · ") || "todas";
    case "import_specs":
      return String(p.file_name ?? "");
    default:
      return "";
  }
}
