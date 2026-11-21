import { describe, expect, it } from "vitest";

import {
  type AiBudget,
  budgetVerdict,
  confirmsAmount,
  describeParams,
  formatResetsAt,
  parseJobForm,
  safeFilename,
} from "./jobs";

const form = (o: Record<string, string>) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(o)) fd.set(k, v);
  return fd;
};

describe("parseJobForm", () => {
  it("accepts the recalculate commands without parameters", () => {
    for (const c of ["normalize", "consolidate", "recalculate"]) {
      expect(parseJobForm(form({ command: c }))).toEqual({ ok: true, job: { command: c, params: {} } });
    }
  });

  it("refuses commands the site may not queue", () => {
    for (const c of ["migrate", "import", "ai_submit", "", "normalize; drop"]) {
      expect(parseJobForm(form({ command: c }))).toMatchObject({ ok: false });
    }
  });

  it("validates exports", () => {
    expect(parseJobForm(form({ command: "export", format: "xlsx", with_sources: "on" }))).toEqual({
      ok: true,
      job: { command: "export", params: { format: "xlsx", with_sources: true } },
    });
    expect(parseJobForm(form({ command: "export", format: "pdf" }))).toMatchObject({ ok: false });
  });

  it("builds a deterministic AI estimate request", () => {
    const a = parseJobForm(
      form({ command: "ai_estimate", kind: "specs", makes: " Mazda, Toyota,Mazda ", min_listings: "5", limit: "" }),
    );
    expect(a).toEqual({
      ok: true,
      job: { command: "ai_estimate", params: { kind: "specs", makes: ["Mazda", "Toyota"], min_listings: 5 } },
    });
    // identity ignores min_listings; count_tokens only when ticked
    expect(
      parseJobForm(
        form({ command: "ai_estimate", kind: "identity", min_listings: "5", count_tokens: "on", effort: "low" }),
      ),
    ).toEqual({
      ok: true,
      job: { command: "ai_estimate", params: { kind: "identity", effort: "low", count_tokens: true } },
    });
    expect(parseJobForm(form({ command: "ai_estimate", kind: "everything" }))).toMatchObject({ ok: false });
    expect(parseJobForm(form({ command: "ai_estimate", kind: "identity", effort: "max" }))).toMatchObject({
      ok: false,
    });
    expect(parseJobForm(form({ command: "ai_estimate", kind: "identity", limit: "0" }))).toMatchObject({ ok: false });
  });

  it("collects the latest run or a given one", () => {
    expect(parseJobForm(form({ command: "ai_collect", run_id: "" }))).toEqual({
      ok: true,
      job: { command: "ai_collect", params: {} },
    });
    expect(parseJobForm(form({ command: "ai_collect", run_id: "7" }))).toEqual({
      ok: true,
      job: { command: "ai_collect", params: { run_id: 7 } },
    });
    expect(parseJobForm(form({ command: "ai_collect", run_id: "x" }))).toMatchObject({ ok: false });
  });
});

describe("confirmsAmount", () => {
  it("needs exactly the estimated amount", () => {
    expect(confirmsAmount("33.36", 33.36)).toBe(true);
    expect(confirmsAmount("33,36", 33.36)).toBe(true);
    expect(confirmsAmount("US$33.36", 33.36)).toBe(true);
    expect(confirmsAmount("1.9", 1.9)).toBe(true);
    expect(confirmsAmount("33", 33.36)).toBe(false);
    expect(confirmsAmount("33.37", 33.36)).toBe(false);
    expect(confirmsAmount("33.360", 33.36)).toBe(false);
    expect(confirmsAmount("", 0)).toBe(false);
  });
});

describe("safeFilename and describeParams", () => {
  it("keeps download names header-safe", () => {
    expect(safeFilename("kb_listings.csv")).toBe("kb_listings.csv");
    expect(safeFilename('a"b\r\n.csv')).toBe("a_b__.csv");
    expect(safeFilename("../../etc/passwd")).toBe("_.._etc_passwd");
  });

  it("describes parameters for the job list", () => {
    expect(describeParams("export", { format: "csv", with_sources: true })).toBe("CSV, con origen");
    expect(describeParams("ai_estimate", { kind: "specs", makes: ["Mazda"], min_listings: 3 })).toBe(
      "fichas · marcas: Mazda · ≥ 3 anuncios",
    );
    expect(describeParams("ai_submit", { estimate_job_id: 4, confirm_usd: 1.9 })).toBe("estimado #4 · hasta US$1.9");
  });
});

describe("budgetVerdict", () => {
  const budget: AiBudget = {
    limit_usd: 5,
    period: "daily",
    period_start: "2026-11-21T00:00:00-05:00",
    resets_at: "2026-11-22T00:00:00-05:00",
    spent_usd: 1,
    remaining_usd: 4,
    allows: true,
    error: null,
    message: null,
  };

  it("allows a send that fits, up to the limit itself", () => {
    expect(budgetVerdict(budget, 1, 0.5)).toEqual({ allowed: true, message: null });
    expect(budgetVerdict(budget, 4.8, 0.2).allowed).toBe(true);
  });

  it("blocks when what was spent until now plus this send exceeds the limit", () => {
    expect(budgetVerdict(budget, 4.8, 0.4)).toEqual({
      allowed: false,
      message:
        "Se superó el límite de gasto en IA: llevas US$4.80 de US$5.00 hoy y este envío costaría US$0.40. " +
        "Se reinicia el 22/11 00:00.",
    });
  });

  it("blocks without a limit or without budget data", () => {
    const missing = { ...budget, limit_usd: null, error: "falta KB_AI_BUDGET_USD en el .env." };
    expect(budgetVerdict(missing, 0, 0.1)).toEqual({
      allowed: false,
      message: "No se puede enviar a Claude: falta KB_AI_BUDGET_USD en el .env.",
    });
    expect(budgetVerdict(undefined, 0, 0.1).allowed).toBe(false);
  });

  it("reads the reset date as the worker wrote it", () => {
    expect(formatResetsAt("2026-12-01T00:00:00-05:00")).toBe("01/12 00:00");
  });
});
