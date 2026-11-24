import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { ActionStatusBadge } from "@/components/action-status";
import { KeyValues } from "@/components/key-values";
import { NoAccess } from "@/components/no-access";
import { RefreshWhile } from "@/components/refresh-while";
import { DecisionForm } from "@/components/review/decision-form";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { userWithRole } from "@/lib/auth/current-user";
import { hasRole } from "@/lib/auth/roles";
import { fieldLabel, formatValue, type Catalogs } from "@/lib/fields";
import { formatDate, formatInt } from "@/lib/format";
import { ENTITY_LABELS, ISSUES, isIssue, type Issue } from "@/lib/issues";
import { getCatalogs } from "@/lib/queries/knowledge";
import { caseListing, getCase, parseQueueFilters, queueHref } from "@/lib/queries/review";

export const metadata: Metadata = { title: "Caso" };

export default function CasePage(props: PageProps<"/revision/[id]">) {
  return (
    <main className="space-y-6">
      <Suspense fallback={<Skeleton className="h-5 w-36" />}>
        <BackLink searchParams={props.searchParams} />
      </Suspense>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <CaseView {...props} />
      </Suspense>
    </main>
  );
}

async function BackLink({ searchParams }: Pick<PageProps<"/revision/[id]">, "searchParams">) {
  const href = queueHref(parseQueueFilters(await searchParams));
  return (
    <Link href={href} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
      <ArrowLeft className="size-4" aria-hidden /> Volver a la cola
    </Link>
  );
}

const CORRECTION_HINTS: Partial<Record<Issue, string>> = {
  unknown_make: "Nombre de una marca ya aceptada; esta se une a ella.",
  missing_make: "Nombre de una marca ya aceptada.",
  weak_model: "Nombre del modelo. Si ya existe en la marca, se unen.",
  model_is_attributes: "Nombre del modelo de este anuncio.",
  generation_split: "Año (p. ej. 2020).",
  evolution_note: "Año desde el que aplica.",
};

async function CaseView({ params }: PageProps<"/revision/[id]">) {
  const user = await userWithRole("lector");
  if (!user) return <NoAccess needed="lector" />;
  const { id } = await params;
  const found = await getCase(id);
  if (!found) notFound();
  const { item, requests } = found;
  const issue = isIssue(item.issue) ? item.issue : null;
  const info = issue ? ISSUES[issue] : null;
  const catalogs = await getCatalogs();
  const listing = item.entity_type === "listing" && item.entity_key ? await caseListing(item.entity_key) : null;
  const inFlight = requests.some((r) => r.status === "queued" || r.status === "running");
  const canDecide = hasRole(user.role, "revisor") && item.status === "pending" && !inFlight && info && issue;
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_24rem]">
      <RefreshWhile active={inFlight} />
      <div className="space-y-6">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{info?.label ?? item.issue}</Badge>
            <Badge variant={item.status === "pending" ? "secondary" : "outline"}>{STATUS[item.status ?? ""] ?? item.status}</Badge>
          </div>
          <h1 className="text-xl font-semibold" data-testid="case-entity">
            {item.entity_label ?? `${ENTITY_LABELS[item.entity_type ?? ""]} ${item.entity_key}`}
          </h1>
          <p className="text-sm text-muted-foreground">{info?.what}</p>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>El caso</CardTitle>
          </CardHeader>
          <CardContent>
            <KeyValues
              items={[
                ["Entidad", ENTITY_LABELS[item.entity_type ?? ""] ?? item.entity_type],
                ["Campo", item.field ? fieldLabel(item.field) : "—"],
                ["Valor actual", formatValue(item.field, item.current_value, catalogs)],
                ["Valor propuesto", formatValue(item.field, item.proposed_value, catalogs)],
                ["Anuncios afectados", formatInt(item.listings_affected)],
                ["Abierto", formatDate(item.created_at)],
                ...(item.status !== "pending"
                  ? ([
                      ["Decidió", `${item.decided_by ?? "—"} · ${formatDate(item.decided_at)}`],
                      ["Valor corregido", correctedText(item.field, item.corrected_value, catalogs)],
                      ["Nota", item.note ?? "—"],
                    ] as [string, string][])
                  : []),
              ]}
            />
          </CardContent>
        </Card>
        <Evidence value={item.evidence} catalogs={catalogs} />
        {listing && (
          <Card>
            <CardHeader>
              <CardTitle>El anuncio</CardTitle>
              {item.link && (
                <CardDescription>
                  <a href={item.link} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 underline">
                    Ver en el sitio <ExternalLink className="size-3" aria-hidden />
                  </a>
                </CardDescription>
              )}
            </CardHeader>
            <CardContent>
              <KeyValues
                items={[
                  ["Marca / modelo", `${listing.make_name ?? "—"} ${listing.model_name ?? ""}`],
                  ["Versión", `${listing.trim_name ?? "—"} (anuncio: ${listing.trim_raw ?? "—"})`],
                  ["Año", String(listing.model_year ?? "—")],
                  ["País", catalogs.country?.[listing.country_code] ?? listing.country_code],
                  ["Carrocería", formatValue("body_style_code", listing.body_style_code, catalogs)],
                  ["Combustible", formatValue("fuel_type_code", listing.fuel_type_code, catalogs)],
                  ["Transmisión", formatValue("transmission_type_code", listing.transmission_type_code, catalogs)],
                  ["Tracción", formatValue("drivetrain_code", listing.drivetrain_code, catalogs)],
                  ["Cilindraje", formatValue("engine_displacement_l", listing.engine_displacement_l)],
                  ["Potencia", formatValue("horsepower_hp", listing.horsepower_hp)],
                  ["En la base", listing.variant_id ? <Link href={`/base/variante/${listing.variant_id}`} className="underline">Ver variante</Link> : (listing.excluded_reason ?? listing.unassigned_reason ?? "—")],
                ]}
              />
            </CardContent>
          </Card>
        )}
        {item.entity_type === "generation" && (
          <Link href={`/base/generacion/${item.entity_key}`} className="text-sm underline">
            Ver la generación
          </Link>
        )}
        {item.entity_type === "variant" && (
          <Link href={`/base/variante/${item.entity_key}`} className="text-sm underline">
            Ver la variante
          </Link>
        )}
      </div>
      <aside className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Decidir</CardTitle>
          </CardHeader>
          <CardContent>
            {canDecide ? (
              <DecisionForm
                caseId={String(item.id)}
                issue={issue}
                info={info}
                correctedHint={CORRECTION_HINTS[issue] ?? "El valor correcto para este campo."}
              />
            ) : item.status !== "pending" ? (
              <p className="text-sm text-muted-foreground">Este caso ya está decidido.</p>
            ) : inFlight ? (
              <p className="text-sm text-muted-foreground">Hay una decisión en cola; el worker la está aplicando.</p>
            ) : (
              <NoAccess needed="revisor" />
            )}
          </CardContent>
        </Card>
        {requests.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Decisiones enviadas</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {requests.map((r) => (
                <div key={String(r.id)} className="space-y-1" data-testid="case-request">
                  <div className="flex items-center gap-2">
                    <ActionStatusBadge status={r.status} />
                    <span className="text-muted-foreground">
                      #{String(r.id)} · {r.requested_by} · {formatDate(r.requested_at)}
                    </span>
                  </div>
                  {r.error && <p className="text-destructive">{r.error}</p>}
                </div>
              ))}
            </CardContent>
          </Card>
        )}
      </aside>
    </div>
  );
}

/** What the reviewer wrote, without the worker's internal ids (review.decide's shapes). */
function correctedText(field: string | null, value: unknown, catalogs: Catalogs): string {
  if (value && typeof value === "object") {
    const v = value as Record<string, unknown>;
    if (typeof v.class === "string") return `Clase: ${v.class}`;
    for (const key of ["name", "make", "model"]) if (typeof v[key] === "string") return v[key] as string;
    if (v.year_from != null) return `Desde ${v.year_from}`;
  }
  return formatValue(field, value, catalogs);
}

const STATUS: Record<string, string> = {
  pending: "Pendiente",
  approved: "Aprobado",
  rejected: "Rechazado",
  corrected: "Corregido",
  obsolete: "Obsoleto",
};

function Evidence({ value, catalogs }: { value: unknown; catalogs: Catalogs }) {
  if (!value || typeof value !== "object" || Object.keys(value).length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Evidencia</CardTitle>
      </CardHeader>
      <CardContent>
        <KeyValues
          items={Object.entries(value as Record<string, unknown>).map(([k, v]) => [
            EVIDENCE_LABELS[k] ?? k,
            formatValue(undefined, v, catalogs),
          ])}
        />
      </CardContent>
    </Card>
  );
}

const EVIDENCE_LABELS: Record<string, string> = {
  spellings: "Escrituras",
  sites: "Sitios",
  models: "Modelos",
  trims: "Versiones",
  years: "Años",
  make: "Marca",
  model: "Modelo",
  trim: "Versión",
  year: "Año",
  from: "De dónde sale",
  reason: "Motivo",
  counts: "Valores en los anuncios",
  before: "Antes",
  after: "Después",
  signature: "Se compara",
  engine_displacement_l: "Cilindraje",
};
