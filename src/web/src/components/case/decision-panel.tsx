"use client";

import { startTransition, useActionState, useEffect, useId, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, CircleAlert, Pencil, XCircle } from "lucide-react";
import { cn } from "cn";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { type DecideState, submitDecision } from "@/lib/actions/decide";
import { type FieldSpec, validateFieldValue } from "@/lib/fields";
import { type CorrectionKind, type Decision, DECISION_LABELS } from "@/lib/issues";
import { VEHICLE_CLASSES, vehicleClassLabel } from "@/lib/knowledge";
import type { SplitPreview } from "@/lib/queries/case";

const ICONS: Record<Decision, typeof CheckCircle2> = {
  approved: CheckCircle2,
  rejected: XCircle,
  corrected: Pencil,
};
const SHORTCUT: Record<Decision, string> = { approved: "a", rejected: "r", corrected: "c" };

interface Props {
  itemId: string;
  allowed: Decision[];
  effects: Partial<Record<Decision, string>>;
  correction: CorrectionKind | undefined;
  field: { name: string; label: string; spec: FieldSpec } | null;
  targets: string[];
  split: SplitPreview | null;
  hasReviewer: boolean;
  nextHref: string | null;
}

function isTyping(el: EventTarget | null) {
  return el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
}

export function DecisionPanel({
  itemId,
  allowed,
  effects,
  correction,
  field,
  targets,
  split,
  hasReviewer,
  nextHref,
}: Props) {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [state, action, pending] = useActionState<DecideState, FormData>(submitDecision, { status: "idle" });
  const [clientError, setClientError] = useState<string | null>(null);
  const ids = useId();

  // Submitted through onSubmit (not the form's action prop) so React does not reset the form
  // after the action: on an error the reviewer keeps the choice and the value to fix it.
  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    if (decision === "corrected" && correction === "field" && field) {
      const v = validateFieldValue(field.name, String(data.get("corrected") ?? ""));
      if (!v.ok) {
        setClientError(v.error);
        return;
      }
    }
    setClientError(null);
    startTransition(() => action(data));
  }
  const error = clientError ?? (state.status === "error" ? state.error : null);

  // a: aprobar · r: rechazar · c: corregir · Ctrl/⌘+Enter: enviar · n: siguiente caso
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        formRef.current?.requestSubmit();
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      const d = allowed.find((x) => SHORTCUT[x] === e.key.toLowerCase());
      if (d) {
        e.preventDefault();
        setDecision(d);
      } else if (e.key.toLowerCase() === "n" && nextHref) {
        e.preventDefault();
        router.push(nextHref);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [allowed, nextHref, router]);

  return (
    <form ref={formRef} onSubmit={onSubmit} className="space-y-4" aria-describedby={`${ids}-help`}>
      <input type="hidden" name="itemId" value={itemId} />
      <fieldset className="space-y-2">
        <legend className="mb-2 text-sm font-medium">Tu decisión</legend>
        {allowed.map((d) => {
          const Icon = ICONS[d];
          return (
            <label
              key={d}
              className={cn(
                "flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors hover:bg-muted/60",
                decision === d && "border-foreground/50 bg-muted",
              )}
            >
              <input
                type="radio"
                name="decision"
                value={d}
                checked={decision === d}
                onChange={() => {
                  setDecision(d);
                  setClientError(null);
                }}
                className="mt-1 accent-foreground"
                required
              />
              <span className="space-y-0.5">
                <span className="flex items-center gap-1.5 text-sm font-medium">
                  <Icon className="size-4" aria-hidden /> {DECISION_LABELS[d]}
                  <kbd className="ml-1 rounded border px-1 text-[10px] text-muted-foreground">{SHORTCUT[d]}</kbd>
                </span>
                <span className="block text-xs text-muted-foreground">{effects[d]}</span>
              </span>
            </label>
          );
        })}
      </fieldset>

      {decision === "corrected" && (
        <CorrectionInput
          key={correction}
          kind={correction}
          field={field}
          targets={targets}
          split={split}
          id={`${ids}-corrected`}
        />
      )}

      <div className="space-y-1">
        <label htmlFor={`${ids}-note`} className="text-sm">
          Nota <span className="text-muted-foreground">(opcional)</span>
        </label>
        <Textarea
          id={`${ids}-note`}
          name="note"
          maxLength={2000}
          rows={2}
          placeholder="Por qué, o la fuente que consultaste"
        />
      </div>

      {error && (
        <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {error}
        </p>
      )}
      {!hasReviewer && (
        <p className="text-sm text-muted-foreground">Escribe tu nombre arriba a la derecha para poder decidir.</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={pending || !decision || !hasReviewer}>
          {pending ? "Enviando…" : "Enviar decisión"}
        </Button>
        {nextHref && (
          <Button type="button" variant="ghost" onClick={() => router.push(nextHref)}>
            Saltar <kbd className="rounded border px-1 text-[10px] text-muted-foreground">n</kbd>
          </Button>
        )}
      </div>
      <p id={`${ids}-help`} className="text-xs text-muted-foreground">
        La decisión queda en cola y la aplica el worker de Python (`kb review worker`) en unos segundos. Atajos: a · r ·
        c para elegir, Ctrl+Enter para enviar.
      </p>
    </form>
  );
}

function CorrectionInput({
  kind,
  field,
  targets,
  split,
  id,
}: {
  kind: CorrectionKind | undefined;
  field: Props["field"];
  targets: string[];
  split: SplitPreview | null;
  id: string;
}) {
  const [mergeTarget, setMergeTarget] = useState("");
  const [name, setName] = useState("");
  const [splitting, setSplitting] = useState(false);
  const [splitClass, setSplitClass] = useState("");

  if (kind === "field" && field) {
    const { spec, label } = field;
    const hint =
      spec.range && (spec.kind === "int" || spec.kind === "float")
        ? `Entre ${spec.range[0]} y ${spec.range[1]}${spec.unit ? ` ${spec.unit}` : ""}${spec.kind === "int" ? ", entero" : ""}.`
        : null;
    return (
      <div className="space-y-1">
        <label htmlFor={id} className="text-sm">
          Valor correcto de {label.toLowerCase()}
        </label>
        {spec.kind === "bool" ? (
          <NativeSelect id={id} name="corrected" required defaultValue="">
            <option value="" disabled>
              Elige…
            </option>
            <option value="true">Sí</option>
            <option value="false">No</option>
          </NativeSelect>
        ) : spec.kind === "enum" ? (
          <NativeSelect id={id} name="corrected" required defaultValue="">
            <option value="" disabled>
              Elige…
            </option>
            {spec.values?.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </NativeSelect>
        ) : (
          <div className="flex items-center gap-2">
            <Input
              id={id}
              name="corrected"
              required
              autoFocus
              inputMode={spec.kind === "text" ? "text" : "decimal"}
              maxLength={100}
              aria-describedby={hint ? `${id}-hint` : undefined}
            />
            {spec.unit && <span className="text-sm text-muted-foreground">{spec.unit}</span>}
          </div>
        )}
        {hint && (
          <p id={`${id}-hint`} className="text-xs text-muted-foreground">
            {hint}
          </p>
        )}
      </div>
    );
  }

  const listId = `${id}-targets`;
  const value =
    kind === "model_name" && splitting
      ? `split:${splitClass}`
      : kind === "model_name" && mergeTarget
        ? `merge:${mergeTarget}`
        : name;
  const keptClass = vehicleClassLabel(split?.vehicleClass);
  return (
    <div className="space-y-3">
      <input type="hidden" name="corrected" value={value} />
      {kind === "model_name" && split && (
        <div className="space-y-2 rounded-lg border p-3">
          <label className="flex cursor-pointer items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={splitting}
              onChange={(e) => setSplitting(e.target.checked)}
              className="mt-1 accent-foreground"
            />
            <span>
              <span className="font-medium">Es una familia: dividir por el número de la versión</span>
              <span className="block text-xs text-muted-foreground">
                El número al inicio de la versión es parte del modelo. Al recalcular, cada anuncio pasa a su modelo y la
                versión queda sin el número.
              </span>
            </span>
          </label>
          {splitting && (
            <>
              <ul className="space-y-0.5 text-sm" aria-label="Modelos que se crearán">
                {split.models.map((m) => (
                  <li key={m.name} className="flex justify-between gap-2">
                    <span>{m.name}</span>
                    <span className="text-muted-foreground">
                      {m.listings} {m.listings === 1 ? "anuncio" : "anuncios"}
                    </span>
                  </li>
                ))}
              </ul>
              <div className="space-y-1">
                <label htmlFor={`${id}-class`} className="text-sm">
                  Clase de vehículo
                </label>
                <NativeSelect id={`${id}-class`} value={splitClass} onChange={(e) => setSplitClass(e.target.value)}>
                  <option value="">Mantener{keptClass ? ` (${keptClass.toLowerCase()})` : ""}</option>
                  {VEHICLE_CLASSES.map((c) => (
                    <option key={c} value={c}>
                      {vehicleClassLabel(c)}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            </>
          )}
        </div>
      )}
      <div className="space-y-1">
        <label htmlFor={id} className="text-sm">
          {kind === "make_name" ? "Nombre correcto de la marca" : "Nombre canónico"}
        </label>
        <Input
          id={id}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setMergeTarget("");
          }}
          list={kind === "make_name" ? listId : undefined}
          maxLength={80}
          autoFocus
          disabled={!!mergeTarget || splitting}
        />
        {kind === "make_name" && (
          <>
            <datalist id={listId}>
              {targets.map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
            <p className="text-xs text-muted-foreground">Si eliges una marca existente, las dos se fusionan.</p>
          </>
        )}
      </div>
      {kind === "model_name" && targets.length > 0 && (
        <div className="space-y-1">
          <label htmlFor={`${id}-merge`} className="text-sm">
            …o fusionar con un modelo existente
          </label>
          <NativeSelect
            id={`${id}-merge`}
            value={mergeTarget}
            onChange={(e) => setMergeTarget(e.target.value)}
            disabled={splitting}
          >
            <option value="">No fusionar</option>
            {targets.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}
    </div>
  );
}
