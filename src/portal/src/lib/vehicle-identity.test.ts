import { describe, expect, it } from "vitest";

import { identityHref, identityListHref, parseIdentityFilters, statusLabel, yearRange } from "@/lib/vehicle-identity";

describe("vehicle identity sheets", () => {
  it("keeps valid filters and drops the rest", () => {
    expect(parseIdentityFilters({ pais: "co", estado: "verificadas", version: "conocida", q: "  kia  ", pagina: "2", por: "20" }))
      .toEqual({ country: "CO", status: "verificadas", knownTrim: true, q: "kia", page: 2, size: 20 });
    expect(parseIdentityFilters({ pais: "Colombia", estado: "rejected", version: "x", q: "" }))
      .toEqual({ country: undefined, status: undefined, knownTrim: false, q: undefined, page: 1, size: 50 });
  });

  it("round-trips through the list link", () => {
    const f = parseIdentityFilters({ pais: "US", estado: "provisionales", version: "conocida", q: "ram 1500", por: "10", pagina: "3" });
    const href = identityListHref(f);
    expect(href).toBe("/fichas?pais=US&estado=provisionales&version=conocida&q=ram+1500&por=10&pagina=3");
    expect(parseIdentityFilters(Object.fromEntries(new URL(href, "http://x").searchParams))).toEqual(f);
    expect(identityListHref(parseIdentityFilters({}))).toBe("/fichas");
  });

  it("links a sheet and remembers the list", () => {
    expect(identityHref("42")).toBe("/fichas/42");
    expect(identityHref(7, parseIdentityFilters({ pais: "IN", pagina: "2" }))).toBe("/fichas/7?pais=IN&pagina=2");
  });

  it("names statuses and year ranges", () => {
    expect(statusLabel("verified")).toBe("Verificada");
    expect(statusLabel(null)).toBe("—");
    expect(yearRange(2017, 2022)).toBe("2017–2022");
    expect(yearRange(2017, null)).toBe("2017–");
    expect(yearRange(2019, 2019)).toBe("2019");
    expect(yearRange(null, null)).toBe("—");
  });
});
