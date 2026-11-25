"use client";

import { useActionState, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { applySource, type RequestState } from "@/lib/actions/request";

/** One proposed value, already formatted on the server. */
export interface ComparisonRow {
  key: string; // entity_type:entity_id:field, what source_apply receives
  group: string; // "Generación" or the powertrain's label
  field: string;
  current: string;
  currentSource: string;
  proposed: string;
  detail: string; // records, years and the source's names for what matched
  alternatives: string; // other values the source gave, when its records disagree
  same: boolean; // the source says what the base already has
  empty: boolean; // the base has nothing yet
}

/**
 * What a source returned next to what the base has, one checkbox per value, and one button that
 * saves every ticked value at once (a source_apply request). Values the base doesn't have yet
 * start ticked; the worker takes the values from the lookup itself, never from this form.
 */
export function SourceComparison({
  lookupId,
  generationId,
  title,
  credit,
  notes,
  rows,
  saved,
}: {
  lookupId: string;
  generationId: string;
  title: string;
  credit: string;
  notes: string[];
  rows: ComparisonRow[];
  saved: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(
    () => new Set(saved ? [] : rows.filter((r) => r.empty && !r.same).map((r) => r.key)),
  );
  // closes once the request is queued; the page then refreshes until the worker applies it
  const [state, formAction, pending] = useActionState<RequestState, FormData>(async (prev, form) => {
    const next = await applySource(prev, form);
    if (next.status === "queued") setOpen(false);
    return next;
  }, { status: "idle" });
  const toggle = (key: string, on: boolean) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  const differing = rows.filter((r) => !r.same).map((r) => r.key);
  const groups = [...new Set(rows.map((r) => r.group))];
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant={saved ? "outline" : "default"} data-testid="open-comparison">
          {saved ? "Ver comparación" : "Comparar y aceptar"}
        </Button>
      </DialogTrigger>
      <DialogContent data-testid="comparison">
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>
          Lo que la base tiene hoy al lado de lo que respondió la fuente. Marca lo que aceptas y guarda todo de una vez:
          queda como fuente externa (gana a los anuncios, pierde ante un valor manual). {credit}.
        </DialogDescription>
        {notes.length > 0 && (
          <ul className="list-disc pl-5 text-xs text-muted-foreground">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
        <form action={formAction} className="flex min-h-0 flex-1 flex-col gap-3">
          <input type="hidden" name="lookup_id" value={lookupId} />
          <input type="hidden" name="generation_id" value={generationId} />
          <div className="min-h-0 flex-1 overflow-y-auto">
            {rows.length === 0 ? (
              <p className="text-sm">La fuente no devolvió valores para esta generación.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Campo</TableHead>
                    <TableHead>En la base</TableHead>
                    <TableHead>Según la fuente</TableHead>
                    <TableHead className="w-20 text-center">Aceptar</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {groups.map((g) => [
                    <TableRow key={`group:${g}`} className="bg-muted/50 hover:bg-muted/50">
                      <TableCell colSpan={4} className="font-medium">
                        {g}
                      </TableCell>
                    </TableRow>,
                    ...rows
                      .filter((r) => r.group === g)
                      .map((r) => (
                        <TableRow key={r.key} data-testid="comparison-row" data-key={r.key}>
                          <TableCell className="align-top text-muted-foreground">{r.field}</TableCell>
                          <TableCell className="align-top">
                            <span className="font-medium">{r.current}</span>
                            {r.currentSource && <span className="block text-xs text-muted-foreground">{r.currentSource}</span>}
                          </TableCell>
                          <TableCell className="align-top">
                            <span className={r.same ? "font-medium text-muted-foreground" : "font-medium"}>{r.proposed}</span>
                            <span className="block text-xs text-muted-foreground">{r.detail}</span>
                            {r.alternatives && <span className="block text-xs text-amber-700 dark:text-amber-400">{r.alternatives}</span>}
                          </TableCell>
                          <TableCell className="text-center align-top">
                            {r.same ? (
                              <span className="text-xs text-muted-foreground">igual</span>
                            ) : (
                              <input
                                type="checkbox"
                                name="accept"
                                value={r.key}
                                checked={checked.has(r.key)}
                                onChange={(e) => toggle(r.key, e.target.checked)}
                                aria-label={`Aceptar ${r.field} (${r.group})`}
                                className="size-4"
                              />
                            )}
                          </TableCell>
                        </TableRow>
                      )),
                  ])}
                </TableBody>
              </Table>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t pt-3">
            <Button type="submit" size="sm" disabled={pending || checked.size === 0} data-testid="save-accepted">
              {pending ? "Enviando…" : `Guardar ${checked.size} ${checked.size === 1 ? "valor" : "valores"}`}
            </Button>
            {differing.length > 0 && (
              <>
                <Button type="button" size="sm" variant="outline" onClick={() => setChecked(new Set(differing))}>
                  Marcar todos
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => setChecked(new Set())}>
                  Desmarcar
                </Button>
              </>
            )}
            {state.status === "error" && <span className="text-xs text-destructive">{state.error}</span>}
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
