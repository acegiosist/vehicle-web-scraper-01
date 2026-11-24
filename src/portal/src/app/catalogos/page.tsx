import { Suspense } from "react";
import type { Metadata } from "next";

import { ActionForm } from "@/components/edit/action-form";
import { RecentActions } from "@/components/edit/recent-actions";
import { NoAccess } from "@/components/no-access";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { upsertCatalog } from "@/lib/actions/request";
import { userWithRole } from "@/lib/auth/current-user";
import { hasRole } from "@/lib/auth/roles";
import { catalogTables, recentActionsFor } from "@/lib/queries/actions";

export const metadata: Metadata = { title: "Catálogos" };

const TITLES: Record<string, string> = {
  segment: "Segmentos",
  headlight_type: "Tipos de faros",
  brake_type: "Tipos de frenos",
  body_style: "Carrocerías",
  fuel_type: "Combustibles",
  transmission_type: "Transmisiones",
  drivetrain: "Tracciones",
  exclusion_reason: "Motivos de exclusión",
  vehicle_class: "Clases de vehículo",
  country: "Países",
};
/** New codes only where no rule depends on them (kb/worker.py NEW_CODES_ALLOWED). */
const OPEN = new Set(["segment", "headlight_type", "brake_type"]);

export default function CatalogsPage() {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Catálogos</h1>
        <p className="text-sm text-muted-foreground">
          Listas cerradas de la base. Se pueden renombrar o desactivar valores; solo segmentos, faros y frenos admiten
          valores nuevos (los demás los usan las reglas de limpieza y el scraper).
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Catalogs />
      </Suspense>
    </main>
  );
}

async function Catalogs() {
  const user = await userWithRole("lector");
  if (!user) return <NoAccess needed="lector" />;
  const editor = hasRole(user.role, "editor");
  const [tables, actions] = await Promise.all([catalogTables(), recentActionsFor([{ table: "segment" }, { table: "headlight_type" }, { table: "brake_type" }, { table: "fuel_type" }, { table: "transmission_type" }, { table: "drivetrain" }, { table: "body_style" }, { table: "exclusion_reason" }, { table: "vehicle_class" }, { table: "country" }])]);
  return (
    <div className="space-y-6">
      <RecentActions actions={actions} />
      <div className="grid gap-6 lg:grid-cols-2">
        {tables.map(({ table, rows }) => (
          <Card key={table} size="sm">
            <CardHeader>
              <CardTitle>{TITLES[table] ?? table}</CardTitle>
              <CardDescription>
                <code>kb.{table}</code>
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Código</TableHead>
                    <TableHead>Nombre</TableHead>
                    <TableHead>English</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((r) => (
                    <TableRow key={String(r.code)}>
                      <TableCell className="font-mono text-xs">{String(r.code)}</TableCell>
                      <TableCell>{String(r.name_es)}</TableCell>
                      <TableCell className="text-muted-foreground">{String(r.name_en)}</TableCell>
                      <TableCell className="text-right">
                        {r.active === false && <Badge variant="outline">inactivo</Badge>}
                        {editor && (
                          <details className="text-left text-xs">
                            <summary className="cursor-pointer text-muted-foreground">Editar</summary>
                            <ActionForm action={upsertCatalog} submitLabel="Guardar" className="mt-2 space-y-2">
                              <input type="hidden" name="table" value={table} />
                              <input type="hidden" name="code" value={String(r.code)} />
                              <Input name="name_es" defaultValue={String(r.name_es)} aria-label="Nombre" />
                              <Input name="name_en" defaultValue={String(r.name_en)} aria-label="English" />
                              <label className="flex items-center gap-2">
                                <input type="checkbox" name="active" defaultChecked={r.active !== false} /> Activo
                              </label>
                            </ActionForm>
                          </details>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {editor && OPEN.has(table) && (
                <details className="text-sm">
                  <summary className="cursor-pointer text-muted-foreground">Agregar valor</summary>
                  <ActionForm action={upsertCatalog} submitLabel="Agregar" className="mt-2 space-y-2" testId={`add-${table}`}>
                    <input type="hidden" name="table" value={table} />
                    <input type="hidden" name="active" value="true" />
                    <Input name="code" required placeholder="Código (letras y números)" aria-label="Código" />
                    <Input name="name_es" required placeholder="Nombre en español" aria-label="Nombre" />
                    <Input name="name_en" required placeholder="Nombre en inglés" aria-label="English" />
                    {table === "segment" && (
                      <>
                        <NativeSelect name="vehicle_class_code" required defaultValue="" aria-label="Clase">
                          <option value="" disabled>
                            Clase…
                          </option>
                          <option value="car">Automóvil</option>
                          <option value="motorcycle">Motocicleta</option>
                        </NativeSelect>
                        <Input name="body_style_code" placeholder="Solo para la carrocería (código, opcional)" aria-label="Carrocería" />
                      </>
                    )}
                  </ActionForm>
                </details>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
