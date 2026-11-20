import { formatValue } from "@/lib/fields";
import { formatPercent } from "@/lib/format";
import { keyLabel } from "@/lib/issues";

type Json = string | number | boolean | null | Json[] | { [k: string]: Json };

// spec_evidence.source_kind, in the reviewer's words
const SOURCES: Record<string, string> = {
  listing_consensus: "Consenso de anuncios",
  listing_single: "Un solo anuncio",
  sibling_inference: "Heredado de años vecinos",
  ai_knowledge: "Conocimiento de la IA",
  manual: "Verificado por una persona",
};

/** A review_item JSON blob (proposed / current / evidence) as a readable list. */
export function KeyValues({ data, field }: { data: unknown; field: string | null }) {
  if (data === null || data === undefined) return <p className="text-sm text-muted-foreground">Sin datos.</p>;
  if (typeof data !== "object" || Array.isArray(data)) {
    return <p className="text-sm">{renderValue("value", data as Json, field)}</p>;
  }
  const entries = Object.entries(data as Record<string, Json>).filter(([k]) => !k.startsWith("_"));
  if (entries.length === 0) return <p className="text-sm text-muted-foreground">Sin datos.</p>;
  return (
    <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{keyLabel(k)}</dt>
          <dd className="min-w-0 break-words">{renderValue(k, v, field)}</dd>
        </div>
      ))}
    </dl>
  );
}

function renderValue(key: string, v: Json, field: string | null): React.ReactNode {
  if (v === null) return "—";
  if (["value", "top_value", "expected_value", "model_median"].includes(key)) return formatValue(field, v);
  if (key === "agreement" || key === "confidence") return typeof v === "number" ? formatPercent(v) : String(v);
  if (key === "source" && typeof v === "string") return SOURCES[v] ?? v;
  if (typeof v === "boolean") return v ? "Sí" : "No";
  if (Array.isArray(v)) {
    if (v.every((x) => typeof x !== "object" || x === null)) return v.map(String).join(", ") || "—";
    return <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">{JSON.stringify(v, null, 2)}</pre>;
  }
  if (typeof v === "object") {
    const flat = Object.entries(v);
    if (flat.every(([, x]) => typeof x !== "object" || x === null)) {
      return flat.map(([a, b]) => `${a}: ${String(b)}`).join(" · ") || "—";
    }
    return <pre className="overflow-x-auto rounded bg-muted p-2 text-xs">{JSON.stringify(v, null, 2)}</pre>;
  }
  return String(v);
}
