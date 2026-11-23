import { describe, expect, it } from "vitest";

import { checkDecision, decisionFormSchema } from "./decision-input";

const spec = { issue: "outlier_in_model", field: "fuel_tank_capacity_l", entity_type: "spec" };
const variant = { issue: "title_vs_displacement", field: "", entity_type: "variant" };
const model = { issue: "unresolved_model", field: "", entity_type: "model" };
const make = { issue: "unresolved_make", field: "", entity_type: "make" };

describe("decisionFormSchema", () => {
  it("only accepts numeric ids and known decisions", () => {
    expect(decisionFormSchema.safeParse({ itemId: "12", decision: "approved" }).success).toBe(true);
    expect(decisionFormSchema.safeParse({ itemId: "1 OR 1=1", decision: "approved" }).success).toBe(false);
    expect(decisionFormSchema.safeParse({ itemId: "12", decision: "delete" }).success).toBe(false);
    expect(decisionFormSchema.safeParse({ itemId: "12", decision: "approved", note: "x".repeat(2001) }).success).toBe(
      false,
    );
  });
});

describe("checkDecision", () => {
  it("approves and rejects without a value; a blank note becomes null", () => {
    expect(checkDecision(spec, { itemId: "1", decision: "approved", note: "  " })).toEqual({
      ok: true,
      decision: "approved",
      corrected: null,
      note: null,
    });
  });

  it("validates spec corrections against the field", () => {
    expect(checkDecision(spec, { itemId: "1", decision: "corrected", corrected: "44" })).toMatchObject({
      ok: true,
      corrected: "44",
    });
    expect(checkDecision(spec, { itemId: "1", decision: "corrected", corrected: "2000" })).toMatchObject({ ok: false });
    expect(checkDecision(spec, { itemId: "1", decision: "corrected", corrected: "" })).toMatchObject({ ok: false });
  });

  it("refuses decisions that do nothing for the case", () => {
    expect(checkDecision(variant, { itemId: "1", decision: "corrected", corrected: "2.0" })).toMatchObject({
      ok: false,
    });
    expect(checkDecision(variant, { itemId: "1", decision: "rejected" })).toMatchObject({ ok: true });
  });

  it("accepts names and merge targets for identity cases", () => {
    expect(checkDecision(make, { itemId: "1", decision: "corrected", corrected: "Mercedes-Benz" })).toMatchObject({
      ok: true,
      corrected: "Mercedes-Benz",
    });
    expect(
      checkDecision(model, { itemId: "1", decision: "corrected", corrected: "merge: Land Cruiser Prado" }),
    ).toMatchObject({
      ok: true,
      corrected: "merge:Land Cruiser Prado",
    });
    expect(checkDecision(model, { itemId: "1", decision: "corrected", corrected: "<script>" })).toMatchObject({
      ok: false,
    });
  });

  it("splits a model family by version number, optionally setting its class", () => {
    expect(checkDecision(model, { itemId: "1", decision: "corrected", corrected: "split:" })).toMatchObject({
      ok: true,
      corrected: "split:",
    });
    expect(checkDecision(model, { itemId: "1", decision: "corrected", corrected: "split: Heavy" })).toMatchObject({
      ok: true,
      corrected: "split:heavy",
    });
    expect(checkDecision(model, { itemId: "1", decision: "corrected", corrected: "split:truck" })).toMatchObject({
      ok: false,
    });
    // only models can be split: for a make it is just an (invalid) name
    expect(checkDecision(make, { itemId: "1", decision: "corrected", corrected: "split:" })).toMatchObject({
      ok: false,
    });
  });
});
