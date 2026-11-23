import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { countsText, parseCounts, runKindLabel, runStatusLabel } from "@/lib/ai-runs";
import { formatDate } from "@/lib/format";
import type { AiRunRow } from "@/lib/queries/jobs";

const usd = (v: number | null) => (v === null ? "—" : `US$ ${Number(v).toFixed(2)}`);

/** The latest AI runs and where each one is: processing, ready to collect, collected. */
export function RunTable({ runs }: { runs: AiRunRow[] }) {
  if (runs.length === 0) return <p className="text-sm text-muted-foreground">Todavía no se ha enviado ningún lote.</p>;
  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Lote</TableHead>
            <TableHead>Enviado</TableHead>
            <TableHead className="hidden md:table-cell">Terminó</TableHead>
            <TableHead>Resultado</TableHead>
            <TableHead className="hidden text-right md:table-cell">Costo</TableHead>
            <TableHead>Estado</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((r) => (
            <TableRow key={r.id}>
              <TableCell>
                #{r.id} · {runKindLabel(r.kind)}
              </TableCell>
              <TableCell className="text-muted-foreground">{formatDate(r.submitted_at)}</TableCell>
              <TableCell className="hidden text-muted-foreground md:table-cell">{formatDate(r.ended_at)}</TableCell>
              <TableCell className="whitespace-normal">
                {countsText(parseCounts(r.batch_counts), r.request_count)}
              </TableCell>
              <TableCell className="hidden text-right tabular-nums md:table-cell">
                {r.actual_cost_usd !== null ? usd(r.actual_cost_usd) : `≈ ${usd(r.est_cost_usd)}`}
              </TableCell>
              <TableCell>
                {r.status === "ended" ? (
                  <Badge>{runStatusLabel(r.status)}</Badge>
                ) : r.status === "submitted" ? (
                  <Badge variant="secondary">{runStatusLabel(r.status)}</Badge>
                ) : (
                  <span className="text-xs text-muted-foreground">{runStatusLabel(r.status)}</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
