import { describe, expect, it } from "vitest";

import { FIELDS, formatValue, validateFieldValue } from "./fields";

describe("field catalog", () => {
  it("is loaded from the Python-generated file", () => {
    expect(FIELDS.horsepower_hp).toMatchObject({ kind: "int", unit: "hp", critical: true, range: [1, 2000] });
    expect(FIELDS.fuel_type.values).toContain("Diesel");
    expect(FIELDS.abs.group).toBe("equip");
  });
});

describe("validateFieldValue", () => {
  it("accepts numbers in range, with a decimal comma", () => {
    expect(validateFieldValue("fuel_tank_capacity_l", "44")).toEqual({ ok: true, value: "44" });
    expect(validateFieldValue("engine_displacement_l", "1,6")).toEqual({ ok: true, value: "1.6" });
  });

  it("rejects out-of-range, non-numeric and non-integer values", () => {
    expect(validateFieldValue("fuel_tank_capacity_l", "2000")).toMatchObject({ ok: false });
    expect(validateFieldValue("engine_displacement_l", "1600")).toMatchObject({ ok: false }); // cc, not litres
    expect(validateFieldValue("horsepower_hp", "mucho")).toMatchObject({ ok: false });
    expect(validateFieldValue("seats", "5.5")).toMatchObject({ ok: false, error: "Debe ser un número entero." });
    expect(validateFieldValue("horsepower_hp", "150 hp")).toMatchObject({ ok: false });
  });

  it("normalizes booleans and checks enums", () => {
    expect(validateFieldValue("abs", "Sí")).toEqual({ ok: true, value: "true" });
    expect(validateFieldValue("abs", "no")).toEqual({ ok: true, value: "false" });
    expect(validateFieldValue("abs", "quizás")).toMatchObject({ ok: false });
    expect(validateFieldValue("fuel_type", "Diesel")).toEqual({ ok: true, value: "Diesel" });
    expect(validateFieldValue("fuel_type", "diesel")).toMatchObject({ ok: false });
  });

  it("refuses unknown fields and empty values", () => {
    expect(validateFieldValue("price; DROP TABLE x", "1")).toMatchObject({ ok: false });
    expect(validateFieldValue("seats", "  ")).toMatchObject({ ok: false });
  });
});

describe("formatValue", () => {
  it("adds units and reads values stored as text", () => {
    expect(formatValue("fuel_tank_capacity_l", 44)).toBe("44 L");
    expect(formatValue("fuel_tank_capacity_l", "44")).toBe("44 L");
    expect(formatValue("abs", "true")).toBe("Sí");
    expect(formatValue("abs", false)).toBe("No");
    expect(formatValue("tire_size", "205/55R16")).toBe("205/55R16");
    expect(formatValue("seats", null)).toBe("—");
  });
});
