import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";

import { NoAccess } from "@/components/no-access";
import { PageSizeSelect } from "@/components/page-size-select";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { userWithRole } from "@/lib/auth/current-user";
import { fieldLabel, formatValue } from "@/lib/fields";
import { formatInt } from "@/lib/format";
import { ENTITY_LABELS, ISSUE_ORDER, ISSUES, type Issue } from "@/lib/issues";
import { getCatalogs } from "@/lib/queries/knowledge";
import {
  parseQueueFilters,
  caseHref,
  pendingByIssue,
  QUEUE_PAGE_SIZE,
  QUEUE_PAGE_SIZES,
  queueHref,
  reviewQueue,
  type QueueFilters,
} from "@/lib/queries/review";

export const metadata: Metadata = { title: "Revisión" };

export default function ReviewPage(props: PageProps<"/revision">) {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Revisión</h1>
        <p className="text-sm text-muted-foreground">
          Casos que las reglas no pudieron resolver. Primero los que más anuncios destraban.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Queue {...props} />
      </Suspense>
    </main>
  );
}

async function Queue({ searchParams }: PageProps<"/revision">) {
  if (!(await userWithRole("lector"))) return <NoAccess needed="lector" />;
  const filters = parseQueueFilters(await searchParams);
  const [summary, { rows, total }, catalogs] = await Promise.all([pendingByIssue(), reviewQueue(filters), getCatalogs()]);
  const pageCount = Math.max(1, Math.ceil(total / filters.size));
  return (
    <div className="space-y-4">
      <nav aria-label="Tipos de caso" className="flex flex-wrap gap-2 text-sm">
        <IssueChip filters={filters} issue={undefined} label="Todos" count={Object.values(summary).reduce((a, s) => a + s.cases, 0)} />
        {ISSUE_ORDER.filter((i) => summary[i]).map((i) => (
          <IssueChip key={i} filters={filters} issue={i} label={ISSUES[i].label} count={summary[i].cases} />
        ))}
      </nav>
      <form className="flex flex-wrap items-end gap-2" action="/revision">
        {filters.size !== QUEUE_PAGE_SIZE && <input type="hidden" name="por" value={filters.size} />}
        <NativeSelect name="tipo" defaultValue={filters.issue ?? ""} className="w-56" aria-label="Tipo">
          <option value="">Todos los tipos</option>
          {ISSUE_ORDER.map((i) => (
            <option key={i} value={i}>
              {ISSUES[i].label}
            </option>
          ))}
        </NativeSelect>
        <Input name="q" defaultValue={filters.q ?? ""} placeholder="Buscar marca, modelo, anuncio…" className="w-72" />
        <Button type="submit" variant="outline">
          Filtrar
        </Button>
      </form>
      <p className="text-sm text-muted-foreground">{formatInt(total)} casos</p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Tipo</TableHead>
            <TableHead>Entidad</TableHead>
            <TableHead>Campo</TableHead>
            <TableHead>Valor actual</TableHead>
            <TableHead>Propuesto</TableHead>
            <TableHead className="text-right">Anuncios</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={String(r.id)}>
              <TableCell className="whitespace-nowrap">{ISSUES[r.issue as Issue]?.label ?? r.issue}</TableCell>
              <TableCell className="max-w-md">
                <Link href={caseHref(r.id, filters)} className="underline-offset-2 hover:underline">
                  {r.entity_label ?? `${ENTITY_LABELS[r.entity_type ?? ""] ?? r.entity_type}`}
                </Link>
                {r.country_code && <span className="ml-1 text-xs text-muted-foreground">{r.country_code}</span>}
              </TableCell>
              <TableCell>{r.field ? fieldLabel(r.field) : "—"}</TableCell>
              <TableCell>{formatValue(r.field, r.current_value, catalogs)}</TableCell>
              <TableCell>{formatValue(r.field, r.proposed_value, catalogs)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatInt(r.listings_affected)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="flex items-center justify-between gap-4">
        <PageSizeSelect
          size={filters.size}
          options={QUEUE_PAGE_SIZES.map((size) => ({ size, href: queueHref({ ...filters, size, page: 1 }) }))}
        />
        <div className="flex-1">
          <Pagination page={filters.page} pageCount={pageCount} href={(p) => queueHref(filters, p)} />
        </div>
      </div>
    </div>
  );
}

function IssueChip({ filters, issue, label, count }: { filters: QueueFilters; issue?: Issue; label: string; count: number }) {
  const active = filters.issue === issue;
  return (
    <Link
      href={queueHref({ ...filters, issue, page: 1 })}
      aria-current={active ? "page" : undefined}
      className={`rounded-full border px-3 py-1 ${active ? "border-primary bg-muted font-medium" : "text-muted-foreground hover:bg-muted"}`}
    >
      {label} <span className="tabular-nums">{formatInt(count)}</span>
    </Link>
  );
}
