"use client";

import { useActionState, useState } from "react";
import { UserRound } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { setReviewer } from "@/lib/actions/reviewer";

export function ReviewerForm({ current }: { current: string | null }) {
  const [editing, setEditing] = useState(!current);
  const [state, action, pending] = useActionState(async (prev: { error?: string }, data: FormData) => {
    const result = await setReviewer(prev, data);
    if (!result.error) setEditing(false);
    return result;
  }, {});

  if (current && !editing) {
    return (
      <div className="flex items-center gap-2 text-sm">
        <UserRound className="size-4 text-muted-foreground" aria-hidden />
        <span>
          Revisando como <strong>{current}</strong>
        </span>
        <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
          Cambiar
        </Button>
      </div>
    );
  }

  return (
    <form action={action} className="flex flex-wrap items-center gap-2 text-sm">
      <label htmlFor="reviewer" className="text-muted-foreground">
        Tu nombre
      </label>
      <Input
        id="reviewer"
        name="reviewer"
        defaultValue={current ?? ""}
        required
        minLength={2}
        maxLength={60}
        autoComplete="name"
        className="w-44"
        aria-invalid={!!state.error}
        aria-describedby={state.error ? "reviewer-error" : undefined}
      />
      <Button type="submit" size="sm" disabled={pending}>
        Guardar
      </Button>
      {state.error && (
        <p id="reviewer-error" role="alert" className="w-full text-xs text-destructive">
          {state.error}
        </p>
      )}
    </form>
  );
}
