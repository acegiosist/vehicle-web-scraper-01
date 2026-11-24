import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";

import { NoAccess } from "@/components/no-access";
import { PageSizeSelect } from "@/components/page-size-select";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { userWithRole } from "@/lib/auth/current-user";
import { formatInt } from "@/lib/format";
import { baseQuery, parseBaseFilters } from "@/lib/base-href";
import { DEFAULT_PAGE_SIZE, PAGE_SIZES } from "@/lib/paging";
import { makes } from "@/lib/queries/knowledge";

export const metadata: Metadata = { title: "Base" };

export default function BasePage(props: PageProps<"/base">) {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Base de conocimiento</h1>
        <p className="text-sm text-muted-foreground">Marca → modelo → generación → tren motriz → variante por país.</p>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Makes {...props} />
      </Suspense>
    </main>
  );
}

async function Makes({ searchParams }: PageProps<"/base">) {
  if (!(await userWithRole("lector"))) return <NoAccess needed="lector" />;
  const sp = await searchParams;
  const { q, page: requested, size } = parseBaseFilters(sp);
  const all = await makes(q);
  const pageCount = Math.max(1, Math.ceil(all.length / size));
  const page = Math.min(requested, pageCount);
  const rows = all.slice((page - 1) * size, page * size);
  const href = (p: number, s = size) => `/base${baseQuery({ q, page: p, size: s })}`;
  const current = baseQuery({ q, page, size });
  return (
    <div className="space-y-4">
      <form className="flex gap-2" action="/base">
        {size !== DEFAULT_PAGE_SIZE && <input type="hidden" name="por" value={size} />}
        <Input name="q" defaultValue={q ?? ""} placeholder="Buscar marca…" className="w-72" />
        <Button type="submit" variant="outline">
          Buscar
        </Button>
      </form>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Marca</TableHead>
            <TableHead className="text-right">Modelos</TableHead>
            <TableHead className="text-right">Generaciones</TableHead>
            <TableHead className="text-right">Anuncios</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((m) => (
            <TableRow key={String(m.id)}>
              <TableCell>
                <Link href={`/base/marca/${m.id}${current}`} className="font-medium underline-offset-2 hover:underline">
                  {m.name}
                </Link>
                {m.status !== "accepted" && <span className="ml-2 text-xs text-muted-foreground">(pendiente de revisión)</span>}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatInt(m.models)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatInt(m.generations)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatInt(m.listings)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="flex items-center justify-between gap-4">
        <PageSizeSelect size={size} options={PAGE_SIZES.map((s) => ({ size: s, href: href(1, s) }))} />
        <div className="flex-1">
          <Pagination page={page} pageCount={pageCount} href={(p) => href(p)} />
        </div>
      </div>
    </div>
  );
}
