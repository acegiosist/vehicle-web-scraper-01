import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { NoAccess } from "@/components/no-access";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { userWithRole } from "@/lib/auth/current-user";
import { baseQuery, parseBaseFilters } from "@/lib/base-href";
import { formatValue } from "@/lib/fields";
import { formatInt, formatYears as years } from "@/lib/format";
import { getCatalogs, makeWithGenerations } from "@/lib/queries/knowledge";

export const metadata: Metadata = { title: "Marca" };

export default function MakePage(props: PageProps<"/base/marca/[id]">) {
  return (
    <main className="space-y-6">
      <Suspense fallback={<Skeleton className="h-5 w-36" />}>
        <BackLink searchParams={props.searchParams} />
      </Suspense>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <MakeView {...props} />
      </Suspense>
    </main>
  );
}

/** Back to the make list with the search, page and size the user came from. */
async function BackLink({ searchParams }: Pick<PageProps<"/base/marca/[id]">, "searchParams">) {
  const href = `/base${baseQuery(parseBaseFilters(await searchParams))}`;
  return (
    <Link href={href} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
      <ArrowLeft className="size-4" aria-hidden /> Todas las marcas
    </Link>
  );
}

async function MakeView({ params }: PageProps<"/base/marca/[id]">) {
  if (!(await userWithRole("lector"))) return <NoAccess needed="lector" />;
  const { id } = await params;
  const [found, catalogs] = await Promise.all([makeWithGenerations(id), getCatalogs()]);
  if (!found) notFound();
  const models = new Map<string, typeof found.generations>();
  for (const row of found.generations) {
    const key = String(row.model_id);
    models.set(key, [...(models.get(key) ?? []), row]);
  }
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">{found.make.name}</h1>
      <div className="grid gap-4 md:grid-cols-2">
        {[...models.values()].map((rows) => {
          const m = rows[0];
          const gens = rows.filter((r) => r.generation_id && (r.generation_listings ?? 0) > 0);
          return (
            <Card key={String(m.model_id)} size="sm">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  {m.model_name}
                  {m.model_status !== "accepted" && <Badge variant="outline">pendiente</Badge>}
                  <span className="ml-auto text-xs font-normal text-muted-foreground">{formatInt(m.model_listings)} anuncios</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {gens.length ? (
                  <ul className="space-y-1 text-sm">
                    {gens.map((g) => (
                      <li key={String(g.generation_id)} className="flex flex-wrap items-center gap-2">
                        <Link href={`/base/generacion/${g.generation_id}`} className="underline-offset-2 hover:underline">
                          {g.generation_name}
                        </Link>
                        <span className="text-muted-foreground">
                          {years(g.year_from, g.year_to, g.observed_year_from, g.observed_year_to)}
                        </span>
                        {g.segment_code && <Badge variant="outline">{formatValue("segment_code", g.segment_code, catalogs)}</Badge>}
                        {g.generation_status === "provisional" && <Badge variant="outline">provisional</Badge>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">Sin generaciones con anuncios (modelo pendiente o sin carrocería).</p>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
