import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";

import { ActionStatusBadge } from "@/components/action-status";
import { NoAccess } from "@/components/no-access";
import { Pagination } from "@/components/pagination";
import { RefreshWhile } from "@/components/refresh-while";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ACTION_LABELS, describePayload } from "@/lib/action-labels";
import { userWithRole } from "@/lib/auth/current-user";
import { formatDate, formatInt } from "@/lib/format";
import { actionsPage, ACTIONS_PAGE_SIZE } from "@/lib/queries/actions";

export const metadata: Metadata = { title: "Acciones" };

const STATUSES = { queued: "En cola", running: "Aplicando", applied: "Aplicadas", failed: "Fallidas" } as const;

export default function ActionsPage(props: PageProps<"/acciones">) {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Acciones</h1>
        <p className="text-sm text-muted-foreground">
          Todo lo pedido desde el portal: quién, cuándo, y si el worker lo aplicó o por qué falló.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Actions {...props} />
      </Suspense>
    </main>
  );
}

async function Actions({ searchParams }: PageProps<"/acciones">) {
  if (!(await userWithRole("lector"))) return <NoAccess needed="lector" />;
  const sp = await searchParams;
  const one = (k: string) => (Array.isArray(sp[k]) ? sp[k][0] : sp[k]);
  const status = one("estado") as keyof typeof STATUSES | undefined;
  const valid = status && status in STATUSES ? status : undefined;
  const page = Math.max(1, Number.parseInt(one("pagina") ?? "1", 10) || 1);
  const { rows, total } = await actionsPage(valid, page);
  const href = (s: string | undefined, p = 1) => {
    const q = new URLSearchParams();
    if (s) q.set("estado", s);
    if (p > 1) q.set("pagina", String(p));
    return q.size ? `/acciones?${q}` : "/acciones";
  };
  return (
    <div className="space-y-4">
      <RefreshWhile active={rows.some((r) => r.status === "queued" || r.status === "running")} />
      <nav className="flex flex-wrap gap-2 text-sm" aria-label="Estado">
        {[undefined, ...Object.keys(STATUSES)].map((s) => (
          <Link
            key={s ?? "all"}
            href={href(s)}
            aria-current={valid === s ? "page" : undefined}
            className={`rounded-full border px-3 py-1 ${valid === s ? "border-primary bg-muted font-medium" : "text-muted-foreground hover:bg-muted"}`}
          >
            {s ? STATUSES[s as keyof typeof STATUSES] : "Todas"}
          </Link>
        ))}
      </nav>
      <p className="text-sm text-muted-foreground">{formatInt(total)} acciones</p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>#</TableHead>
            <TableHead>Estado</TableHead>
            <TableHead>Acción</TableHead>
            <TableHead>Detalle</TableHead>
            <TableHead>Quién</TableHead>
            <TableHead>Pedida</TableHead>
            <TableHead>Aplicada</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((a) => (
            <TableRow key={String(a.id)} data-testid="action-row">
              <TableCell className="tabular-nums">{String(a.id)}</TableCell>
              <TableCell>
                <ActionStatusBadge status={a.status} />
              </TableCell>
              <TableCell>{ACTION_LABELS[a.kind] ?? a.kind}</TableCell>
              <TableCell className="max-w-md">
                {describePayload(a.kind, a.payload)}
                {a.error && <p className="text-xs text-destructive">{a.error}</p>}
              </TableCell>
              <TableCell className="text-xs">{a.requested_by}</TableCell>
              <TableCell className="text-xs">{formatDate(a.requested_at)}</TableCell>
              <TableCell className="text-xs">{formatDate(a.applied_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Pagination page={page} pageCount={Math.max(1, Math.ceil(total / ACTIONS_PAGE_SIZE))} href={(p) => href(valid, p)} />
    </div>
  );
}
