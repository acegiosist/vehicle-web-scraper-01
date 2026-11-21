import { Suspense } from "react";
import type { Metadata } from "next";

import { LevelSummary } from "@/components/queue/level-summary";
import { QueueFiltersForm } from "@/components/queue/queue-filters";
import { QueueTable } from "@/components/queue/queue-table";
import { Pagination } from "@/components/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { parseQueueFilters, queueHref } from "@/lib/filters";
import { filterOptions, levelCounts, listQueue } from "@/lib/queries/queue";

export const metadata: Metadata = { title: "Cola" };

export default function QueuePage({ searchParams }: PageProps<"/cola">) {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Cola de revisión</h1>
        <p className="text-sm text-muted-foreground">
          Casos que las reglas y la IA no pudieron cerrar. Resuelve de arriba hacia abajo: un modelo no avanza hasta que
          su marca está aceptada.
        </p>
      </div>
      <Suspense fallback={<QueueSkeleton />}>
        <Queue searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function Queue({ searchParams }: Pick<PageProps<"/cola">, "searchParams">) {
  const filters = parseQueueFilters(await searchParams);
  const [list, counts, options] = await Promise.all([listQueue(filters), levelCounts(), filterOptions()]);
  return (
    <>
      <LevelSummary counts={counts} filters={filters} />
      <QueueFiltersForm options={options} filters={filters} />
      <section aria-labelledby="queue-heading" className="space-y-3">
        <h2 id="queue-heading" className="text-sm text-muted-foreground">
          {list.total === 0
            ? "No hay casos con estos filtros."
            : `${list.total.toLocaleString("es")} ${list.total === 1 ? "caso" : "casos"} · página ${list.page} de ${list.pageCount}`}
        </h2>
        {list.rows.length > 0 && <QueueTable rows={list.rows} filters={filters} />}
        <Pagination page={list.page} pageCount={list.pageCount} href={(page) => queueHref(filters, { page })} />
      </section>
    </>
  );
}

function QueueSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Cargando la cola">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
      <Skeleton className="h-10" />
      <Skeleton className="h-96" />
    </div>
  );
}
