import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { EvolutionNoteForm } from "@/components/edit/evolution-note-form";
import { RecentActions } from "@/components/edit/recent-actions";
import { KeyValues } from "@/components/key-values";
import { Sheet } from "@/components/knowledge/sheet";
import { NoAccess } from "@/components/no-access";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { userWithRole } from "@/lib/auth/current-user";
import { hasRole } from "@/lib/auth/roles";
import { fieldLabel, formatValue, VARIANT_SHEET_GROUPS } from "@/lib/fields";
import { formatInt, formatMoney } from "@/lib/format";
import { recentActionsFor } from "@/lib/queries/actions";
import { getCatalogs, variant } from "@/lib/queries/knowledge";

export const metadata: Metadata = { title: "Variante" };

export default function VariantPage(props: PageProps<"/base/variante/[id]">) {
  return (
    <main className="space-y-6">
      <Suspense fallback={<Skeleton className="h-96" />}>
        <VariantView {...props} />
      </Suspense>
    </main>
  );
}

async function VariantView({ params }: PageProps<"/base/variante/[id]">) {
  const user = await userWithRole("lector");
  if (!user) return <NoAccess needed="lector" />;
  const { id } = await params;
  // Requests first, then the data they change (see recentActionsFor).
  const actions = await recentActionsFor([{ entity_type: "variant", entity_id: Number(id) }, { variant_id: Number(id) }]);
  const [found, catalogs] = await Promise.all([variant(id), getCatalogs()]);
  if (!found) notFound();
  const editor = hasRole(user.role, "editor");
  const { v, evidence, notes, listings } = found;
  const values = { ...v, seats: v.seats ?? v.generation_seats } as Record<string, unknown>;
  return (
    <div className="space-y-6">
      <Link href={`/base/generacion/${v.generation_id}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft className="size-4" aria-hidden /> {v.make_name} {v.generation_name}
      </Link>
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight" data-testid="variant-name">
          {v.make_name} {v.model_name} {v.trim_name ?? "(sin versión)"}
        </h1>
        <p className="text-sm text-muted-foreground">
          {catalogs.country?.[v.country_code] ?? v.country_code} · vendida {v.sale_year_from}–{v.sale_year_to} ·{" "}
          {formatInt(v.listings)} anuncios
          {v.trim_unknown && " · reúne los anuncios que no dicen su versión"}
        </p>
      </div>
      <RecentActions actions={actions} />
      <Card>
        <CardHeader>
          <CardTitle>Tren motriz</CardTitle>
        </CardHeader>
        <CardContent>
          <KeyValues
            items={[
              ["Cilindraje", formatValue("engine_displacement_l", v.engine_displacement_l)],
              ["Cilindros", formatValue("engine_cylinders", v.engine_cylinders)],
              ["Combustible", formatValue("fuel_type_code", v.fuel_type_code, catalogs)],
              ["Transmisión", formatValue("transmission_type_code", v.transmission_type_code, catalogs)],
              ["Tracción", formatValue("drivetrain_code", v.drivetrain_code, catalogs)],
              ["Potencia", formatValue("horsepower_hp", v.horsepower_hp)],
            ]}
          />
        </CardContent>
      </Card>
      {(notes.length > 0 || editor) && (
        <Card>
          <CardHeader>
            <CardTitle>Notas de evolución</CardTitle>
            <CardDescription>Cambios desde un año, sin duplicar la ficha.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {notes.length === 0 && <p className="text-sm text-muted-foreground">Sin notas todavía.</p>}
            <ul className="space-y-1 text-sm">
              {notes.map((n) => (
                <li key={String(n.id)}>
                  Desde {n.year_from}: {fieldLabel(n.field)} = {formatValue(n.field, n.value, catalogs)}
                  {n.note && <span className="text-muted-foreground"> · {n.note}</span>}
                </li>
              ))}
            </ul>
            {editor && <EvolutionNoteForm variantId={id} />}
          </CardContent>
        </Card>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        {VARIANT_SHEET_GROUPS.map(([title, fields]) => (
          <Card key={title}>
            <CardHeader>
              <CardTitle>{title}</CardTitle>
            </CardHeader>
            <CardContent>
              <Sheet
                fields={fields}
                values={values}
                evidence={evidence}
                catalogs={catalogs}
                edit={editor ? { entityType: "variant", entityId: id } : undefined}
              />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Anuncios</CardTitle>
          <CardDescription>Los 50 más recientes.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Año</TableHead>
                <TableHead>Versión en el anuncio</TableHead>
                <TableHead>Precio</TableHead>
                <TableHead className="text-right">Km</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {listings.map((l) => (
                <TableRow key={`${l.source_site}:${l.listing_id}`}>
                  <TableCell>{l.model_year}</TableCell>
                  <TableCell>{l.trim_raw ?? "—"}</TableCell>
                  <TableCell>{formatMoney(l.price, l.currency_code)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatInt(l.mileage_km)}</TableCell>
                  <TableCell>
                    {l.url && (
                      <a href={l.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs underline">
                        {l.source_site} <ExternalLink className="size-3" aria-hidden />
                      </a>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
