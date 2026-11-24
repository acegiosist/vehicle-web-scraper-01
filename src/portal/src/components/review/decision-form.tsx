"use client";

import { useActionState, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { decideCase, type RequestState } from "@/lib/actions/request";
import { DECISIONS, MAKE_CLASSES, type Decision, type IssueInfo } from "@/lib/issues";

interface Props {
  caseId: string;
  issue: string;
  info: IssueInfo;
  correctedHint: string;
}

/** Aprobar / rechazar / corregir one case. The worker validates and applies it. */
export function DecisionForm({ caseId, issue, info, correctedHint }: Props) {
  const [state, action, pending] = useActionState<RequestState, FormData>(decideCase, { status: "idle" });
  const [decision, setDecision] = useState<Decision | "">("");
  const effects: Record<Decision, string> = { aprobar: info.approve, rechazar: info.reject, corregir: info.correct };
  return (
    <form action={action} className="space-y-4">
      <input type="hidden" name="case_id" value={caseId} />
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Decisión</legend>
        {(Object.keys(DECISIONS) as Decision[]).map((d) => (
          <label key={d} className="flex cursor-pointer items-start gap-2 rounded-md border p-2 text-sm has-checked:border-primary">
            <input
              type="radio"
              name="decision"
              value={d}
              checked={decision === d}
              onChange={() => setDecision(d)}
              className="mt-1"
              required
            />
            <span>
              <span className="font-medium">{DECISIONS[d]}</span>
              <span className="block text-muted-foreground">{effects[d]}</span>
            </span>
          </label>
        ))}
      </fieldset>
      {issue === "unknown_make" && decision === "aprobar" && (
        <div className="space-y-1">
          <Label htmlFor="class">Clase (qué fabrica)</Label>
          <NativeSelect id="class" name="class" required defaultValue="">
            <option value="" disabled>
              Elegir…
            </option>
            {Object.entries(MAKE_CLASSES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}
      {decision === "corregir" && (
        <div className="space-y-1">
          <Label htmlFor="corrected_value">Valor corregido</Label>
          <Input id="corrected_value" name="corrected_value" required maxLength={200} autoComplete="off" />
          <p className="text-xs text-muted-foreground">{correctedHint}</p>
        </div>
      )}
      <div className="space-y-1">
        <Label htmlFor="note">Nota (opcional)</Label>
        <Textarea id="note" name="note" maxLength={500} rows={2} />
      </div>
      {state.status === "error" && (
        <Alert variant="destructive">
          <AlertDescription>{state.error}</AlertDescription>
        </Alert>
      )}
      {state.status === "queued" && (
        <Alert>
          <AlertDescription data-testid="decision-queued">
            Enviada (acción #{state.actionId}). El worker la valida y la aplica en unos segundos.
          </AlertDescription>
        </Alert>
      )}
      <Button type="submit" disabled={pending || !decision}>
        {pending ? "Enviando…" : "Enviar decisión"}
      </Button>
    </form>
  );
}
