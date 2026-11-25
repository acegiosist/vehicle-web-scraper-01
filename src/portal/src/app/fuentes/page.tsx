import { Suspense } from "react";
import type { Metadata } from "next";

import { ActionForm } from "@/components/edit/action-form";
import { RecentActions } from "@/components/edit/recent-actions";
import { NoAccess } from "@/components/no-access";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { updateSource } from "@/lib/actions/request";
import { userWithRole } from "@/lib/auth/current-user";
import { hasRole } from "@/lib/auth/roles";
import { formatDate } from "@/lib/format";
import { recentActionsFor } from "@/lib/queries/actions";
import { externalSources } from "@/lib/queries/sources";

export const metadata: Metadata = { title: "Fuentes" };

export default function SourcesPage() {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Fuentes externas</h1>
        <p className="text-sm text-muted-foreground">
          Fuentes que se consultan desde cada generación (Base → generación → Fuentes externas). Lo que una persona acepta
          queda como fuente externa: gana a los anuncios y pierde ante un valor manual. Entre fuentes externas gana lo
          capturado en la plantilla (Captura) y luego la prioridad de cada fuente (menor primero). Una fuente solo se ofrece
          en las generaciones con variantes en sus países (vacío = todos). Las de pago no se consultan desde el portal.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Sources />
      </Suspense>
    </main>
  );
}

async function Sources() {
  const user = await userWithRole("lector");
  if (!user) return <NoAccess needed="lector" />;
  const editor = hasRole(user.role, "editor");
  // Requests first, then the data they change (see recentActionsFor).
  const codes = (await externalSources()).map((s) => s.code);
  const actions = await recentActionsFor(codes.map((code) => ({ code })));
  const sources = await externalSources();
  return (
    <div className="space-y-6">
      <RecentActions actions={actions} />
      {sources.map((s) => (
        <Card key={s.code} size="sm" data-testid="source" data-code={s.code}>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              {s.name}
              <Badge variant={s.active ? "secondary" : "outline"} data-testid="source-active">
                {s.active ? "Activa" : "Desactivada"}
              </Badge>
              {s.paid && <Badge variant="outline">De pago</Badge>}
            </CardTitle>
            <CardDescription>
              {s.provides}.{" "}
              <a href={s.url} target="_blank" rel="noreferrer noopener" className="underline">
                Documentación
              </a>{" "}
              · Crédito: {s.credit}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p>
              <span className="text-muted-foreground">Países:</span>{" "}
              <span data-testid="source-countries">{s.countries.length ? s.countries.join(", ") : "todos"}</span> ·{" "}
              <span className="text-muted-foreground">Prioridad:</span> {s.priority}
              {s.updated_by && (
                <span className="text-xs text-muted-foreground">
                  {" "}
                  · cambiada por {s.updated_by}, {formatDate(s.updated_at)}
                </span>
              )}
            </p>
            {editor && (
              <ActionForm action={updateSource} submitLabel="Guardar" className="flex flex-wrap items-end gap-3" testId="source-form">
                <input type="hidden" name="code" value={s.code} />
                <label className="flex items-center gap-2">
                  <input type="checkbox" name="active" defaultChecked={s.active} className="size-4" /> Activa
                </label>
                <label className="space-y-1">
                  <span className="block text-xs text-muted-foreground">Países (vacío = todos)</span>
                  <Input name="countries" defaultValue={s.countries.join(", ")} placeholder="US, CO" className="w-44" aria-label="Países" />
                </label>
                <label className="space-y-1">
                  <span className="block text-xs text-muted-foreground">Prioridad (1–1000)</span>
                  <Input name="priority" type="number" min={1} max={1000} defaultValue={s.priority} className="w-28" aria-label="Prioridad" />
                </label>
              </ActionForm>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
