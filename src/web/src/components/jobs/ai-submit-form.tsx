"use client";

import { useActionState, useId, useState } from "react";
import { CircleAlert, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { submitAiJob, type JobFormState } from "@/lib/actions/jobs";
import { confirmsAmount } from "@/lib/jobs";

/** Second control before spending money: the reviewer types the estimated amount. With
 *  `blockedReason` (e.g. over the AI spending limit) the button stays disabled and says why. */
export function AiSubmitForm({
  estimateJobId,
  costUsd,
  blockedReason = null,
}: {
  estimateJobId: string;
  costUsd: number;
  blockedReason?: string | null;
}) {
  const [state, action, pending] = useActionState<JobFormState, FormData>(submitAiJob, {});
  const [typed, setTyped] = useState("");
  const id = useId();
  const ok = confirmsAmount(typed, costUsd) && !blockedReason;
  return (
    <form action={action} className="space-y-3">
      <input type="hidden" name="estimateJobId" value={estimateJobId} />
      <label htmlFor={id} className="block text-sm">
        Para enviar, escribe el costo estimado: <strong className="tabular-nums">{costUsd.toFixed(2)}</strong>
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">US$</span>
        <Input
          id={id}
          name="confirm"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          inputMode="decimal"
          autoComplete="off"
          className="w-32"
          disabled={!!blockedReason}
          aria-describedby={`${id}-help`}
        />
        <Button type="submit" variant="destructive" disabled={!ok || pending}>
          <Send aria-hidden /> {pending ? "Enviando…" : "Enviar a Claude"}
        </Button>
      </div>
      {blockedReason && (
        <p role="alert" className="flex items-start gap-2 text-sm font-medium text-destructive">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {blockedReason}
        </p>
      )}
      <p id={`${id}-help`} className="text-xs text-muted-foreground">
        Gasta dinero. El worker vuelve a comprobar que los requests sean los mismos del estimado, que el costo no supere
        este monto ni el límite de gasto en IA, y no envía nada si el envío no está habilitado en su entorno.
      </p>
      {state.error && (
        <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {state.error}
        </p>
      )}
    </form>
  );
}
