import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { DecisionPanel } from "@/components/case/decision-panel";
import { DecisionStatus } from "@/components/case/decision-status";
import { KeyValues } from "@/components/case/key-values";
import { ListingsTable } from "@/components/case/listings-table";
import { ValueDistribution } from "@/components/case/value-distribution";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fieldLabel, FIELDS, formatValue, isField } from "@/lib/fields";
import { caseHref, parseQueueFilters, queueHref } from "@/lib/filters";
import { formatDate, formatInt, formatPercent } from "@/lib/format";
import {
  allowedDecisions,
  DECISION_LABELS,
  type Decision,
  ENTITY_LABELS,
  type EntityType,
  issueInfo,
  levelLabel,
} from "@/lib/issues";
import {
  caseField,
  caseListings,
  correctionTargets,
  getCase,
  publishedValue,
  splitPreview,
  valueDistribution,
} from "@/lib/queries/case";
import { nextCaseId } from "@/lib/queries/queue";
import { vehicleClassLabel } from "@/lib/knowledge";
import { getReviewer } from "@/lib/reviewer";

export const metadata: Metadata = { title: "Caso" };

export default function CasePage(props: PageProps<"/cola/[id]">) {
  return (
    <main>
      <Suspense fallback={<CaseSkeleton />}>
        <CaseView {...props} />
      </Suspense>
    </main>
  );
}

async function CaseView({ params, searchParams }: PageProps<"/cola/[id]">) {
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const filters = parseQueueFilters(sp);
  const found = await getCase(id);
  if (!found) notFound();
  const { item, decisions } = found;
  const field = caseField(item);
  const info = issueInfo(item.issue);
  const [listings, distribution, published, targets, split, nextId, reviewer] = await Promise.all([
    caseListings(item),
    valueDistribution(item),
    publishedValue(item),
    correctionTargets(item),
    info.correction === "model_name" ? splitPreview(item) : null,
    nextCaseId(filters, id),
    getReviewer(),
  ]);

  const latest = decisions[0];
  const nextHref = nextId ? caseHref(nextId, filters) : null;
  const pending = item.status === "pending";
  const canDecide = pending && !item.queued_decision_id;

  return (
    <div className="space-y-6">
      <Link
        href={queueHref(filters)}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden /> Volver a la cola
      </Link>

      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{levelLabel(item.level)}</Badge>
          <Badge variant="secondary">{info.title}</Badge>
          {item.from_ai && <Badge>Propuesta de la IA · corrida #{item.ai_run_id ?? "?"}</Badge>}
          {item.kind === "sample" && <Badge variant="outline">Muestra del lote {item.review_batch_id}</Badge>}
          {!pending && <Badge>{statusLabel(item.status)}</Badge>}
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">{item.entity_label ?? "?"}</h1>
        <p className="text-sm text-muted-foreground">
          {ENTITY_LABELS[item.entity_type as EntityType] ?? item.entity_type} #{item.entity_id}
          {item.field ? ` · ${fieldLabel(item.field)}` : ""}
          {item.country ? ` · ${item.country}` : ""} · {formatInt(item.listings_affected)} anuncios afectados · caso #
          {item.id}
        </p>
        {info.question && <p className="max-w-3xl">{info.question}</p>}
      </header>

      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <div className="min-w-0 space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Card className={item.from_ai ? "ring-2 ring-primary/40" : undefined}>
              <CardHeader>
                <CardTitle>{item.from_ai ? "Propuesta de la IA" : "Propuesta"}</CardTitle>
                <CardDescription>
                  {item.from_ai
                    ? `Corrida #${item.ai_run_id ?? "?"} de Claude${confidenceText(item.proposed)}. Nada de la IA se acepta sin tu revisión.`
                    : "Lo que propone la regla"}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <KeyValues data={item.proposed} field={field} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Lo que se sabe</CardTitle>
                <CardDescription>Datos actuales del caso</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <KeyValues data={item.current} field={field} />
                {published !== undefined && (
                  <p className="text-sm">
                    <span className="text-muted-foreground">Publicado hoy: </span>
                    {formatValue(item.field, published)}
                  </p>
                )}
              </CardContent>
            </Card>
          </div>

          {item.evidence !== null && (
            <Card>
              <CardHeader>
                <CardTitle>Evidencia</CardTitle>
              </CardHeader>
              <CardContent>
                <KeyValues data={item.evidence} field={field} />
              </CardContent>
            </Card>
          )}

          {distribution.length > 0 && field && (
            <Card>
              <CardHeader>
                <CardTitle>{fieldLabel(field)} según los anuncios</CardTitle>
                <CardDescription>Valor que reporta cada anuncio de la variante</CardDescription>
              </CardHeader>
              <CardContent>
                <ValueDistribution rows={distribution} field={field} />
              </CardContent>
            </Card>
          )}

          <section aria-labelledby="listings-heading" className="space-y-2">
            <h2 id="listings-heading" className="text-lg font-semibold">
              Anuncios
            </h2>
            <ListingsTable rows={listings.rows} total={listings.total} field={listings.field} />
          </section>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-4 lg:self-start">
          {latest && (
            <DecisionStatus
              key={latest.id}
              status={latest.status as "queued" | "applied" | "failed" | "superseded"}
              decision={latest.decision as Decision}
              reviewer={latest.reviewer}
              error={latest.error}
              nextHref={nextHref}
            />
          )}
          {canDecide ? (
            <Card>
              <CardContent>
                <DecisionPanel
                  key={item.id}
                  itemId={item.id ?? ""}
                  allowed={allowedDecisions(item.issue)}
                  effects={info.effects}
                  correction={info.correction}
                  field={
                    isField(item.field)
                      ? { name: item.field, label: fieldLabel(item.field), spec: FIELDS[item.field] }
                      : null
                  }
                  targets={targets}
                  split={split}
                  hasReviewer={!!reviewer}
                  nextHref={nextHref}
                />
              </CardContent>
            </Card>
          ) : (
            !pending && (
              <Card>
                <CardContent className="text-sm">
                  Decidido: <strong>{statusLabel(item.status)}</strong>
                  {item.reviewer ? ` por ${item.reviewer}` : ""} · {formatDate(item.decided_at)}
                  {item.corrected_value !== null && <> · {correctedText(item.field, item.corrected_value)}</>}
                </CardContent>
              </Card>
            )
          )}
          {decisions.length > 1 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Historial del caso</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1 text-xs text-muted-foreground">
                  {decisions.map((d) => (
                    <li key={d.id}>
                      {formatDate(d.submitted_at)} · {d.reviewer} · {DECISION_LABELS[d.decision as Decision]} ·{" "}
                      {statusLabel(d.status)}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}

/** A decided correction in words: identity markers (`merge:`, `split:`) are not values. */
function correctedText(field: string | null, value: unknown): string {
  if (typeof value === "string" && value.startsWith("merge:")) return `fusionado con ${value.slice(6)}`;
  if (typeof value === "string" && value.startsWith("split:")) {
    const cls = vehicleClassLabel(value.slice(6));
    return `dividido por número de versión${cls ? ` (clase ${cls.toLowerCase()})` : ""}`;
  }
  return `valor: ${formatValue(field, value)}`;
}

/** ", confianza 60 %" when the AI proposal carries a confidence (0..1). */
function confidenceText(proposed: unknown): string {
  const c = proposed && typeof proposed === "object" ? (proposed as Record<string, unknown>).confidence : undefined;
  return typeof c === "number" && c >= 0 && c <= 1 ? `, confianza ${formatPercent(c)}` : "";
}

function statusLabel(status: string | null): string {
  return (
    {
      approved: "Aprobado",
      rejected: "Rechazado",
      corrected: "Corregido",
      pending: "Pendiente",
      queued: "En cola",
      applied: "Aplicada",
      failed: "Falló",
      superseded: "Ya decidido",
    }[status ?? ""] ??
    status ??
    "?"
  );
}

function CaseSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Cargando el caso">
      <Skeleton className="h-6 w-40" />
      <Skeleton className="h-10 w-2/3" />
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <Skeleton className="h-96" />
        <Skeleton className="h-80" />
      </div>
    </div>
  );
}
