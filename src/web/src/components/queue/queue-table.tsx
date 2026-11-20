import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fieldLabel } from "@/lib/fields";
import { caseHref, type QueueFilters } from "@/lib/filters";
import { formatInt } from "@/lib/format";
import { ENTITY_LABELS, type EntityType, issueInfo, levelLabel } from "@/lib/issues";
import type { QueueRow } from "@/lib/queries/queue";

export function QueueTable({ rows, filters }: { rows: QueueRow[]; filters: QueueFilters }) {
  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-28">Nivel</TableHead>
            <TableHead>Caso</TableHead>
            <TableHead>Qué se revisa</TableHead>
            <TableHead className="hidden md:table-cell">País</TableHead>
            <TableHead className="text-right">Anuncios</TableHead>
            <TableHead className="w-32">Estado</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.id} className="relative">
              <TableCell className="text-muted-foreground">{levelLabel(r.level)}</TableCell>
              <TableCell className="max-w-[28rem] whitespace-normal">
                <Link
                  href={caseHref(r.id ?? "", filters)}
                  className="font-medium after:absolute after:inset-0 hover:underline focus-visible:outline-none"
                >
                  {r.entity_label ?? "?"}
                </Link>
                <div className="text-xs text-muted-foreground">
                  {ENTITY_LABELS[r.entity_type as EntityType] ?? r.entity_type} #{r.id}
                </div>
              </TableCell>
              <TableCell className="whitespace-normal">
                {issueInfo(r.issue).title}
                {r.field && <span className="text-muted-foreground"> · {fieldLabel(r.field)}</span>}
              </TableCell>
              <TableCell className="hidden md:table-cell">{r.country || "—"}</TableCell>
              <TableCell className="text-right tabular-nums">{formatInt(r.listings_affected)}</TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {r.queued_decision_id ? <Badge variant="secondary">En cola</Badge> : null}
                  {r.kind === "sample" ? <Badge variant="outline">Muestra</Badge> : null}
                  {!r.queued_decision_id && r.kind !== "sample" ? (
                    <span className="text-xs text-muted-foreground">Pendiente</span>
                  ) : null}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
