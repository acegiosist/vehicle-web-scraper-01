"use server";

import { cookies } from "next/headers";
import { refresh } from "next/cache";

import { REVIEWER_COOKIE, reviewerSchema } from "@/lib/reviewer-schema";

export type ReviewerState = { error?: string };

export async function setReviewer(_prev: ReviewerState, formData: FormData): Promise<ReviewerState> {
  const parsed = reviewerSchema.safeParse(formData.get("reviewer"));
  if (!parsed.success) return { error: parsed.error.issues[0]?.message };
  (await cookies()).set(REVIEWER_COOKIE, parsed.data, {
    httpOnly: true,
    sameSite: "strict",
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
  });
  refresh();
  return {};
}
