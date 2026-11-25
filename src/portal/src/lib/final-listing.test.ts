import { describe, expect, it } from "vitest";

import { FIELDS } from "@/lib/fields";
import { FINAL_SHEET_GROUPS, finalRecordHref, reasonLabel } from "@/lib/final-listing";

describe("final record", () => {
  it("links a listing's record", () => {
    expect(finalRecordHref("carroya", "0a-1")).toBe("/fichas/anuncio/carroya/0a-1");
    expect(finalRecordHref("site x", "a/b")).toBe("/fichas/anuncio/site%20x/a%2Fb");
  });

  it("names the reasons", () => {
    expect(reasonLabel(null)).toBe("Asignado");
    expect(reasonLabel("variant_rejected")).toBe("Variante rechazada");
    expect(reasonLabel("something_new")).toBe("something_new");
  });

  it("labels every field of the sheet once", () => {
    const fields = FINAL_SHEET_GROUPS.flatMap(([, fs]) => fs);
    expect(new Set(fields).size).toBe(fields.length);
    expect(fields.filter((f) => !FIELDS[f])).toEqual([]);
  });
});
