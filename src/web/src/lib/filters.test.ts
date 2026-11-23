import { describe, expect, it } from "vitest";

import {
  caseHref,
  knowledgeHref,
  likePattern,
  parseDecisionFilters,
  parseKnowledgeFilters,
  parseQueueFilters,
  queueHref,
  variantHref,
} from "./filters";

describe("parseQueueFilters", () => {
  it("keeps valid values and drops anything else", () => {
    expect(
      parseQueueFilters({
        level: "2",
        issue: "unresolved_model",
        entity: "model",
        kind: "individual",
        origin: "ai",
        make: "Toyota",
        country: "CO",
        q: " rav ",
        page: "3",
      }),
    ).toEqual({
      level: 2,
      issue: "unresolved_model",
      entity: "model",
      kind: "individual",
      origin: "ai",
      make: "Toyota",
      country: "CO",
      q: "rav",
      page: 3,
    });

    expect(
      parseQueueFilters({
        level: "9",
        issue: "drop_table",
        entity: "user",
        kind: "x",
        origin: "human",
        country: "col",
        page: "-1",
        q: "",
      }),
    ).toEqual({});
  });

  it("takes the first value of a repeated parameter", () => {
    expect(parseQueueFilters({ level: ["1", "2"] })).toEqual({ level: 1 });
  });
});

describe("hrefs", () => {
  it("builds queue and case links without page 1 or empty filters", () => {
    expect(queueHref({ level: 2, page: 1 })).toBe("/cola?level=2");
    expect(queueHref({ level: 2 }, { level: undefined })).toBe("/cola");
    expect(caseHref("7", { issue: "outlier_in_model", page: 4 })).toBe("/cola/7?issue=outlier_in_model");
  });
});

describe("likePattern", () => {
  it("escapes LIKE wildcards typed by the user", () => {
    expect(likePattern("50%_off")).toBe("%50\\%\\_off%");
  });
});

describe("parseKnowledgeFilters", () => {
  it("keeps numeric ids and a plausible year", () => {
    expect(parseKnowledgeFilters({ make: "12", model: "345", year: "2020", page: "2" })).toEqual({
      make: "12",
      model: "345",
      year: 2020,
      page: 2,
    });
  });

  it("drops names, injections and out-of-range years", () => {
    expect(parseKnowledgeFilters({ make: "Toyota", model: "1 OR 1=1", year: "20200", page: "0" })).toEqual({});
    expect(parseKnowledgeFilters({ make: "1234567890123456789" })).toEqual({});
  });
});

describe("knowledge hrefs", () => {
  it("builds list and variant links without page 1 or empty filters", () => {
    expect(knowledgeHref({ make: "3", page: 1 })).toBe("/base?make=3");
    expect(knowledgeHref({ make: "3", model: "9" }, { page: 2 })).toBe("/base?make=3&model=9&page=2");
    expect(knowledgeHref({ make: "3" }, { make: undefined })).toBe("/base");
    expect(variantHref("42", { year: 2020, page: 5 })).toBe("/base/42?year=2020");
  });
});

describe("parseDecisionFilters", () => {
  it("validates status and reviewer", () => {
    expect(parseDecisionFilters({ status: "failed", reviewer: "ana" })).toEqual({ status: "failed", reviewer: "ana" });
    expect(parseDecisionFilters({ status: "deleted" })).toEqual({});
  });
});
