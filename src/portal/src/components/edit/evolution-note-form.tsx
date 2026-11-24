import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { addEvolutionNote } from "@/lib/actions/request";
import { FIELDS, VARIANT_SHEET_GROUPS } from "@/lib/fields";

import { ActionForm } from "./action-form";

/** "From <year>, <field> = <value>" on one variant, instead of a duplicated sheet. */
export function EvolutionNoteForm({ variantId }: { variantId: string }) {
  return (
    <ActionForm action={addEvolutionNote} submitLabel="Agregar nota" testId="evolution-form" className="space-y-3">
      <input type="hidden" name="variant_id" value={variantId} />
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor="evo-field">Campo</Label>
          <NativeSelect id="evo-field" name="field" required defaultValue="">
            <option value="" disabled>
              Elegir…
            </option>
            {VARIANT_SHEET_GROUPS.map(([group, fields]) => (
              <optgroup key={group} label={group}>
                {fields
                  .filter((f) => f !== "seats")
                  .map((f) => (
                    <option key={f} value={f}>
                      {FIELDS[f]?.label ?? f}
                    </option>
                  ))}
              </optgroup>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1">
          <Label htmlFor="evo-value">Valor</Label>
          <Input id="evo-value" name="value" required placeholder="sí, no, 6, LED…" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="evo-year">Desde el año</Label>
          <Input id="evo-year" name="year_from" inputMode="numeric" required placeholder="2026" />
        </div>
      </div>
      <Input name="note" placeholder="Nota o fuente (opcional)" aria-label="Nota" />
    </ActionForm>
  );
}
