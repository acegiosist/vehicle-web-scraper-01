"use client";

import { useActionState } from "react";
import { CircleAlert, Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { enqueueJob, type JobFormState } from "@/lib/actions/jobs";

/** Queues the ai_collect job of one run (the same Server Action as the /tareas forms, which
 *  validates everything again and redirects to the job's page). */
export function CollectButton({ runId }: { runId: string }) {
  const [state, action, pending] = useActionState<JobFormState, FormData>(enqueueJob, {});
  return (
    <form action={action} className="space-y-1">
      <input type="hidden" name="command" value="ai_collect" />
      <input type="hidden" name="run_id" value={runId} />
      <Button type="submit" size="sm" disabled={pending}>
        <Download aria-hidden /> Recoger resultados
      </Button>
      {state.error && (
        <p role="alert" className="flex items-start gap-1 text-xs text-destructive">
          <CircleAlert className="mt-0.5 size-3 shrink-0" aria-hidden /> {state.error}
        </p>
      )}
    </form>
  );
}
