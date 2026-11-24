"use client";

import { useActionState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { RequestState } from "@/lib/actions/request";

type Action = (state: RequestState, form: FormData) => Promise<RequestState>;

/** A form that queues one request for the worker and says what happened. */
export function ActionForm({
  action,
  children,
  submitLabel,
  className,
  variant = "default",
  testId,
}: {
  action: Action;
  children?: ReactNode;
  submitLabel: string;
  className?: string;
  variant?: "default" | "outline" | "destructive" | "secondary";
  testId?: string;
}) {
  const [state, formAction, pending] = useActionState<RequestState, FormData>(action, { status: "idle" });
  return (
    <form action={formAction} className={className ?? "space-y-2"} data-testid={testId}>
      {children}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" variant={variant} disabled={pending}>
          {pending ? "Enviando…" : submitLabel}
        </Button>
        {state.status === "queued" && (
          <span className="text-xs text-muted-foreground" data-testid="action-queued">
            Enviado (#{state.actionId}). Su estado aparece en Cambios recientes y en Acciones.
          </span>
        )}
        {state.status === "error" && <span className="text-xs text-destructive">{state.error}</span>}
      </div>
    </form>
  );
}
