import { FieldEditor, type EditTarget } from "@/components/edit/field-editor";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fieldLabel, formatValue, SOURCE_LABELS, type Catalogs } from "@/lib/fields";
import { formatPercent } from "@/lib/format";
import type { Evidence } from "@/lib/queries/knowledge";

interface Props {
  fields: readonly string[];
  values: Record<string, unknown>;
  evidence: Evidence;
  catalogs: Catalogs;
  /** set for editors: each row gets an inline editor */
  edit?: EditTarget;
}

/** A level's published values with where each came from (manual, external, listings, AI). */
export function Sheet({ fields, values, evidence, catalogs, edit }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-1/3">Campo</TableHead>
          <TableHead>Valor</TableHead>
          <TableHead>Fuente</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {fields.map((f) => {
          const e = evidence[f];
          const pending = e?.candidates.filter((c) => c.status === "pending") ?? [];
          return (
            <TableRow key={f} data-field={f}>
              <TableCell className="align-top text-muted-foreground">{fieldLabel(f)}</TableCell>
              <TableCell className="align-top">
                <span className="font-medium">{formatValue(f, values[f], catalogs)}</span>
                {edit && <FieldEditor target={edit} field={f} catalogs={catalogs} current={values[f]} />}
              </TableCell>
              <TableCell className="align-top text-xs text-muted-foreground">
                {e?.published ? (
                  <span className="flex flex-wrap items-center gap-1">
                    <Badge variant={e.published.source_kind === "manual" ? "secondary" : "outline"}>
                      {SOURCE_LABELS[e.published.source_kind] ?? e.published.source_kind}
                    </Badge>
                    {e.published.source_kind === "listings" && (
                      <span>
                        {e.published.support} anuncios
                        {e.published.agreement != null && `, ${formatPercent(e.published.agreement)} de acuerdo`}
                      </span>
                    )}
                  </span>
                ) : pending.length ? (
                  <span>
                    Sin publicar: {pending[0].support} anuncios, {formatPercent(pending[0].agreement)} de acuerdo
                  </span>
                ) : (
                  "—"
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
