import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { KeyValues } from "@/components/key-values";
import { NoAccess } from "@/components/no-access";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { userWithRole } from "@/lib/auth/current-user";
import { fieldLabel, formatValue, SOURCE_LABELS, type Catalogs } from "@/lib/fields";
import { FINAL_SHEET_GROUPS, finalRecordHref } from "@/lib/final-listing";
import { formatDate, formatInt, formatMoney } from "@/lib/format";
import { getCatalogs } from "@/lib/queries/knowledge";
import { identity } from "@/lib/queries/final";
import { identityListHref, parseIdentityFilters, statusLabel, yearRange } from "@/lib/vehicle-identity";

export const metadata: Metadata = { title: "Ficha del vehículo" };

interface Note {
  field: string;
  value: unknown;
  year_from: number;
  note: string | null;
  source: string;
}

export default function IdentityPage(props: PageProps<"/fichas/[id]">) {
  return (
    <main className="space-y-6">
      <Suspense fallback={<Skeleton className="h-96" />}>
        <IdentityView {...props} />
      </Suspense>
    </main>
  );
}

async function IdentityView({ params, searchParams }: PageProps<"/fichas/[id]">) {
  if (!(await userWithRole("lector"))) return <NoAccess needed="lector" />;
  const [{ id }, sp] = await Promise.all([params, searchParams]);
  const [found, catalogs] = await Promise.all([identity(id), getCatalogs()]);
  if (!found) notFound();
  const { sheet: v, listings } = found;
  const values = v as unknown as Record<string, unknown>;
  const sources = (v.sources ?? {}) as Record<string, string>;
  const notes = (v.evolution_notes ?? []) as unknown as Note[];
  const level = (href: string, text: string, status: string) => (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Link href={href} className="underline">
        {text}
      </Link>
      <span className="text-xs text-muted-foreground">{statusLabel(status)}</span>
    </span>
  );
  return (
    <div className="space-y-6">
      <Link href={identityListHref(parseIdentityFilters(sp))} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft className="size-4" aria-hidden /> Fichas
      </Link>
      <div className="space-y-1">
        <h1 className="flex flex-wrap items-center gap-2 text-2xl font-semibold tracking-tight">
          <span data-testid="identity-name">
            {v.make} {v.model} {v.trim ?? "(sin versión)"}
          </span>
          <Badge variant={v.variant_status === "verified" ? "secondary" : "outline"} data-testid="identity-status">
            {statusLabel(v.variant_status)}
          </Badge>
        </h1>
        <p className="text-sm text-muted-foreground">
          {catalogs.country?.[v.country_code] ?? v.country_code} · {v.generation_name} · vendida{" "}
          {yearRange(v.sale_year_from, v.sale_year_to)} · {formatInt(v.listings)}{" "}
          {v.listings === 1 ? "anuncio" : "anuncios"}
          {v.trim_unknown && " · reúne los anuncios que no dicen su versión: el equipamiento puede mezclar versiones"}
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Identidad</CardTitle>
        </CardHeader>
        <CardContent>
          <KeyValues
            items={[
              ["Marca y modelo", `${v.make} ${v.model}`],
              ["Clase", v.vehicle_class_code ? (catalogs.vehicle_class?.[v.vehicle_class_code] ?? v.vehicle_class_code) : "—"],
              ["Generación", level(`/base/generacion/${v.generation_id}`, v.generation_name, v.generation_status)],
              ["Código de generación", v.generation_code ?? "—"],
              ["Ciclo oficial", yearRange(v.year_from, v.year_to)],
              ["Años vistos en anuncios", yearRange(v.observed_year_from, v.observed_year_to)],
              ["Tren motriz", level(`/base/tren-motriz/${v.powertrain_id}`, "Ver tren motriz", v.powertrain_status)],
              ["Variante", level(`/base/variante/${v.variant_id}`, "Ver variante", v.variant_status)],
              ["Ficha calculada", formatDate(v.built_at)],
            ]}
          />
          <p className="mt-3 text-xs text-muted-foreground">
            Cada valor es el publicado en la base (gana manual, luego fuente externa, anuncios e IA). Para cambiar uno,
            edítalo en la generación, el tren motriz o la variante; la ficha se actualiza al recalcular.
          </p>
        </CardContent>
      </Card>
      {notes.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Notas de evolución</CardTitle>
            <CardDescription>Cambios desde un año; antes de ese año vale lo que dice la ficha.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1 text-sm" data-testid="identity-notes">
              {notes.map((n) => (
                <li key={`${n.field}:${n.year_from}`}>
                  Desde {n.year_from}: {fieldLabel(n.field)} = {formatValue(n.field, n.value, catalogs)}
                  <span className="text-muted-foreground">
                    {" "}
                    · {SOURCE_LABELS[n.source] ?? n.source}
                    {n.note && ` · ${n.note}`}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        {FINAL_SHEET_GROUPS.map(([title, fields]) => (
          <Card key={title}>
            <CardHeader>
              <CardTitle>{title}</CardTitle>
            </CardHeader>
            <CardContent>
              <Values fields={fields} values={values} sources={sources} catalogs={catalogs} />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Anuncios que la respaldan</CardTitle>
          <CardDescription>
            Los 50 más recientes de {formatInt(v.listings)}; el año abre la ficha final de cada anuncio.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {listings.length === 0 ? (
            <p className="text-sm text-muted-foreground">Sin anuncios en el último recálculo.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Año</TableHead>
                  <TableHead>Precio</TableHead>
                  <TableHead className="text-right">Km</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {listings.map((l) => (
                  <TableRow key={`${l.source_site}:${l.listing_id}`} data-testid="identity-listing">
                    <TableCell>
                      <Link href={finalRecordHref(l.source_site, l.listing_id)} className="underline-offset-2 hover:underline">
                        {l.model_year ?? "—"}
                      </Link>
                    </TableCell>
                    <TableCell>{formatMoney(l.price, l.currency)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatInt(l.mileage_km)}</TableCell>
                    <TableCell>
                      {l.source_url && (
                        <a href={l.source_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs underline">
                          {l.source_site} <ExternalLink className="size-3" aria-hidden />
                        </a>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/** A group of the sheet: label, value and where the value came from. */
function Values({ fields, values, sources, catalogs }: {
  fields: string[];
  values: Record<string, unknown>;
  sources: Record<string, string>;
  catalogs: Catalogs;
}) {
  return (
    <Table>
      <TableBody>
        {fields.map((f) => (
          <TableRow key={f}>
            <TableCell className="w-1/2 align-top text-muted-foreground">{fieldLabel(f)}</TableCell>
            <TableCell className="align-top font-medium" data-field={f}>
              {formatValue(f, values[f], catalogs)}
            </TableCell>
            <TableCell className="w-28 align-top text-right" data-source={f}>
              {sources[f] && (
                <Badge variant={sources[f] === "manual" ? "secondary" : "outline"}>{SOURCE_LABELS[sources[f]] ?? sources[f]}</Badge>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
