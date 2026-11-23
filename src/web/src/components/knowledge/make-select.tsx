"use client";

import { NativeSelect } from "@/components/ui/native-select";

interface Props {
  makes: { id: string; name: string }[];
  defaultValue: string;
}

/** The make filter. Choosing a make clears the model and year (they belong to the previous make)
 *  and submits the form, so the server sends that make's models. Without JavaScript the
 *  "Filtrar" button does the same. */
export function MakeSelect({ makes, defaultValue }: Props) {
  return (
    <NativeSelect
      id="f-make"
      name="make"
      defaultValue={defaultValue}
      onChange={(e) => {
        const form = e.currentTarget.form;
        if (!form) return;
        for (const name of ["model", "year"]) {
          const el = form.elements.namedItem(name);
          if (el instanceof HTMLSelectElement) el.value = "";
        }
        form.requestSubmit();
      }}
    >
      <option value="">Todas</option>
      {makes.map((m) => (
        <option key={m.id} value={m.id}>
          {m.name}
        </option>
      ))}
    </NativeSelect>
  );
}
