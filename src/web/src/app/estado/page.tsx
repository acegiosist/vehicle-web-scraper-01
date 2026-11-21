import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fieldLabel } from "@/lib/fields";
import { formatInt } from "@/lib/format";
import { issueInfo, levelLabel } from "@/lib/issues";
import { aiRuns, coverage, identityCounts, reviewSummary, totals } from "@/lib/queries/status";

export const metadata: Metadata = { title: "Estado" };

export default function StatusPage() {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Estado de la base</h1>
        <p className="text-sm text-muted-foreground">
          Lo mismo que <code>vehicle-scraper kb status</code>, en vivo. Para recalcular o exportar, ve a{" "}
          <Link href="/tareas" className="underline">
            Tareas
          </Link>
          .
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-28" />}>
        <Totals />
      </Suspense>
      <div className="grid gap-4 lg:grid-cols-2">
        <Suspense fallback={<Skeleton className="h-64" />}>
          <Identity />
        </Suspense>
        <Suspense fallback={<Skeleton className="h-64" />}>
          <AiRuns />
        </Suspense>
      </div>
      <Suspense fallback={<Skeleton className="h-64" />}>
        <Review />
      </Suspense>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Coverage />
      </Suspense>
    </main>
  );
}

async function Totals() {
  const t = await totals();
  const items = [
    ["Anuncios", t.listings],
    ["Con variante", t.matched],
    ["Variantes", t.variants],
    ["Fichas mecánicas", t.mech],
    ["Fichas de equipamiento", t.equip],
    ["Casos pendientes", t.pending],
  ] as const;
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {items.map(([label, n]) => (
        <div key={label} className="rounded-xl border p-3">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="mt-1 text-2xl font-semibold tabular-nums">{formatInt(n)}</dd>
        </div>
      ))}
    </dl>
  );
}

const STATUS_LABELS: Record<string, string> = {
  accepted: "aceptadas",
  unresolved: "sin resolver",
  pending_review: "en revisión",
  rejected: "rechazadas",
};

async function Identity() {
  const c = await identityCounts();
  const rows = [
    ["Marcas", c.make],
    ["Modelos", c.model],
    ["Versiones", c.trim],
  ] as const;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Identidad</CardTitle>
        <CardDescription>Marcas, modelos y versiones por estado</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 text-sm">
          {rows.map(([label, counts]) => (
            <li key={label} className="flex flex-wrap gap-x-3">
              <span className="w-20 font-medium">{label}</span>
              {Object.entries(counts).map(([status, n]) => (
                <span key={status} className="text-muted-foreground">
                  <span className="text-foreground tabular-nums">{formatInt(n)}</span> {STATUS_LABELS[status] ?? status}
                </span>
              ))}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

async function AiRuns() {
  const runs = await aiRuns();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Corridas de IA</CardTitle>
        <CardDescription>
          Batches de Claude por tipo y estado, con el costo estimado y el real (al recogerlos)
        </CardDescription>
      </CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">Todavía no se ha enviado nada a Claude.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {runs.map((r) => (
              <li key={`${r.kind}-${r.status}`}>
                {r.kind === "identity" ? "Identidad" : "Fichas"} · {r.status}: {r.runs} corridas,{" "}
                {formatInt(r.requests)} requests, estimado US$ {r.usd.toFixed(2)}
                {r.actualUsd !== null && <>, real US$ {r.actualUsd.toFixed(4)}</>}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

async function Review() {
  const rows = await reviewSummary();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Casos de revisión pendientes</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No hay casos pendientes.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nivel</TableHead>
                <TableHead>Tipo de caso</TableHead>
                <TableHead>Revisión</TableHead>
                <TableHead className="text-right">Casos</TableHead>
                <TableHead className="text-right">Anuncios</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={`${r.level}-${r.kind}-${r.issue}`}>
                  <TableCell className="text-muted-foreground">{levelLabel(r.level)}</TableCell>
                  <TableCell>
                    <Link href={`/cola?issue=${r.issue}`} className="hover:underline">
                      {issueInfo(r.issue).title}
                    </Link>
                  </TableCell>
                  <TableCell>{r.kind === "sample" ? "Muestra" : "Individual"}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatInt(r.n)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatInt(r.listings)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

async function Coverage() {
  const c = await coverage();
  const groups = [
    ["mech", "Ficha mecánica"],
    ["equip", "Equipamiento"],
  ] as const;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Cobertura</CardTitle>
        <CardDescription>
          % de los {formatInt(c.total)} anuncios con variante que tienen cada dato, ya completado con la base de
          conocimiento
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 md:grid-cols-2">
        {groups.map(([group, title]) => (
          <section key={group} aria-label={title}>
            <h3 className="mb-2 text-sm font-medium">{title}</h3>
            <ul className="space-y-1.5 text-sm">
              {c.fields
                .filter((f) => f.group === group)
                .map((f) => (
                  <li key={f.name} className="grid grid-cols-[10rem_1fr_3.5rem] items-center gap-2">
                    <span className="truncate">{fieldLabel(f.name)}</span>
                    <span className="h-2 rounded-full bg-muted" aria-hidden>
                      <span className="block h-2 rounded-full bg-foreground/70" style={{ width: `${f.pct}%` }} />
                    </span>
                    <span className="text-right tabular-nums text-muted-foreground">{f.pct.toFixed(0)} %</span>
                  </li>
                ))}
            </ul>
          </section>
        ))}
      </CardContent>
    </Card>
  );
}
