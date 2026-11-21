"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/** Re-renders the page while a job is queued or running (fast first, then every 5 s). */
export function JobPoller({ active }: { active: boolean }) {
  const router = useRouter();
  const [polls, setPolls] = useState(0);
  useEffect(() => {
    if (!active || polls >= 400) return; // ~30 min, then the reviewer reloads
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
