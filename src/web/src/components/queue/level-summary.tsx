import Link from "next/link";
import { cn } from "cn";

import { type QueueFilters, queueHref } from "@/lib/filters";
import { LEVELS } from "@/lib/issues";

interface Props {
  counts: { level: number; open: number; queued: number }[];
  filters: QueueFilters;
}

export function LevelSummary({ counts, filters }: Props) {
  const byLevel = new Map(counts.map((c) => [c.level, c]));
  const firstOpen = counts.find((c) => c.open > 0)?.level;
  return (
    <nav aria-label="Casos por nivel" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {Object.entries(LEVELS).map(([key, label]) => {
        const level = Number(key);
        const c = byLevel.get(level);
        const active = filters.level === level;
        const waits = firstOpen !== undefined && level > firstOpen && (c?.open ?? 0) > 0;
        return (
          <Link
            key={level}
            href={queueHref(filters, { level: active ? undefined : level, page: undefined })}
            aria-current={active ? "true" : undefined}
            className={cn(
              "rounded-xl border p-3 transition-colors hover:bg-muted/60",
              active && "border-foreground/40 bg-muted",
              !c?.open && "opacity-60",
            )}
          >
            <div className="text-xs text-muted-foreground">
              {level}. {label}
            </div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">{(c?.open ?? 0).toLocaleString("es")}</div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              {c?.queued ? `${c.queued} en cola · ` : ""}
              {waits ? "conviene esperar al nivel " + firstOpen : c?.open ? "abiertos" : "sin casos"}
            </div>
          </Link>
        );
      })}
    </nav>
  );
}
