import { describe, expect, it } from "vitest";

import {
  catalogUpsertSchema,
  decideCaseSchema,
  evolutionNoteSchema,
  mergeGenerationsSchema,
  setValueSchema,
  splitGenerationSchema,
  userUpsertSchema,
} from "./schemas";

describe("edit schemas", () => {
  it("set_value: an empty value clears the manual one", () => {
    expect(setValueSchema.parse({ entity_type: "generation", entity_id: "7", field: "length_mm", value: " " })).toEqual({
      entity_type: "generation",
      entity_id: 7,
      field: "length_mm",
      value: null,
    });
    expect(setValueSchema.safeParse({ entity_type: "make", entity_id: "7", field: "x" }).success).toBe(false);
    expect(setValueSchema.safeParse({ entity_type: "variant", entity_id: "7", field: "DROP TABLE" }).success).toBe(false);
  });

  it("split and merge", () => {
    expect(splitGenerationSchema.parse({ generation_id: "3", year_from: "2020" })).toEqual({ generation_id: 3, year_from: 2020 });
    expect(splitGenerationSchema.safeParse({ generation_id: "3", year_from: "veinte" }).success).toBe(false);
    expect(mergeGenerationsSchema.safeParse({ source_id: "3", target_id: "3" }).success).toBe(false);
  });

  it("evolution note needs a value and a year", () => {
    expect(evolutionNoteSchema.safeParse({ variant_id: "1", field: "wireless_charger", value: "", year_from: "2026" }).success)
      .toBe(false);
    expect(evolutionNoteSchema.parse({ variant_id: "1", field: "wireless_charger", value: "sí", year_from: "2026" }).year_from)
      .toBe(2026);
  });

  it("catalog and user: checkbox semantics and normalization", () => {
    const base = { table: "segment", code: "SUVCoupe", name_es: "SUV coupé", name_en: "Coupe SUV" };
    expect(catalogUpsertSchema.parse({ ...base, active: "on" }).active).toBe(true);
    expect(catalogUpsertSchema.parse(base).active).toBe(false); // unticked checkbox = absent
    expect(catalogUpsertSchema.safeParse({ ...base, code: "SUV Coupe" }).success).toBe(false);
    expect(catalogUpsertSchema.safeParse({ ...base, table: "kb.make" }).success).toBe(false);
    expect(userUpsertSchema.parse({ email: " Ana@X.co ", role: "revisor", active: "true" })).toMatchObject({
      email: "ana@x.co",
      role: "revisor",
      active: true,
    });
    expect(userUpsertSchema.safeParse({ email: "ana", role: "revisor" }).success).toBe(false);
    expect(userUpsertSchema.safeParse({ email: "a@x.co", role: "admin" }).success).toBe(false);
  });
});

describe("decideCaseSchema", () => {
  it("accepts a plain approval and drops empty fields", () => {
    expect(decideCaseSchema.parse({ case_id: "12", decision: "aprobar", corrected_value: "", class: "", note: " " }))
      .toEqual({ case_id: 12, decision: "aprobar" });
  });

  it("needs a value to correct", () => {
    const r = decideCaseSchema.safeParse({ case_id: "12", decision: "corregir", corrected_value: "  " });
    expect(r.success).toBe(false);
    expect(r.error?.issues[0].message).toMatch(/valor corregido/);
  });

  it("rejects unknown decisions, classes and ids", () => {
    expect(decideCaseSchema.safeParse({ case_id: "12", decision: "borrar" }).success).toBe(false);
    expect(decideCaseSchema.safeParse({ case_id: "12", decision: "aprobar", class: "nave" }).success).toBe(false);
    expect(decideCaseSchema.safeParse({ case_id: "-1", decision: "aprobar" }).success).toBe(false);
    expect(decideCaseSchema.safeParse({ case_id: "abc", decision: "aprobar" }).success).toBe(false);
  });

  it("keeps a class and caps long text", () => {
    expect(decideCaseSchema.parse({ case_id: 3, decision: "aprobar", class: "moto" }).class).toBe("moto");
    expect(decideCaseSchema.safeParse({ case_id: 3, decision: "corregir", corrected_value: "x".repeat(201) }).success)
      .toBe(false);
  });
});
