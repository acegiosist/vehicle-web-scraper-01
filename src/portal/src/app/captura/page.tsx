import { Suspense } from "react";
import type { Metadata } from "next";
import { Download } from "lucide-react";

import { ActionStatusBadge } from "@/components/action-status";
import { UploadForm } from "@/components/capture/upload-form";
import { ActionForm } from "@/components/edit/action-form";
import { NoAccess } from "@/components/no-access";
import { RefreshWhile } from "@/components/refresh-while";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { describePayload } from "@/lib/action-labels";
import { exportSpecs } from "@/lib/actions/request";
import { userWithRole } from "@/lib/auth/current-user";
import { formatDate, formatInt } from "@/lib/format";
import { captureActions, type CaptureAction } from "@/lib/queries/actions";

export const metadata: Metadata = { title: "Captura" };

export default function CapturePage() {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Captura</h1>
        <p className="text-sm text-muted-foreground">
          Datos que los anuncios no traen (dimensiones, segmento, torque, velocidades, código de motor, ciclo de la
          generación), capturados de una fuente. Lo que se sube queda como fuente externa: gana a los anuncios y pierde
          ante un valor manual. Se publica al recalcular.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Capture />
      </Suspense>
    </main>
  );
}

const SAVED_LABELS: [string, string][] = [
  ["generation_values", "valores de generación"],
  ["powertrain_values", "valores de tren motriz"],
  ["cycle_opened", "casos de ciclo abiertos"],
  ["cycle_already_decided", "ciclos ya decididos"],
];

async function Capture() {
  if (!(await userWithRole("revisor"))) return <NoAccess needed="revisor" />;
  const actions = await captureActions(20);
  const exports = actions.filter((a) => a.kind === "export_specs").slice(0, 5);
  const uploads = actions.filter((a) => a.kind === "import_specs").slice(0, 5);
  const inFlight = actions.some((a) => a.status === "queued" || a.status === "running");
  return (
    <div className="space-y-6">
      <RefreshWhile active={inFlight} />
      <Card size="sm">
        <CardHeader>
          <CardTitle>1. Preparar la plantilla</CardTitle>
          <CardDescription>
            Generaciones y trenes motrices con anuncios a los que les falta algún dato, primero los de más anuncios, con lo
            que la base tiene hoy. La hoja Instrucciones explica cada columna.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ActionForm action={exportSpecs} submitLabel="Preparar plantilla" className="flex flex-wrap items-end gap-2" testId="export-form">
            <Input name="make" placeholder="Marca (opcional)" aria-label="Marca" className="w-48" />
            <Input name="country" placeholder="País (CO, US…)" aria-label="País" className="w-36" maxLength={2} />
            <Input name="limit" type="number" min={1} max={2000} defaultValue={500} aria-label="Filas por hoja" className="w-28" />
          </ActionForm>
          {exports.length > 0 && (
            <ul className="space-y-1 text-sm" data-testid="templates">
              {exports.map((a) => (
                <li key={String(a.id)} className="flex flex-wrap items-center gap-2">
                  <ActionStatusBadge status={a.status} />
                  <span>{describePayload(a.kind, a.payload)}</span>
                  {a.status === "applied" && (
                    <>
                      <span className="text-muted-foreground">
                        {formatInt(Number(a.result?.generations ?? 0))} generaciones,{" "}
                        {formatInt(Number(a.result?.powertrains ?? 0))} trenes motrices
                      </span>
                      {/* a plain link: the route answers "attachment", so the browser saves it */}
                      <a href={`/captura/plantilla/${a.id}`} className="inline-flex items-center gap-1 underline">
                        <Download className="size-4" aria-hidden /> Descargar
                      </a>
                    </>
                  )}
                  {a.error && <span className="text-destructive">{a.error}</span>}
                  <span className="text-xs text-muted-foreground">
                    {a.requested_by} · {formatDate(a.requested_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      <Card size="sm">
        <CardHeader>
          <CardTitle>2. Subir la plantilla llena</CardTitle>
          <CardDescription>
            Cada fila que cambie algo necesita su fuente. Las celdas vacías o iguales no cambian nada. Los años del ciclo
            abren un caso de revisión en vez de fijarse. Máximo 700 KB.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <UploadForm />
        </CardContent>
      </Card>
      {uploads.length > 0 && (
        <Card size="sm">
          <CardHeader>
            <CardTitle>Subidas recientes</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {uploads.map((a) => (
              <Upload key={String(a.id)} action={a} />
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Upload({ action: a }: { action: CaptureAction }) {
  const saved = (a.result?.saved ?? {}) as Record<string, number>;
  const errors = (a.result?.errors ?? []) as { sheet: string; row: number; id?: number; error: string }[];
  const errorCount = Number(a.result?.error_count ?? errors.length);
  return (
    <div className="space-y-2 text-sm" data-testid="upload">
      <div className="flex flex-wrap items-center gap-2">
        <ActionStatusBadge status={a.status} />
        <span>{describePayload(a.kind, a.payload)}</span>
        <span className="text-xs text-muted-foreground">
          {a.requested_by} · {formatDate(a.requested_at)}
        </span>
      </div>
      {a.error && <p className="text-destructive">{a.error}</p>}
      {a.status === "applied" && (
        <p data-testid="upload-saved">
          {SAVED_LABELS.filter(([k]) => saved[k]).map(([k, label]) => `${formatInt(saved[k])} ${label}`).join(", ") ||
            "Nada nuevo"}
          {errorCount > 0 && `; ${formatInt(errorCount)} filas con error (no se guardaron)`}.
          {saved.generation_values || saved.powertrain_values ? (
            <span className="text-muted-foreground"> Se publican al recalcular.</span>
          ) : null}
        </p>
      )}
      {errors.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Hoja</TableHead>
              <TableHead>Fila</TableHead>
              <TableHead>Id</TableHead>
              <TableHead>Error</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {errors.map((e, i) => (
              <TableRow key={i} data-testid="upload-error">
                <TableCell>{e.sheet}</TableCell>
                <TableCell className="tabular-nums">{e.row}</TableCell>
                <TableCell className="tabular-nums">{e.id ?? "—"}</TableCell>
                <TableCell>{e.error}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
