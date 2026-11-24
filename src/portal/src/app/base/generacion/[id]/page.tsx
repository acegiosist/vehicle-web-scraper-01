import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { FieldEditor } from "@/components/edit/field-editor";
import { GenerationTools } from "@/components/edit/generation-tools";
import { RecentActions } from "@/components/edit/recent-actions";
import { Sheet } from "@/components/knowledge/sheet";
import { NoAccess } from "@/components/no-access";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { userWithRole } from "@/lib/auth/current-user";
import { hasRole } from "@/lib/auth/roles";
import { formatValue, GENERATION_SHEET } from "@/lib/fields";
import { formatInt, formatYears } from "@/lib/format";
import { recentActionsFor } from "@/lib/queries/actions";
import { generation, getCatalogs } from "@/lib/queries/knowledge";

export const metadata: Metadata = { title: "Generación" };

export default function GenerationPage(props: PageProps<"/base/generacion/[id]">) {
  return (
    <main className="space-y-6">
      <Suspense fallback={<Skeleton className="h-96" />}>
        <GenerationView {...props} />
      </Suspense>
    </main>
  );
}

async function GenerationView({ params }: PageProps<"/base/generacion/[id]">) {
  const user = await userWithRole("lector");
  if (!user) return <NoAccess needed="lector" />;
  const { id } = await params;
  const n = Number(id);
  // Requests first, then the data they change (see recentActionsFor).
  const actions = await recentActionsFor([{ entity_type: "generation", entity_id: n }, { generation_id: n }, { source_id: n }, { target_id: n }]);
  const [found, catalogs] = await Promise.all([generation(id), getCatalogs()]);
  if (!found) notFound();
  const editor = hasRole(user.role, "editor");
  const target = { entityType: "generation" as const, entityId: id };
  const { g, powertrains, variants, evidence, siblings } = found;
  const countries = [...new Set(variants.map((v) => v.country_code))];
  const ptLabel = new Map(powertrains.map((p) => [String(p.id), powertrainLabel(p, catalogs)]));
  return (
    <div className="space-y-6">
      <Link href={`/base/marca/${g.make_id}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft className="size-4" aria-hidden /> {g.make_name}
      </Link>
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight" data-testid="generation-name">
          {g.make_name} {g.name}
        </h1>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span>{formatYears(g.year_from, g.year_to, g.observed_year_from, g.observed_year_to)}</span>
          <Badge variant="outline">{formatValue("body_style_code", g.body_style_code, catalogs)}</Badge>
          <Badge variant={g.status === "verified" ? "secondary" : "outline"}>{g.status}</Badge>
          <span data-testid="generation-listings">{formatInt(g.listings)} anuncios</span>
        </div>
        {siblings.length > 0 && (
          <p className="text-sm text-muted-foreground">
            Otras generaciones del modelo:{" "}
            {siblings.map((s, i) => (
              <span key={String(s.id)}>
                {i > 0 && ", "}
                <Link href={`/base/generacion/${s.id}`} className="underline">
                  {s.name}
                </Link>
              </span>
            ))}
          </p>
        )}
      </div>
      <RecentActions actions={actions} />
      {editor && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card size="sm">
            <CardHeader>
              <CardTitle>Datos de la generación</CardTitle>
              <CardDescription>Nombre, ciclo oficial y estado (verificada cuando una persona la confirmó).</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {(
                [
                  ["Nombre", "name", g.name],
                  ["Año inicio (oficial)", "year_from", g.year_from],
                  ["Año fin (oficial)", "year_to", g.year_to],
                  ["Estado", "status", g.status],
                ] as const
              ).map(([label, field, value]) => (
                <div key={field}>
                  <span className="text-muted-foreground">{label}:</span> <span className="font-medium">{value ?? "—"}</span>
                  <FieldEditor target={target} field={field} catalogs={catalogs} current={value} />
                </div>
              ))}
            </CardContent>
          </Card>
          <GenerationTools generationId={id} siblings={siblings} />
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Nivel 1 · Generación</CardTitle>
            <CardDescription>Lo que comparten todas sus versiones.</CardDescription>
          </CardHeader>
          <CardContent>
            <Sheet
              fields={GENERATION_SHEET}
              values={g as Record<string, unknown>}
              evidence={evidence}
              catalogs={catalogs}
              edit={editor ? target : undefined}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Nivel 2 · Trenes motrices</CardTitle>
            <CardDescription>Combinaciones mecánicas vistas en los anuncios.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Motor</TableHead>
                  <TableHead>Potencia</TableHead>
                  <TableHead className="text-right">Anuncios</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {powertrains.map((p) => (
                  <TableRow key={String(p.id)}>
                    <TableCell>
                      <Link href={`/base/tren-motriz/${p.id}`} className="underline-offset-2 hover:underline">
                        {ptLabel.get(String(p.id))}
                      </Link>
                    </TableCell>
                    <TableCell>{formatValue("horsepower_hp", p.horsepower_hp)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatInt(p.listings)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Nivel 3 · Variantes comerciales por país</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {countries.map((c) => (
            <section key={c} className="space-y-2">
              <h2 className="font-medium">{catalogs.country?.[c] ?? c}</h2>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Versión</TableHead>
                    <TableHead>Tren motriz</TableHead>
                    <TableHead>Años de venta</TableHead>
                    <TableHead className="text-right">Anuncios</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {variants
                    .filter((v) => v.country_code === c)
                    .map((v) => (
                      <TableRow key={String(v.id)}>
                        <TableCell>
                          <Link href={`/base/variante/${v.id}`} className="underline-offset-2 hover:underline">
                            {v.trim_name ?? <span className="italic text-muted-foreground">sin versión</span>}
                          </Link>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">{ptLabel.get(String(v.powertrain_id))}</TableCell>
                        <TableCell>
                          {v.sale_year_from}–{v.sale_year_to}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{formatInt(v.listings)}</TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
            </section>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

type Catalogs = Awaited<ReturnType<typeof getCatalogs>>;

function powertrainLabel(
  p: {
    engine_displacement_l: number | null;
    engine_cylinders: number | null;
    fuel_type_code: string | null;
    transmission_type_code: string | null;
    drivetrain_code: string | null;
  },
  catalogs: Catalogs,
): string {
  const engine = p.engine_displacement_l
    ? `${p.engine_displacement_l.toFixed(1)} L`
    : p.engine_cylinders
      ? `${p.engine_cylinders} cil.`
      : "cilindraje ?";
  return [
    engine,
    formatValue("fuel_type_code", p.fuel_type_code, catalogs),
    formatValue("transmission_type_code", p.transmission_type_code, catalogs),
    formatValue("drivetrain_code", p.drivetrain_code, catalogs),
  ].join(" · ");
}
