"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/** Re-renders the page while something is in the worker's queue (fast first, then every 5 s). */
export function RefreshWhile({ active }: { active: boolean }) {
  const router = useRouter();
  const [polls, setPolls] = useState(0);
  useEffect(() => {
    if (!active || polls >= 400) return; // ~30 min, then the user reloads
    const t = setTimeout(
      () => {
        router.refresh();
        setPolls((p) => p + 1);
      },
      polls < 20 ? 1500 : 5000,
    );
    return () => clearTimeout(t);
  }, [active, polls, router]);
  return null;
}
