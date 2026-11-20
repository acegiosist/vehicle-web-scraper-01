import { formatValue } from "@/lib/fields";

/** How many listings report each value (a quick look at "who is right"). */
export function ValueDistribution({
  rows,
  field,
}: {
  rows: { value: string | null; n: number }[];
  field: string | null;
}) {
  const total = rows.reduce((s, r) => s + r.n, 0);
  if (!total) return <p className="text-sm text-muted-foreground">Ningún anuncio reporta este dato.</p>;
  return (
    <ul className="space-y-1.5 text-sm">
      {rows.map((r) => {
        const pct = Math.round((r.n / total) * 100);
        const parsed =
          r.value === "true"
            ? true
            : r.value === "false"
              ? false
              : r.value !== null && Number.isFinite(Number(r.value))
                ? Number(r.value)
                : r.value;
        return (
          <li key={r.value ?? "null"} className="grid grid-cols-[7rem_1fr_4.5rem] items-center gap-2">
            <span className="truncate">{r.value === null ? "Sin dato" : formatValue(field, parsed)}</span>
            <span className="h-2 rounded-full bg-muted" aria-hidden>
              <span className="block h-2 rounded-full bg-foreground/70" style={{ width: `${pct}%` }} />
            </span>
            <span className="text-right tabular-nums text-muted-foreground">
              {r.n} · {pct} %
            </span>
          </li>
        );
      })}
    </ul>
  );
}
