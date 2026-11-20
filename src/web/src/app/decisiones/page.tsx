import { Suspense } from "react";
import type { Metadata } from "next";
import Form from "next/form";
import Link from "next/link";

import { Pagination } from "@/components/pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fieldLabel, formatValue } from "@/lib/fields";
import { type DecisionFilters, parseDecisionFilters } from "@/lib/filters";
import { formatDate } from "@/lib/format";
import { DECISION_LABELS, type Decision, issueInfo } from "@/lib/issues";
import { listDecisions } from "@/lib/queries/decisions";

export const metadata: Metadata = { title: "Decisiones" };

const STATUS: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  queued: { label: "En cola", variant: "secondary" },
  applied: { label: "Aplicada", variant: "default" },
  failed: { label: "Falló", variant: "destructive" },
  superseded: { label: "Ya decidido", variant: "outline" },
};

export default function DecisionsPage({ searchParams }: PageProps<"/decisiones">) {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Decisiones</h1>
        <p className="text-sm text-muted-foreground">
          Todo lo que se decidió desde este sitio, con quién lo decidió y si el worker lo aplicó.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Decisions searchParams={searchParams} />
      </Suspense>
    </main>
  );
}

function href(filters: DecisionFilters, page: number) {
  const qs = new URLSearchParams();
  if (filters.reviewer) qs.set("reviewer", filters.reviewer);
  if (filters.status) qs.set("status", filters.status);
  if (page > 1) qs.set("page", String(page));
  const s = qs.toString();
  return s ? `/decisiones?${s}` : "/decisiones";
}

async function Decisions({ searchParams }: Pick<PageProps<"/decisiones">, "searchParams">) {
  const filters = parseDecisionFilters(await searchParams);
  const list = await listDecisions(filters);
  return (
    <>
      <Form
        action="/decisiones"
        key={JSON.stringify(filters)}
        className="flex flex-wrap items-end gap-3 rounded-xl border p-3"
      >
        <div className="space-y-1">
          <label htmlFor="d-reviewer" className="block text-xs text-muted-foreground">
            Revisor
          </label>
          <NativeSelect id="d-reviewer" name="reviewer" defaultValue={filters.reviewer ?? ""} className="w-48">
            <option value="">Todos</option>
            {list.reviewers.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1">
          <label htmlFor="d-status" className="block text-xs text-muted-foreground">
            Estado
          </label>
          <NativeSelect id="d-status" name="status" defaultValue={filters.status ?? ""} className="w-40">
            <option value="">Todos</option>
            {Object.entries(STATUS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </NativeSelect>
        </div>
        <Button type="submit">Filtrar</Button>
        <Button asChild variant="ghost">
          <Link href="/decisiones">Limpiar</Link>
        </Button>
      </Form>

      {list.rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Todavía no hay decisiones con estos filtros.</p>
      ) : (
        <div className="rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Cuándo</TableHead>
                <TableHead>Revisor</TableHead>
                <TableHead>Caso</TableHead>
                <TableHead>Decisión</TableHead>
                <TableHead>Estado</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.rows.map((d) => {
                const s = STATUS[d.status] ?? { label: d.status, variant: "outline" as const };
                return (
                  <TableRow key={d.id}>
                    <TableCell className="tabular-nums text-muted-foreground">{formatDate(d.submitted_at)}</TableCell>
                    <TableCell>{d.reviewer}</TableCell>
                    <TableCell className="max-w-[26rem] whitespace-normal">
                      <Link href={`/cola/${d.review_item_id}`} className="font-medium hover:underline">
                        {d.entity_label ?? `Caso #${d.review_item_id}`}
                      </Link>
                      <div className="block text-xs text-muted-foreground">
                        {issueInfo(d.issue).title}
                        {d.field ? ` · ${fieldLabel(d.field)}` : ""}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-normal">
                      {DECISION_LABELS[d.decision as Decision] ?? d.decision}
                      {d.corrected_value && (
                        <span className="text-muted-foreground"> → {formatValue(d.field, d.corrected_value)}</span>
                      )}
                      {d.note && <div className="block text-xs text-muted-foreground">{d.note}</div>}
                    </TableCell>
                    <TableCell className="whitespace-normal">
                      <Badge variant={s.variant}>{s.label}</Badge>
                      {d.error && <div className="mt-1 text-xs text-destructive">{d.error}</div>}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
      <Pagination page={list.page} pageCount={list.pageCount} href={(p) => href(filters, p)} />
    </>
  );
}
