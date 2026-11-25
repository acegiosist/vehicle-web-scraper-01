import Link from "next/link";

import { ActionStatusBadge } from "@/components/action-status";
import { ActionForm } from "@/components/edit/action-form";
import { SourceComparison, type ComparisonRow } from "@/components/sources/source-comparison";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { lookupSource } from "@/lib/actions/request";
import { fieldLabel, formatValue, sourceLabel, type Catalogs } from "@/lib/fields";
import { formatDate, formatInt } from "@/lib/format";
import type { ExternalSource, Lookup, LookupProposal } from "@/lib/queries/sources";

/**
 * The generation page's external sources (revisor): pick a source, ask it about this generation
 * (the worker queries it and writes nothing), then compare and accept in a modal.
 */
export function SourcePanel({
  generationId,
  countries,
  sources,
  offered,
  lookups,
  powertrainLabels,
  catalogs,
}: {
  generationId: string;
  countries: string[];
  sources: ExternalSource[];
  offered: ExternalSource[];
  lookups: Lookup[];
  powertrainLabels: Map<string, string>;
  catalogs: Catalogs;
}) {
  const names = new Map(sources.map((s) => [s.code, s.name]));
  return (
    <Card size="sm" data-testid="source-panel">
      <CardHeader>
        <CardTitle>Fuentes externas</CardTitle>
        <CardDescription>
          Consulta una fuente para esta generación y sus trenes motrices, compara lo que responde con lo que hay y acepta
          valor por valor. Solo se ofrecen las fuentes activas que aplican a sus países ({countries.join(", ") || "—"});
          se configuran en <Link href="/fuentes" className="underline">Fuentes</Link>.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {offered.length === 0 ? (
          <p className="text-muted-foreground">Ninguna fuente activa aplica a los países de esta generación.</p>
        ) : (
          <ActionForm action={lookupSource} submitLabel="Consultar" className="flex flex-wrap items-end gap-2" testId="source-lookup-form">
            <input type="hidden" name="generation_id" value={generationId} />
            <NativeSelect name="source" aria-label="Fuente" className="w-80" defaultValue={offered[0].code}>
              {offered.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.name}
                </option>
              ))}
            </NativeSelect>
          </ActionForm>
        )}
        {lookups.length > 0 && (
          <ul className="space-y-2" data-testid="lookups">
            {lookups.map((l) => (
              <li key={String(l.id)} className="space-y-1" data-testid="lookup">
                <div className="flex flex-wrap items-center gap-2">
                  <ActionStatusBadge status={l.status} />
                  <span className="font-medium">{names.get(l.source) ?? l.source}</span>
                  <span className="text-xs text-muted-foreground">
                    #{String(l.id)} · {l.requested_by} · {formatDate(l.requested_at)}
                  </span>
                  {l.status === "applied" && l.result && (
                    <>
                      <span className="text-muted-foreground">
                        {formatInt(l.result.proposals.length)} {l.result.proposals.length === 1 ? "valor" : "valores"}
                        {l.result.years.length > 0 && ` · ${l.result.years[0]}–${l.result.years[l.result.years.length - 1]}`}
                      </span>
                      {l.saved && (
                        <span className="text-xs text-muted-foreground" data-testid="lookup-saved">
                          aceptados en la solicitud #{String(l.saved.id)}
                        </span>
                      )}
                      <SourceComparison
                        lookupId={String(l.id)}
                        generationId={generationId}
                        title={`${l.result.source_name}: comparación`}
                        credit={l.result.credit}
                        notes={l.result.notes}
                        rows={l.result.proposals.map((p) => row(p, powertrainLabels, names, catalogs))}
                        saved={!!l.saved}
                      />
                    </>
                  )}
                </div>
                {l.error && <p className="text-destructive">{l.error}</p>}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function row(p: LookupProposal, powertrains: Map<string, string>, names: Map<string, string>, catalogs: Catalogs): ComparisonRow {
  const current = p.current?.value ?? null;
  const same = current !== null && Number(current) === Number(p.value);
  const alternatives = Object.entries(p.alternatives ?? {});
  return {
    key: `${p.entity_type}:${p.entity_id}:${p.field}`,
    group: p.entity_type === "generation" ? "Generación" : `Tren motriz · ${powertrains.get(String(p.entity_id)) ?? `#${p.entity_id}`}`,
    field: fieldLabel(p.field),
    current: formatValue(p.field, current, catalogs),
    currentSource: p.current?.source_kind ? sourceLabel(p.current.source_kind, p.current.source_code, names.get(p.current.source_code ?? "")) : "",
    proposed: formatValue(p.field, p.value, catalogs),
    detail: [
      `${p.records} ${p.records === 1 ? "registro" : "registros"}`,
      p.years.length ? p.years.join(", ") : null,
      p.matched.slice(0, 3).join("; ") + (p.matched.length > 3 ? "…" : ""),
    ].filter(Boolean).join(" · "),
    alternatives: alternatives.length
      ? `También: ${alternatives.map(([v, n]) => `${formatValue(p.field, Number(v), catalogs)} (${n})`).join(", ")}`
      : "",
    same,
    empty: current === null,
  };
}
