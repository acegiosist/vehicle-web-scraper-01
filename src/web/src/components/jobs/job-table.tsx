import Link from "next/link";
import { Download } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cancelJob } from "@/lib/actions/jobs";
import { formatDate } from "@/lib/format";
import { COMMAND_LABELS, describeParams, JOB_STATUS, type JobCommand, type JobStatus } from "@/lib/jobs";
import type { JobRow } from "@/lib/queries/jobs";

export function duration(job: Pick<JobRow, "started_at" | "finished_at">): string {
  if (!job.started_at) return "—";
  const end = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
  const s = Math.max(0, Math.round((end - new Date(job.started_at).getTime()) / 1000));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

export function JobTable({ jobs }: { jobs: JobRow[] }) {
  if (jobs.length === 0)
    return <p className="text-sm text-muted-foreground">Todavía no se ha lanzado ninguna tarea.</p>;
  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Tarea</TableHead>
            <TableHead>Pedida</TableHead>
            <TableHead className="hidden md:table-cell">Duración</TableHead>
            <TableHead>Estado</TableHead>
            <TableHead className="w-28" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.map((j) => {
            const s = JOB_STATUS[j.status as JobStatus] ?? { label: j.status, variant: "outline" as const };
            return (
              <TableRow key={j.id}>
                <TableCell className="max-w-[28rem] whitespace-normal">
                  <Link href={`/tareas/${j.id}`} className="font-medium hover:underline">
                    {COMMAND_LABELS[j.command as JobCommand] ?? j.command}
                  </Link>
                  <div className="text-xs text-muted-foreground">
                    #{j.id} {describeParams(j.command, j.params) && `· ${describeParams(j.command, j.params)}`}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {j.requested_by}
                  <div className="text-xs">{formatDate(j.created_at)}</div>
                </TableCell>
                <TableCell className="hidden tabular-nums md:table-cell">{duration(j)}</TableCell>
                <TableCell>
                  <Badge variant={s.variant}>{s.label}</Badge>
                </TableCell>
                <TableCell className="text-right">
                  {j.status === "queued" && (
                    <form action={cancelJob}>
                      <input type="hidden" name="jobId" value={j.id} />
                      <Button type="submit" variant="ghost" size="sm">
                        Cancelar
                      </Button>
                    </form>
                  )}
                  {j.filename && (
                    <Button asChild variant="outline" size="sm">
                      <a href={`/tareas/${j.id}/descargar`} download>
                        <Download aria-hidden /> Descargar
                      </a>
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
