"use client";

import { useActionState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { importSpecs, type RequestState } from "@/lib/actions/request";

/** Upload a filled capture template; kb worker validates and saves it. */
export function UploadForm() {
  const [state, formAction, pending] = useActionState<RequestState, FormData>(importSpecs, { status: "idle" });
  return (
    <form action={formAction} className="space-y-2" data-testid="upload-form">
      <Label htmlFor="specs-file">Plantilla llena (.xlsx)</Label>
      <Input id="specs-file" name="file" type="file" accept=".xlsx" required className="max-w-md" />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={pending}>
          {pending ? "Enviando…" : "Subir"}
        </Button>
        {state.status === "queued" && (
          <span className="text-xs text-muted-foreground">Enviada (#{state.actionId}). El resultado aparece abajo.</span>
        )}
        {state.status === "error" && <span className="text-xs text-destructive">{state.error}</span>}
      </div>
    </form>
  );
}
