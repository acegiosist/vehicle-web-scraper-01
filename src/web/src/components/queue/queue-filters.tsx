import Form from "next/form";
import Link from "next/link";
import { Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import type { QueueFilters } from "@/lib/filters";
import { ENTITY_LABELS, issueInfo, LEVELS } from "@/lib/issues";

interface Props {
  options: { issues: string[]; makes: string[]; countries: string[] };
  filters: QueueFilters;
}

export function QueueFiltersForm({ options, filters }: Props) {
  // key: a new URL remounts the form so the fields show the current filters
  return (
    <Form
      action="/cola"
      key={JSON.stringify(filters)}
      className="grid grid-cols-2 items-end gap-3 rounded-xl border p-3 sm:grid-cols-4 xl:grid-cols-[repeat(7,minmax(0,1fr))_auto]"
      aria-label="Filtros"
    >
      <Field label="Nivel" htmlFor="f-level">
        <NativeSelect id="f-level" name="level" defaultValue={filters.level ?? ""}>
          <option value="">Todos</option>
          {Object.entries(LEVELS).map(([k, v]) => (
            <option key={k} value={k}>
              {k}. {v}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field label="Tipo de caso" htmlFor="f-issue">
        <NativeSelect id="f-issue" name="issue" defaultValue={filters.issue ?? ""}>
          <option value="">Todos</option>
          {options.issues.map((i) => (
            <option key={i} value={i}>
              {issueInfo(i).title}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field label="Entidad" htmlFor="f-entity">
        <NativeSelect id="f-entity" name="entity" defaultValue={filters.entity ?? ""}>
          <option value="">Todas</option>
          {Object.entries(ENTITY_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field label="Revisión" htmlFor="f-kind">
        <NativeSelect id="f-kind" name="kind" defaultValue={filters.kind ?? ""}>
          <option value="">Todas</option>
          <option value="individual">Individual</option>
          <option value="sample">Muestra de lote</option>
        </NativeSelect>
      </Field>
      <Field label="Origen" htmlFor="f-origin">
        <NativeSelect id="f-origin" name="origin" defaultValue={filters.origin ?? ""}>
          <option value="">Todos</option>
          <option value="ai">Propuesta de la IA</option>
          <option value="rules">Reglas</option>
        </NativeSelect>
      </Field>
      <Field label="Marca" htmlFor="f-make">
        <NativeSelect id="f-make" name="make" defaultValue={filters.make ?? ""}>
          <option value="">Todas</option>
          {options.makes.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field label="Buscar" htmlFor="f-q">
        <Input id="f-q" name="q" type="search" defaultValue={filters.q ?? ""} placeholder="Texto, campo…" />
      </Field>
      <div className="col-span-2 flex gap-2 sm:col-span-1">
        <Button type="submit" className="flex-1">
          <Search aria-hidden /> Filtrar
        </Button>
        <Button asChild variant="ghost">
          <Link href="/cola">Limpiar</Link>
        </Button>
      </div>
      {filters.country && <input type="hidden" name="country" value={filters.country} />}
    </Form>
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
