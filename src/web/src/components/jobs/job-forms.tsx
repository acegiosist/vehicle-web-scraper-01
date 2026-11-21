"use client";

import { useActionState, useId, useState } from "react";
import { CircleAlert, Download, RefreshCw, Sparkles, Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { enqueueJob, type JobFormState } from "@/lib/actions/jobs";

interface Run {
  id: string;
  kind: string;
  request_count: number;
}

/** One form = one job. The Server Action redirects to the job's page when it is queued. */
function JobForm({
  command,
  children,
  submit,
}: {
  command?: string;
  children?: React.ReactNode;
  submit: React.ReactNode;
}) {
  const [state, action, pending] = useActionState<JobFormState, FormData>(enqueueJob, {});
  return (
    <form action={action} className="space-y-3">
      {command && <input type="hidden" name="command" value={command} />}
      {children}
      <fieldset disabled={pending} className="flex flex-wrap gap-2">
        {submit}
      </fieldset>
      {state.error && (
        <p role="alert" className="flex items-start gap-2 text-sm text-destructive">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {state.error}
        </p>
      )}
    </form>
  );
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-xs text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}

export function JobForms({ runs }: { runs: Run[] }) {
  const id = useId();
  const [kind, setKind] = useState("identity");
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <RefreshCw className="size-4" aria-hidden /> Recalcular
          </CardTitle>
          <CardDescription>
            Normalizar resuelve marcas, modelos y años con reglas; consolidar arma variantes y publica las fichas. Con
            los datos completos tarda unos minutos y las decisiones esperan mientras corre.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <JobForm
            submit={
              <>
                <Button type="submit" name="command" value="recalculate">
                  Recalcular todo
                </Button>
                <Button type="submit" name="command" value="normalize" variant="outline">
                  Solo normalizar
                </Button>
                <Button type="submit" name="command" value="consolidate" variant="outline">
                  Solo consolidar
                </Button>
              </>
            }
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Download className="size-4" aria-hidden /> Exportar anuncios
          </CardTitle>
          <CardDescription>
            Cada anuncio en el esquema estricto, con los huecos completados desde la base de conocimiento.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <JobForm command="export" submit={<Button type="submit">Exportar</Button>}>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Formato" htmlFor={`${id}-format`}>
                <NativeSelect id={`${id}-format`} name="format" defaultValue="xlsx" className="w-32">
                  <option value="xlsx">Excel (XLSX)</option>
                  <option value="csv">CSV</option>
                  <option value="json">JSON</option>
                </NativeSelect>
              </Field>
              <label className="flex items-center gap-2 pb-1.5 text-sm">
                <input type="checkbox" name="with_sources" className="accent-foreground" /> Con columnas de origen
              </label>
            </div>
          </JobForm>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="size-4" aria-hidden /> IA: estimar costo
          </CardTitle>
          <CardDescription>
            Arma los requests a Claude y calcula el costo sin enviar nada. Desde el estimado se puede enviar, si el
            envío está habilitado.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <JobForm command="ai_estimate" submit={<Button type="submit">Estimar</Button>}>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Qué" htmlFor={`${id}-kind`}>
                <NativeSelect id={`${id}-kind`} name="kind" value={kind} onChange={(e) => setKind(e.target.value)}>
                  <option value="identity">Identidad (marcas y modelos)</option>
                  <option value="specs">Fichas técnicas</option>
                </NativeSelect>
              </Field>
              <Field label="Esfuerzo" htmlFor={`${id}-effort`}>
                <NativeSelect id={`${id}-effort`} name="effort" defaultValue="">
                  <option value="">Por defecto ({kind === "identity" ? "low" : "medium"})</option>
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                </NativeSelect>
              </Field>
              <Field label="Marcas (piloto, separadas por coma)" htmlFor={`${id}-makes`}>
                <Input id={`${id}-makes`} name="makes" placeholder="Toyota, Mazda" maxLength={600} />
              </Field>
              <Field label="Máximo de requests" htmlFor={`${id}-limit`}>
                <Input id={`${id}-limit`} name="limit" type="number" min={1} max={10000} placeholder="Todos" />
              </Field>
              {kind === "specs" && (
                <Field label="Mínimo de anuncios por variante" htmlFor={`${id}-min`}>
                  <Input id={`${id}-min`} name="min_listings" type="number" min={1} max={1000} defaultValue={3} />
                </Field>
              )}
            </div>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" name="count_tokens" className="mt-1 accent-foreground" />
              <span>
                Contar tokens exactos
                <span className="block text-xs text-muted-foreground">
                  Usa el endpoint gratuito count_tokens: envía el texto a Anthropic (nunca el de Cofino).
                </span>
              </span>
            </label>
          </JobForm>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Inbox className="size-4" aria-hidden /> IA: recoger resultados
          </CardTitle>
          <CardDescription>
            Trae las respuestas de un batch terminado y las convierte en casos de revisión. Nada se acepta solo.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <JobForm command="ai_collect" submit={<Button type="submit">Recoger</Button>}>
            <Field label="Corrida" htmlFor={`${id}-run`}>
              <NativeSelect id={`${id}-run`} name="run_id" defaultValue="">
                <option value="">La última enviada</option>
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    #{r.id} · {r.kind === "identity" ? "identidad" : "fichas"} · {r.request_count} requests
                  </option>
                ))}
              </NativeSelect>
            </Field>
            {runs.length === 0 && (
              <p className="text-xs text-muted-foreground">No hay corridas enviadas por recoger.</p>
            )}
          </JobForm>
        </CardContent>
      </Card>
    </div>
  );
}
