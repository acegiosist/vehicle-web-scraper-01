import { describe, expect, it } from "vitest";

import { cellKey, engineText, sourceLabel, statusLabel, variantLabel, winningEvidence } from "./knowledge";

const ev = (field: string, source_kind: string, status: string, confidence: number | null, country = "") => ({
  field,
  country,
  source_kind,
  status,
  confidence,
});

describe("winningEvidence", () => {
  it("follows the publish precedence: manual > consensus > single > sibling > AI", () => {
    const won = winningEvidence([
      ev("seats", "ai_knowledge", "accepted_sampled", 0.9),
      ev("seats", "listing_single", "accepted", 0.6),
      ev("seats", "listing_consensus", "accepted", 0.8),
      ev("horsepower_hp", "sibling_inference", "accepted", 0.5),
      ev("horsepower_hp", "manual", "accepted", 1),
    ]);
    expect(won.get(cellKey("seats"))?.source_kind).toBe("listing_consensus");
    expect(won.get(cellKey("horsepower_hp"))?.source_kind).toBe("manual");
  });

  it("breaks ties on confidence and keeps countries apart", () => {
    const won = winningEvidence([
      ev("abs", "listing_consensus", "accepted", 0.75, "CO"),
      ev("abs", "listing_consensus", "accepted", 0.9, "CO"),
      ev("abs", "listing_consensus", "accepted", 0.8, "GT"),
    ]);
    expect(won.get(cellKey("abs", "CO"))?.confidence).toBe(0.9);
    expect(won.get(cellKey("abs", "GT"))?.confidence).toBe(0.8);
    expect(won.get(cellKey("abs"))).toBeUndefined();
  });

  it("ignores evidence that is pending or rejected", () => {
    const won = winningEvidence([
      ev("seats", "manual", "rejected", 1),
      ev("seats", "listing_consensus", "pending_review", 0.3),
      ev("doors", "ai_knowledge", "pending_review", 0.9),
      ev("seats", "listing_single", "accepted", 0.6),
    ]);
    expect(won.get(cellKey("seats"))?.source_kind).toBe("listing_single");
    expect(won.has(cellKey("doors"))).toBe(false);
  });
});

describe("labels", () => {
  it("names a variant like the review queue does", () => {
    const v = {
      make_name: "Chevrolet",
      model_name: "Tracker",
      trim_name: null,
      model_year: 2020,
      engine_displacement_l: 1.8,
      fuel_type: "Gasoline",
      transmission_type: "Manual",
      drivetrain: null,
    };
    expect(variantLabel(v)).toBe("Chevrolet Tracker 2020 1.8 L Gasoline Manual");
    expect(engineText({ ...v, engine_displacement_l: null, fuel_type: null, transmission_type: null })).toBe("");
  });

  it("translates known codes and passes unknown ones through", () => {
    expect(statusLabel("pending_review")).toBe("En revisión");
    expect(sourceLabel("manual")).toBe("Verificado por una persona");
    expect(sourceLabel("other")).toBe("other");
    expect(statusLabel(null)).toBe("—");
  });
});
