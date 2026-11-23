import { Suspense } from "react";
import type { Metadata } from "next";

import { KnowledgeFiltersForm } from "@/components/knowledge/knowledge-filters";
import { VariantTable } from "@/components/knowledge/variant-table";
import { Pagination } from "@/components/pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { knowledgeHref, parseKnowledgeFilters } from "@/lib/filters";
import { knowledgeFilterOptions, listVariants } from "@/lib/queries/knowledge";

export const metadata: Metadata = { title: "Base de conocimiento" };

export default function KnowledgePage({ searchParams }: PageProps<"/base">) {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Base de conocimiento</h1>
        <p className="text-sm text-muted-foreground">
          Todas las variantes (marca, modelo, versión, año y motor) con su ficha publicada, estén o no en revisión. Haz
          clic en una fila para ver la ficha completa y de dónde sale cada dato.
        </p>
      </div>
      <Suspense fallback={<KnowledgeSkeleton />}>
        <Knowledge searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

async function Knowledge({ searchParams }: Pick<PageProps<"/base">, "searchParams">) {
  const filters = parseKnowledgeFilters(await searchParams);
  // a model only makes sense together with its make
  if (!filters.make) filters.model = undefined;
  const options = await knowledgeFilterOptions(filters);
  if (filters.model && !options.models.some((m) => m.id === filters.model)) filters.model = undefined;
  const list = await listVariants(filters);
  return (
    <>
      <KnowledgeFiltersForm options={options} filters={filters} />
      <section aria-labelledby="variants-heading" className="space-y-3">
        <h2 id="variants-heading" className="text-sm text-muted-foreground">
          {list.total === 0
            ? "No hay variantes con estos filtros."
            : `${list.total.toLocaleString("es")} ${list.total === 1 ? "variante" : "variantes"} · página ${list.page} de ${list.pageCount}`}
        </h2>
        {list.rows.length > 0 && <VariantTable rows={list.rows} filters={filters} />}
        <Pagination page={list.page} pageCount={list.pageCount} href={(page) => knowledgeHref(filters, { page })} />
      </section>
    </>
  );
}

function KnowledgeSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Cargando la base de conocimiento">
      <Skeleton className="h-14" />
      <Skeleton className="h-96" />
    </div>
  );
}
