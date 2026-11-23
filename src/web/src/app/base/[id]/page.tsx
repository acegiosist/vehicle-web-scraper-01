import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { ListingsTable } from "@/components/case/listings-table";
import { casesByCell, EquipTable, EvidenceTable, HistoryTable, MechTable } from "@/components/knowledge/sheet";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fieldLabel, formatValue } from "@/lib/fields";
import { knowledgeHref, parseKnowledgeFilters } from "@/lib/filters";
import { formatInt } from "@/lib/format";
import { issueInfo } from "@/lib/issues";
import { statusLabel, vehicleClassLabel, variantLabel, verifiedLabel, winningEvidence } from "@/lib/knowledge";
import {
  getVariant,
  variantEvidence,
  variantHistory,
  variantListings,
  variantOpenCases,
} from "@/lib/queries/knowledge";

export const metadata: Metadata = { title: "Ficha de variante" };

export default function VariantPage(props: PageProps<"/base/[id]">) {
  return (
    <main>
      <Suspense fallback={<VariantSkeleton />}>
        <VariantView {...props} />
      </Suspense>
    </main>
  );
}

const KEY_FIELDS = ["engine_displacement_l", "fuel_type", "transmission_type", "drivetrain"] as const;

async function VariantView({ params, searchParams }: PageProps<"/base/[id]">) {
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const filters = parseKnowledgeFilters(sp);
  const found = await getVariant(id);
  if (!found) notFound();
  const { variant, spec, markets, marketSpecs } = found;
  const [evidence, cases, history, listings] = await Promise.all([
    variantEvidence(id),
    variantOpenCases(id),
    variantHistory(id),
    variantListings(id),
  ]);

  const winners = winningEvidence(evidence);
  const openCases = casesByCell(cases);
  // countries with listings, plus any with a published equipment sheet
  const countries = [...markets];
  for (const m of marketSpecs) {
    if (!countries.some((c) => c.country === m.country)) countries.push({ country: m.country, listings_seen: 0 });
  }
  const listingsSeen = markets.reduce((n, m) => n + m.listings_seen, 0);
  const vehicleClass = vehicleClassLabel(variant.vehicle_class);

  return (
    <div className="space-y-6">
      <Link
        href={knowledgeHref(filters)}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden /> Volver a la base de conocimiento
      </Link>

      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            variant={
              variant.status === "accepted" ? "outline" : variant.status === "rejected" ? "destructive" : "secondary"
            }
          >
            {statusLabel(variant.status)}
          </Badge>
          <Badge variant="outline">Verificada: {verifiedLabel(variant.verified_by)}</Badge>
          {vehicleClass && <Badge variant="outline">{vehicleClass}</Badge>}
          {cases.length > 0 && (
            <Badge variant="secondary">
              {cases.length} {cases.length === 1 ? "caso abierto" : "casos abiertos"}
            </Badge>
          )}
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">{variantLabel(variant)}</h1>
        <p className="text-sm text-muted-foreground">
          Variante #{variant.id} · {formatInt(listingsSeen)} {listingsSeen === 1 ? "anuncio" : "anuncios"}
          {markets.length > 0 ? ` · ${markets.map((m) => m.country).join(", ")}` : ""}
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <Card>
          <CardHeader>
            <CardTitle>Identidad</CardTitle>
            <CardDescription>Lo que define a la variante</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
              <Item label="Marca">
                {variant.make_name} <Muted>· {statusLabel(variant.make_status)}</Muted>
              </Item>
              <Item label="Modelo">
                {variant.model_name} <Muted>· {statusLabel(variant.model_status)}</Muted>
                {(variant.year_from || variant.year_to) && (
                  <Muted>
                    {" "}
                    · {variant.year_from ?? "?"}–{variant.year_to ?? "?"}
                  </Muted>
                )}
              </Item>
              <Item label="Versión">
                {variant.trim_name ? (
                  <>
                    {variant.trim_name} <Muted>· {statusLabel(variant.trim_status)}</Muted>
                  </>
                ) : (
                  <Muted>Sin versión</Muted>
                )}
              </Item>
              <Item label="Año">{variant.model_year}</Item>
              {KEY_FIELDS.map((f) => (
                <Item key={f} label={fieldLabel(f)}>
                  {variant[f] === null ? <Muted>Sin dato</Muted> : formatValue(f, variant[f])}
                </Item>
              ))}
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Casos de revisión abiertos</CardTitle>
            <CardDescription>Datos de esta variante que esperan una decisión</CardDescription>
          </CardHeader>
          <CardContent>
            {cases.length === 0 ? (
              <p className="text-sm text-muted-foreground">Ninguno.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {cases.map((c) => (
                  <li key={c.id}>
                    <Link href={`/cola/${c.id}`} className="hover:underline">
                      {issueInfo(c.issue).title}
                      {c.field ? ` · ${fieldLabel(c.field)}` : ""}
                      {c.country ? ` · ${c.country}` : ""}
                    </Link>{" "}
                    <Muted>#{c.id}</Muted>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Section id="mech" title="Ficha técnica" description="Un valor por variante, igual en todos los países">
        <MechTable spec={spec} winners={winners} cases={openCases} />
      </Section>

      <Section id="equip" title="Equipamiento por país" description="El equipamiento cambia según el mercado">
        <EquipTable countries={countries} marketSpecs={marketSpecs} winners={winners} cases={openCases} />
      </Section>

      <Section
        id="evidence"
        title="Evidencia"
        description="Todos los valores candidatos; la fuente con más prioridad aceptada es la que se publica"
      >
        <details className="group">
          <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
            Ver {formatInt(evidence.length)} {evidence.length === 1 ? "registro" : "registros"} de evidencia
          </summary>
          <div className="mt-3">
            <EvidenceTable evidence={evidence} winners={winners} />
          </div>
        </details>
      </Section>

      <Section id="history" title="Historial de cambios" description="Los últimos 50 cambios de los valores publicados">
        <HistoryTable rows={history} />
      </Section>

      <Section id="listings" title="Anuncios">
        <ListingsTable rows={listings.rows} total={listings.total} field={listings.field} />
      </Section>
    </div>
  );
}

function Section({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={`${id}-heading`} className="space-y-2">
      <div>
        <h2 id={`${id}-heading`} className="text-lg font-semibold">
          {title}
        </h2>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  );
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function Muted({ children }: { children: React.ReactNode }) {
  return <span className="text-muted-foreground">{children}</span>;
}

function VariantSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Cargando la ficha">
      <Skeleton className="h-6 w-56" />
      <Skeleton className="h-10 w-2/3" />
      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <Skeleton className="h-64" />
        <Skeleton className="h-64" />
      </div>
      <Skeleton className="h-96" />
    </div>
  );
}
