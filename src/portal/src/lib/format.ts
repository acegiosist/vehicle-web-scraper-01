const dateTime = new Intl.DateTimeFormat("es", { dateStyle: "medium", timeStyle: "short" });
const integer = new Intl.NumberFormat("es");

export function formatDate(value: Date | string | null | undefined): string {
  if (!value) return "—";
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : dateTime.format(d);
}

export function formatInt(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? integer.format(n) : String(value);
}

export function formatMoney(value: number | null | undefined, currency: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${integer.format(Math.round(value))}${currency ? ` ${currency}` : ""}`;
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)} %`;
}

/** A generation's years: the official cycle when known, else what listings show. */
export function formatYears(
  from: number | null | undefined,
  to: number | null | undefined,
  observedFrom?: number | null,
  observedTo?: number | null,
): string {
  if (from || to) return `${from ?? "?"}–${to ?? "hoy"}`;
  return observedFrom ? `${observedFrom}–${observedTo ?? "?"} (visto en anuncios)` : "—";
}
