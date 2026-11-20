import { ExternalLink } from "lucide-react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fieldLabel, formatValue } from "@/lib/fields";
import { formatInt, formatMoney } from "@/lib/format";

interface Listing {
  source_site: string;
  listing_id: string;
  country: string;
  raw_make: string | null;
  raw_model: string | null;
  raw_trim: string | null;
  raw_year: number | null;
  excluded_reason: string | null;
  url: string | null;
  price: number | null;
  currency: string | null;
  mileage_km: number | null;
  value: unknown;
}

/** Only links to the listing's own portal over http(s) are rendered as links. */
function safeUrl(url: string | null): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

export function ListingsTable({ rows, total, field }: { rows: Listing[]; total: number; field: string | null }) {
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No hay anuncios vinculados.</p>;
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        {total > rows.length
          ? `Los ${rows.length} más recientes de ${formatInt(total)}`
          : `${formatInt(total)} anuncios`}
      </p>
      <div className="rounded-xl border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Portal</TableHead>
              <TableHead>Como lo escribió el vendedor</TableHead>
              <TableHead>Año</TableHead>
              {field && <TableHead>{fieldLabel(field)}</TableHead>}
              <TableHead className="hidden text-right md:table-cell">Precio</TableHead>
              <TableHead className="hidden text-right md:table-cell">Km</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((l) => {
              const href = safeUrl(l.url);
              return (
                <TableRow key={`${l.source_site}:${l.listing_id}`}>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      {href ? (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 hover:underline"
                        >
                          {l.source_site}
                          <ExternalLink className="size-3" aria-label="(abre el portal)" />
                        </a>
                      ) : (
                        l.source_site
                      )}
                      <span className="text-xs text-muted-foreground">{l.country}</span>
                    </div>
                    {l.excluded_reason && <div className="text-xs text-destructive">Excluido: {l.excluded_reason}</div>}
                  </TableCell>
                  <TableCell className="max-w-[24rem] whitespace-normal">
                    {[l.raw_make, l.raw_model, l.raw_trim].filter(Boolean).join(" · ") || "—"}
                  </TableCell>
                  <TableCell className="tabular-nums">{l.raw_year ?? "—"}</TableCell>
                  {field && <TableCell>{formatValue(field, l.value)}</TableCell>}
                  <TableCell className="hidden text-right tabular-nums md:table-cell">
                    {formatMoney(l.price, l.currency)}
                  </TableCell>
                  <TableCell className="hidden text-right tabular-nums md:table-cell">
                    {formatInt(l.mileage_km)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
