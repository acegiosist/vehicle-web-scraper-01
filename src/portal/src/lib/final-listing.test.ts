import { describe, expect, it } from "vitest";

import { FIELDS } from "@/lib/fields";
import { FINAL_SHEET_GROUPS, finalListHref, finalRecordHref, parseFinalFilters, reasonLabel } from "@/lib/final-listing";

describe("final record filters", () => {
  it("keeps valid filters and drops the rest", () => {
    expect(parseFinalFilters({ pais: "co", estado: "variant_rejected", anio: "2021", q: "  kia  ", pagina: "2", por: "20" }))
      .toEqual({ country: "CO", status: "variant_rejected", year: 2021, q: "kia", page: 2, size: 20 });
    expect(parseFinalFilters({ pais: "Colombia", estado: "constructor", anio: "21", q: "" }))
      .toEqual({ country: undefined, status: undefined, year: undefined, q: undefined, page: 1, size: 50 });
  });

  it("round-trips through the list link", () => {
    const f = parseFinalFilters({ pais: "US", estado: "sin-asignar", anio: "2019", q: "ram 1500", por: "10", pagina: "3" });
    const href = finalListHref(f);
    expect(href).toBe("/fichas?pais=US&estado=sin-asignar&anio=2019&q=ram+1500&por=10&pagina=3");
    expect(parseFinalFilters(Object.fromEntries(new URL(href, "http://x").searchParams))).toEqual(f);
    expect(finalListHref(parseFinalFilters({}))).toBe("/fichas");
  });

  it("links a record and remembers the list", () => {
    expect(finalRecordHref("carroya", "0a-1")).toBe("/fichas/carroya/0a-1");
    expect(finalRecordHref("cars24", "15", parseFinalFilters({ pais: "IN", pagina: "2" })))
      .toBe("/fichas/cars24/15?pais=IN&pagina=2");
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
