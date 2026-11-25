import { z } from "zod";

import { DECISIONS, MAKE_CLASSES } from "@/lib/issues";

/**
 * Shape checks for the requests the portal queues in kb.web_action. They only stop malformed
 * input early; the worker (kb/worker.py) validates the values against the data and the
 * catalogs and enforces the roles.
 */
const id = z.coerce.number({ error: "Identificador inválido" }).int().positive();
const shortText = (max: number) =>
  z
    .string()
    .trim()
    .max(max, `Máximo ${max} caracteres`)
    .optional()
    .transform((v) => (v ? v : undefined));

export const decideCaseSchema = z
  .object({
    case_id: id,
    decision: z.enum(Object.keys(DECISIONS) as [keyof typeof DECISIONS], { error: "Elige una decisión" }),
    corrected_value: shortText(200),
    class: z
      .enum(Object.keys(MAKE_CLASSES) as [keyof typeof MAKE_CLASSES])
      .optional()
      .or(z.literal("").transform(() => undefined)),
    note: shortText(500),
  })
  .refine((d) => d.decision !== "corregir" || !!d.corrected_value, {
    message: "Para corregir, escribe el valor corregido",
    path: ["corrected_value"],
  });

export type DecideCaseInput = z.infer<typeof decideCaseSchema>;

const year = z.coerce.number({ error: "Año inválido" }).int().min(1900, "Año inválido").max(2100, "Año inválido");
const fieldName = z.string().regex(/^[a-z][a-z0-9_]{1,40}$/, "Campo inválido");

/** A value for one field of a level; empty clears the manual value (the worker checks the field). */
export const setValueSchema = z.object({
  entity_type: z.enum(["generation", "powertrain", "variant"]),
  entity_id: id,
  field: fieldName,
  value: z
    .string()
    .trim()
    .max(200, "Máximo 200 caracteres")
    .optional()
    .transform((v) => (v ? v : null)),
  note: shortText(500),
});

export const splitGenerationSchema = z.object({ generation_id: id, year_from: year });

export const mergeGenerationsSchema = z
  .object({ source_id: id, target_id: id })
  .refine((d) => d.source_id !== d.target_id, { message: "Elige otra generación", path: ["target_id"] });

export const evolutionNoteSchema = z.object({
  variant_id: id,
  field: fieldName,
  value: z.string().trim().min(1, "Escribe el valor").max(200),
  year_from: year,
  note: shortText(500),
});

export const catalogUpsertSchema = z.object({
  table: z.enum([
    "fuel_type", "transmission_type", "drivetrain", "body_style", "segment", "headlight_type", "brake_type",
    "exclusion_reason", "vehicle_class", "country",
  ]),
  code: z.string().trim().regex(/^[A-Za-z0-9]{1,40}$/, "Código: solo letras y números"),
  name_es: shortText(80),
  name_en: shortText(80),
  active: z.preprocess((v) => v === "on" || v === "true" || v === true, z.boolean()),
  vehicle_class_code: z.enum(["car", "motorcycle"]).optional().or(z.literal("").transform(() => undefined)),
  body_style_code: shortText(40),
});

/** Filters of the capture template (kb/specs.py); the worker checks them again. */
export const exportSpecsSchema = z.object({
  make: shortText(60),
  country: z
    .string()
    .trim()
    .toUpperCase()
    .regex(/^([A-Z]{2})?$/, "País: dos letras (CO, US…)")
    .optional()
    .transform((v) => (v ? v : undefined)),
  limit: z.coerce.number({ error: "Límite inválido" }).int().min(1, "Mínimo 1 fila").max(2000, "Máximo 2000 filas"),
});

/** An uploaded template: kb worker SPECS_MAX_BYTES is the same limit. */
export const SPECS_MAX_BYTES = 700 * 1024;

export function checkSpecsFile(file: { name: string; size: number } | null): string | null {
  if (!file || file.size === 0) return "Elige el archivo de la plantilla.";
  if (!/\.xlsx$/i.test(file.name)) return "El archivo debe ser .xlsx (la plantilla descargada aquí).";
  if (file.size > SPECS_MAX_BYTES) return `El archivo pesa más de ${SPECS_MAX_BYTES / 1024} KB.`;
  return null;
}

/** Ask an external source about one generation (kb/sources; the worker checks scope and status). */
export const sourceLookupSchema = z.object({
  generation_id: id,
  source: z.string().regex(/^[a-z0-9_]+$/, "Elige una fuente"),
});

/** The values a person accepted from a lookup: "entity_type:entity_id:field" each. */
export const ACCEPT_KEY = /^(generation|powertrain):(\d+):([a-z0-9_]+)$/;
export const SOURCE_APPLY_MAX = 200;

export function parseAccepted(values: unknown[]): { entity_type: string; entity_id: number; field: string }[] | string {
  const keys = [...new Set(values.filter((v): v is string => typeof v === "string"))];
  if (!keys.length) return "Marca al menos un valor para aceptar.";
  if (keys.length > SOURCE_APPLY_MAX) return `Máximo ${SOURCE_APPLY_MAX} valores por vez.`;
  const out = [];
  for (const k of keys) {
    const m = ACCEPT_KEY.exec(k);
    if (!m) return "Un valor marcado no es válido.";
    out.push({ entity_type: m[1], entity_id: Number(m[2]), field: m[3] });
  }
  return out;
}

/** A source's configuration (editor): countries "US, CO" (empty = all), priority 1-1000. */
export const sourceUpdateSchema = z.object({
  code: z.string().regex(/^[a-z0-9_]+$/, "Fuente inválida"),
  active: z.preprocess((v) => v === "on" || v === "true" || v === true, z.boolean()),
  countries: z
    .string()
    .optional()
    .transform((v) => [...new Set((v ?? "").split(/[\s,;]+/).map((c) => c.trim().toUpperCase()).filter(Boolean))])
    .refine((cs) => cs.every((c) => /^[A-Z]{2}$/.test(c)), "Países: códigos de dos letras separados por comas"),
  priority: z.coerce.number({ error: "Prioridad inválida" }).int().min(1, "Prioridad: 1 a 1000").max(1000, "Prioridad: 1 a 1000"),
});

export const userUpsertSchema = z.object({
  email: z.string().trim().toLowerCase().regex(/^[^@\s]+@[^@\s]+$/, "Correo inválido").max(200),
  name: shortText(120),
  role: z.enum(["lector", "revisor", "editor"], { error: "Elige un rol" }),
  active: z.preprocess((v) => v === "on" || v === "true" || v === true, z.boolean()),
});
