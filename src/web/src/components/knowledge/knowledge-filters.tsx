import Form from "next/form";
import Link from "next/link";
import { Search } from "lucide-react";

import { MakeSelect } from "@/components/knowledge/make-select";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import type { KnowledgeFilters } from "@/lib/filters";

interface Props {
  options: { makes: { id: string; name: string }[]; models: { id: string; name: string }[]; years: number[] };
  filters: KnowledgeFilters;
}

export function KnowledgeFiltersForm({ options, filters }: Props) {
  // a year typed in the URL that this make/model doesn't have still shows as selected
  const years =
    filters.year && !options.years.includes(filters.year) ? [filters.year, ...options.years] : options.years;
  // key: a new URL remounts the form so the fields show the current filters
  return (
    <Form
      action="/base"
      key={JSON.stringify(filters)}
      className="grid grid-cols-2 items-end gap-3 rounded-xl border p-3 sm:grid-cols-[repeat(3,minmax(0,1fr))_auto]"
      aria-label="Filtros"
    >
      <Field label="Marca" htmlFor="f-make">
        <MakeSelect makes={options.makes} defaultValue={filters.make ?? ""} />
      </Field>
      <Field label="Modelo" htmlFor="f-model">
        <NativeSelect
          id="f-model"
          name="model"
          defaultValue={filters.model ?? ""}
          disabled={!filters.make}
          title={filters.make ? undefined : "Elige primero una marca"}
        >
          <option value="">{filters.make ? "Todos" : "Elige una marca"}</option>
          {options.models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field label="Año" htmlFor="f-year">
        <NativeSelect id="f-year" name="year" defaultValue={filters.year ?? ""}>
          <option value="">Todos</option>
          {years.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <div className="col-span-2 flex gap-2 sm:col-span-1">
        <Button type="submit" className="flex-1">
          <Search aria-hidden /> Filtrar
        </Button>
        <Button asChild variant="ghost">
          <Link href="/base">Limpiar</Link>
        </Button>
      </div>
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
