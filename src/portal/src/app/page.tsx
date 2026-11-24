import { Suspense } from "react";
import type { Metadata } from "next";

import { ActionForm } from "@/components/edit/action-form";
import { NoAccess } from "@/components/no-access";
import { RefreshWhile } from "@/components/refresh-while";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { recalculate } from "@/lib/actions/request";
import { userWithRole } from "@/lib/auth/current-user";
import { hasRole } from "@/lib/auth/roles";
import { formatDate, formatInt } from "@/lib/format";
import { pendingRecalc, totals } from "@/lib/queries/status";

export const metadata: Metadata = { title: "Estado" };

export default function StatusPage() {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Estado de la base</h1>
        <p className="text-sm text-muted-foreground">Cifras en vivo de omnibase.</p>
      </div>
      <Suspense fallback={<Skeleton className="h-40" />}>
        <Status />
      </Suspense>
    </main>
  );
}

async function Status() {
  const user = await userWithRole("lector");
  if (!user) return <NoAccess needed="lector" />;
  const [t, recalc] = await Promise.all([totals(), pendingRecalc()]);
  const tiles: [string, number, string][] = [
    ["Anuncios", t.listings, "versión vigente en staging"],
    ["Dentro del alcance", t.in_scope, "autos y motos, 1990 en adelante"],
    ["En una variante", t.assigned, "llegan a los tres niveles"],
    ["Generaciones", t.generations, "con anuncios"],
    ["Trenes motrices", t.powertrains, "con anuncios"],
    ["Variantes comerciales", t.variants, "con anuncios"],
    ["Casos pendientes", t.pending_cases, "por revisar"],
  ];
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {tiles.map(([label, value, hint]) => (
          <Card key={label}>
            <CardHeader>
              <CardDescription>{label}</CardDescription>
              <CardTitle className="text-2xl tabular-nums">{formatInt(value)}</CardTitle>
            </CardHeader>
            <CardContent className="text-xs text-muted-foreground">{hint}</CardContent>
          </Card>
        ))}
      </div>
      <Card size="sm">
        <RefreshWhile active={recalc.running || recalc.queued} />
        <CardHeader>
          <CardTitle>Recalcular</CardTitle>
          <CardDescription>
            Las decisiones y ediciones se guardan al instante; los anuncios cambian de generación o variante, y los
            valores votados por anuncios se actualizan, al recalcular (limpieza + niveles, ~1,5 min).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p data-testid="recalc-status">
            {recalc.running
              ? "Recalculando…"
              : recalc.queued
                ? "Recálculo en cola."
                : `${formatInt(recalc.changes)} cambios aplicados desde el último recálculo (${formatDate(recalc.lastRecalc)}).`}
          </p>
          {hasRole(user.role, "editor") && !recalc.running && !recalc.queued && (
            <ActionForm action={recalculate} submitLabel="Recalcular ahora" testId="recalc-form" />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
