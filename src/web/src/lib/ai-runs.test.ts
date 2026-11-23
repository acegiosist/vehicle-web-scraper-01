import { describe, expect, it } from "vitest";

import { countsText, parseCounts, runKindLabel, runStatusLabel, sinceText } from "./ai-runs";

describe("parseCounts", () => {
  it("reads the worker's counts and treats anything malformed as 0", () => {
    expect(parseCounts({ succeeded: 4, errored: 1, expired: "2", canceled: -1 })).toEqual({
      succeeded: 4,
      errored: 1,
      expired: 0,
      canceled: 0,
      processing: 0,
    });
    expect(parseCounts(null)).toBeNull();
    expect(parseCounts([1, 2])).toBeNull();
  });
});

describe("countsText", () => {
  it("says how many requests came back right, and what went wrong", () => {
    const ok = { succeeded: 5, errored: 0, expired: 0, canceled: 0, processing: 0 };
    expect(countsText(ok, 5)).toBe("5 de 5 correctas");
    expect(countsText({ ...ok, succeeded: 3, errored: 1, expired: 1 }, 5)).toBe(
      "3 de 5 correctas, 1 con error, 1 vencida",
    );
    expect(countsText(null, 1)).toBe("1 solicitud");
  });
});

describe("sinceText", () => {
  const now = Date.parse("2026-11-23T15:00:00Z");
  it("is coarse: minutes, hours, days", () => {
    expect(sinceText("2026-11-23T14:59:50Z", now)).toBe("hace menos de un minuto");
    expect(sinceText("2026-11-23T14:48:00Z", now)).toBe("hace 12 min");
    expect(sinceText(new Date("2026-11-23T12:00:00Z"), now)).toBe("hace 3 h");
    expect(sinceText("2026-11-22T14:00:00Z", now)).toBe("hace 1 día");
    expect(sinceText(null, now)).toBe("");
  });
});

describe("labels", () => {
  it("names statuses and kinds in Spanish", () => {
    expect(runStatusLabel("ended")).toBe("Lista para recoger");
    expect(runStatusLabel("other")).toBe("other");
    expect(runKindLabel("specs")).toBe("fichas");
  });
});
