import { BellRing, Hourglass } from "lucide-react";

import { CollectButton } from "@/components/ai-runs/collect-button";
import { RunPoller } from "@/components/ai-runs/run-poller";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { BATCH_CHECK_MIN, countsText, parseCounts, runKindLabel, sinceText } from "@/lib/ai-runs";
import { pendingRuns } from "@/lib/queries/jobs";

/** Shown on every page while an AI batch is not collected: a finished one (the worker saw it end)
 *  with its "Recoger resultados" button, and the ones still processing at Anthropic. */
export async function AiRunNotice() {
  const runs = await pendingRuns();
  if (runs.length === 0) return null;
  const now = new Date(runs[0].db_now).getTime(); // the database's clock, same as the run dates
  const ended = runs.filter((r) => r.status === "ended");
  const processing = runs.filter((r) => r.status === "submitted");
  return (
    <section aria-label="Avisos de IA" className="mb-6 space-y-2">
      {ended.map((r) => (
        <Alert key={r.id} role="status" className="border-primary/40 bg-primary/5">
          <BellRing aria-hidden />
          <AlertTitle>El lote de IA #{r.id} terminó</AlertTitle>
          <AlertDescription className="space-y-2">
            <p>
              {runKindLabel(r.kind)} · {countsText(parseCounts(r.batch_counts), r.request_count)} · terminó{" "}
              {sinceText(r.ended_at, now)}. Recoge los resultados para convertirlos en casos de revisión: nada de la IA
              se acepta sin revisión.
            </p>
            <CollectButton runId={r.id} />
          </AlertDescription>
        </Alert>
      ))}
      {processing.map((r) => (
        <p key={r.id} role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Hourglass className="size-4 shrink-0" aria-hidden />
          <span>
            Lote de IA #{r.id} ({runKindLabel(r.kind)}, {r.request_count}{" "}
            {r.request_count === 1 ? "solicitud" : "solicitudes"}) en proceso en Claude · enviado{" "}
            {sinceText(r.submitted_at, now)} · se revisa cada {BATCH_CHECK_MIN} min
            {r.batch_checked_at ? ` (última revisión ${sinceText(r.batch_checked_at, now)})` : ""}
          </span>
        </p>
      ))}
      <RunPoller active={processing.length > 0} />
    </section>
  );
}
