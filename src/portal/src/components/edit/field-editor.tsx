import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { setValue } from "@/lib/actions/request";
import { FIELDS, type Catalogs } from "@/lib/fields";

import { ActionForm } from "./action-form";

export type EditTarget = { entityType: "generation" | "powertrain" | "variant"; entityId: string };

const STATUS_OPTIONS = { provisional: "Provisional", verified: "Verificada", rejected: "Rechazada" };

/**
 * Inline editor for one field (a <details>, no JavaScript needed to open it). Values of the
 * sheets become manual evidence; an empty value clears the manual one. The worker validates.
 */
export function FieldEditor({
  target,
  field,
  catalogs,
  current,
}: {
  target: EditTarget;
  field: string;
  catalogs: Catalogs;
  current?: unknown;
}) {
  const info = FIELDS[field];
  const name = `${target.entityType}-${target.entityId}-${field}`;
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Editar</summary>
      <ActionForm action={setValue} submitLabel="Guardar" className="mt-2 space-y-2" testId={`edit-${field}`}>
        <input type="hidden" name="entity_type" value={target.entityType} />
        <input type="hidden" name="entity_id" value={target.entityId} />
        <input type="hidden" name="field" value={field} />
        {field === "status" ? (
          <NativeSelect name="value" defaultValue={String(current ?? "")} aria-label="Estado">
            {Object.entries(STATUS_OPTIONS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </NativeSelect>
        ) : info?.kind === "bool" ? (
          <NativeSelect name="value" defaultValue="" aria-label={info.label}>
            <option value="">— quitar el valor manual —</option>
            <option value="sí">Sí</option>
            <option value="no">No</option>
          </NativeSelect>
        ) : info?.catalog ? (
          <NativeSelect name="value" defaultValue={String(current ?? "")} aria-label={info.label}>
            <option value="">— quitar el valor manual —</option>
            {Object.entries(catalogs[info.catalog] ?? {}).map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </NativeSelect>
        ) : (
          <Input
            name="value"
            defaultValue={current == null ? "" : String(current)}
            placeholder={info?.unit ? `en ${info.unit} (vacío: quitar)` : "vacío: quitar el valor manual"}
            aria-label={info?.label ?? field}
            id={name}
          />
        )}
        <Input name="note" placeholder="Nota o fuente (opcional)" aria-label="Nota" />
      </ActionForm>
    </details>
  );
}
