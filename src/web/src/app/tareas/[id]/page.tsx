import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, CircleAlert, Download } from "lucide-react";

import { AiSubmitForm } from "@/components/jobs/ai-submit-form";
import { JobPoller } from "@/components/jobs/job-poller";
import { duration } from "@/components/jobs/job-table";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cancelJob } from "@/lib/actions/jobs";
import { aiSubmitEnabled } from "@/lib/flags";
import { formatDate, formatInt } from "@/lib/format";
import {
  type AiBudget,
  BUDGET_PERIOD_LABELS,
  budgetVerdict,
  COMMAND_LABELS,
  describeParams,
  ESTIMATE_MAX_AGE_MIN,
  type EstimateResult,
  formatResetsAt,
  JOB_STATUS,
  type JobCommand,
  type JobStatus,
} from "@/lib/jobs";
import { aiSpentSince, getJob } from "@/lib/queries/jobs";

export const metadata: Metadata = { title: "Tarea" };

export default function JobPage(props: PageProps<"/tareas/[id]">) {
  return (
    <main>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <JobView {...props} />
      </Suspense>
    </main>
  );
}

async function JobView({ params }: PageProps<"/tareas/[id]">) {
  const { id } = await params;
  const job = await getJob(id);
  if (!job) notFound();
  const s = JOB_STATUS[job.status as JobStatus] ?? { label: job.status, variant: "outline" as const };
  const active = job.status === "queued" || job.status === "running";
  const estimate =
    job.command === "ai_estimate" && job.status === "done" ? (job.result as EstimateResult | null) : null;
  // spent in the budget's period read now: another batch may have been sent after the estimate
  const spentNow = estimate?.budget ? await aiSpentSince(estimate.budget.period_start) : 0;

  return (
    <div className="space-y-6">
      <JobPoller active={active} />
      <Link
        href="/tareas"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden /> Volver a tareas
      </Link>
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={s.variant}>{s.label}</Badge>
          <span className="text-sm text-muted-foreground">tarea #{job.id}</span>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {COMMAND_LABELS[job.command as JobCommand] ?? job.command}
        </h1>
        <p className="text-sm text-muted-foreground">
          {describeParams(job.command, job.params) && `${describeParams(job.command, job.params)} · `}
          pedida por {job.requested_by} · {formatDate(job.created_at)} · duración {duration(job)}
        </p>
      </header>

      {job.status === "queued" && (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm">Esperando al worker. Si no avanza, revisa que esté corriendo `kb worker`.</p>
          <form action={cancelJob}>
            <input type="hidden" name="jobId" value={job.id} />
            <Button type="submit" variant="outline" size="sm">
              Cancelar
            </Button>
          </form>
        </div>
      )}
      {job.status === "running" && <p className="text-sm">Corriendo… esta página se actualiza sola.</p>}

      {job.error && (
        <Alert variant="destructive">
          <CircleAlert aria-hidden />
          <AlertTitle>No se completó</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap">{job.error}</AlertDescription>
        </Alert>
      )}

      {job.filename && (
        <Button asChild>
          <a href={`/tareas/${job.id}/descargar`} download>
            <Download aria-hidden /> Descargar {job.filename} ({formatInt(job.size)} bytes)
          </a>
        </Button>
      )}

      {estimate && <EstimateCard jobId={job.id} estimate={estimate} fresh={!!job.fresh} spentNow={spentNow} />}

      {job.summary && (
        <Card>
          <CardHeader>
            <CardTitle>Resultado</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="overflow-x-auto rounded-lg bg-muted p-3 text-xs whitespace-pre-wrap">{job.summary}</pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function EstimateCard({
  jobId,
  estimate,
  fresh,
  spentNow,
}: {
  jobId: string;
  estimate: EstimateResult;
  fresh: boolean;
  spentNow: number;
}) {
  const e = estimate.estimate;
  const verdict = e ? budgetVerdict(estimate.budget, spentNow, e.cost_usd_est) : null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Estimado</CardTitle>
        <CardDescription>
          {estimate.params.kind === "identity" ? "Identidad" : "Fichas técnicas"} · modelo {estimate.model ?? "—"} ·
          esfuerzo {estimate.params.effort}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!e ? (
          <p className="text-sm">No hay nada que enviar ({estimate.skipped} requests ya respondidos).</p>
        ) : (
          <>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
              <Stat label="Requests" value={formatInt(e.requests)} />
              <Stat label="Ya respondidos (no se reenvían)" value={formatInt(estimate.skipped)} />
              <Stat label="Tokens de entrada" value={`${formatInt(e.input_tokens)} (${e.method})`} />
              <Stat label="Tokens de salida (aprox.)" value={formatInt(e.output_tokens_est)} />
              <Stat label="Costo estimado" value={`US$ ${e.cost_usd_est.toFixed(2)}`} />
              <Stat label="Rango" value={`US$ ${e.cost_usd_range[0]} – ${e.cost_usd_range[1]}`} />
            </dl>
            <BudgetSummary budget={estimate.budget} spentNow={spentNow} />
            {!aiSubmitEnabled() ? (
              <p className="text-xs text-muted-foreground">
                Enviar desde el sitio está deshabilitado (KB_WEB_AI_SUBMIT). Para enviarlo usa el CLI:
                <code className="ml-1">kb ai-{estimate.params.kind} --submit --confirm</code>.
              </p>
            ) : fresh ? (
              <AiSubmitForm estimateJobId={jobId} costUsd={e.cost_usd_est} blockedReason={verdict?.message ?? null} />
            ) : (
              <p className="text-xs text-muted-foreground">
                Este estimado tiene más de {ESTIMATE_MAX_AGE_MIN} minutos: estima de nuevo para poder enviarlo.
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}

/** The AI spending limit (KB_AI_BUDGET_USD per KB_AI_BUDGET_PERIOD in the worker's .env). */
function BudgetSummary({ budget, spentNow }: { budget: AiBudget | undefined; spentNow: number }) {
  if (!budget || budget.limit_usd === null) return null;
  const remaining = Math.max(0, budget.limit_usd - spentNow);
  const pct = budget.limit_usd > 0 ? Math.min(100, (100 * spentNow) / budget.limit_usd) : 100;
  return (
    <section aria-label="Presupuesto de IA" className="space-y-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-medium">Presupuesto de IA</h3>
        <span className="text-xs text-muted-foreground">
          {BUDGET_PERIOD_LABELS[budget.period] ?? budget.period} · se reinicia el {formatResetsAt(budget.resets_at)}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
        <div className="h-full bg-primary" style={{ width: `${pct}%` }} />
      </div>
      <p className="tabular-nums">
        Gastado US$ {spentNow.toFixed(2)} de US$ {budget.limit_usd.toFixed(2)} · quedan US$ {remaining.toFixed(2)}
      </p>
    </section>
  );
}
