"use server";

import { refresh } from "next/cache";
import { DatabaseError } from "pg";

import { getDb } from "@/lib/db";
import { checkDecision, decisionFormSchema } from "@/lib/decision-input";
import { getReviewer } from "@/lib/reviewer";

export type DecideState =
  { status: "idle" } | { status: "queued"; decisionId: string } | { status: "error"; error: string };

const text = (v: FormDataEntryValue | null) => (typeof v === "string" ? v : undefined);

/**
 * Queues one decision in kb.review_decision. Nothing else: the Python worker applies it with
 * the same code as `kb review import`, and this database role can only INSERT there.
 * Reachable by direct POST, so everything is checked here, not in the form.
 */
export async function submitDecision(_prev: DecideState, formData: FormData): Promise<DecideState> {
  const reviewer = await getReviewer();
  if (!reviewer) return { status: "error", error: "Escribe tu nombre arriba a la derecha antes de decidir." };

  const parsed = decisionFormSchema.safeParse({
    itemId: text(formData.get("itemId")),
    decision: text(formData.get("decision")),
    corrected: text(formData.get("corrected")),
    note: text(formData.get("note")),
  });
  if (!parsed.success) return { status: "error", error: parsed.error.issues[0]?.message ?? "Datos inválidos." };

  const db = getDb();
  const item = await db
    .selectFrom("kb.review_queue")
    .select(["id", "status", "issue", "field", "entity_type", "queued_decision_id"])
    .where("id", "=", parsed.data.itemId)
    .executeTakeFirst();
  if (!item) return { status: "error", error: "El caso no existe." };
  if (item.status !== "pending") return { status: "error", error: "Este caso ya fue decidido." };
  if (item.queued_decision_id) return { status: "error", error: "Ya hay una decisión en cola para este caso." };

  const checked = checkDecision(item, parsed.data);
  if (!checked.ok) return { status: "error", error: checked.error };

  try {
    const row = await db
      .insertInto("kb.review_decision")
      .values({
        review_item_id: parsed.data.itemId,
        decision: checked.decision,
        corrected_value: checked.corrected,
        note: checked.note,
        reviewer,
      })
      .returning("id")
      .executeTakeFirstOrThrow();
    refresh();
    return { status: "queued", decisionId: row.id };
  } catch (err) {
    if (err instanceof DatabaseError && err.code === "23505") {
      return { status: "error", error: "Ya hay una decisión en cola para este caso." };
    }
    console.error("submitDecision failed", err);
    return { status: "error", error: "No se pudo guardar la decisión. Intenta de nuevo." };
  }
}
