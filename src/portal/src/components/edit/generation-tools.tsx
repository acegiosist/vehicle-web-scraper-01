import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { mergeGenerations, splitGeneration } from "@/lib/actions/request";
import { formatYears } from "@/lib/format";

import { ActionForm } from "./action-form";

interface Sibling {
  id: string | number;
  name: string;
  year_from: number | null;
  year_to: number | null;
}

/** Editor tools for a generation: cut it at a year, or merge it into another of the same model. */
export function GenerationTools({ generationId, siblings }: { generationId: string; siblings: Sibling[] }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Cortar o unir</CardTitle>
        <CardDescription>
          Cortar crea una generación nueva desde ese año; unir deja esta como rechazada y pasa sus anuncios a la otra.
          Los anuncios se mueven al recalcular.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">
        <ActionForm action={splitGeneration} submitLabel="Cortar" testId="split-form">
          <input type="hidden" name="generation_id" value={generationId} />
          <Label htmlFor="year_from">Nueva generación desde el año</Label>
          <Input id="year_from" name="year_from" inputMode="numeric" required placeholder="p. ej. 2020" />
        </ActionForm>
        {siblings.length > 0 && (
          <ActionForm action={mergeGenerations} submitLabel="Unir" variant="outline" testId="merge-form">
            <input type="hidden" name="source_id" value={generationId} />
            <Label htmlFor="target_id">Unir esta generación con</Label>
            <NativeSelect id="target_id" name="target_id" required defaultValue="">
              <option value="" disabled>
                Elegir…
              </option>
              {siblings.map((s) => (
                <option key={String(s.id)} value={String(s.id)}>
                  {s.name} ({formatYears(s.year_from, s.year_to)})
                </option>
              ))}
            </NativeSelect>
          </ActionForm>
        )}
      </CardContent>
    </Card>
  );
}
