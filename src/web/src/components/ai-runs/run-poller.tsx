"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

const EVERY_MS = 60_000;

/** While an AI batch is processing, re-renders the page every minute so the notice switches to
 *  "terminó" without a reload. Skips the refresh while the tab is hidden. */
export function RunPoller({ active }: { active: boolean }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => {
      if (!document.hidden) router.refresh();
    }, EVERY_MS);
    return () => clearInterval(t);
  }, [active, router]);
  return null;
}
