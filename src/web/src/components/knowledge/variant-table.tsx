import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { variantHref, type KnowledgeFilters } from "@/lib/filters";
import { formatInt } from "@/lib/format";
import { engineText, statusLabel } from "@/lib/knowledge";
import type { VariantRow } from "@/lib/queries/knowledge";

export function VariantTable({ rows, filters }: { rows: VariantRow[]; filters: KnowledgeFilters }) {
  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Marca</TableHead>
            <TableHead>Modelo</TableHead>
            <TableHead>Versión</TableHead>
            <TableHead className="w-16">Año</TableHead>
            <TableHead className="hidden md:table-cell">Motor</TableHead>
            <TableHead className="hidden lg:table-cell">Carrocería</TableHead>
            <TableHead className="hidden md:table-cell">Países</TableHead>
            <TableHead className="text-right">Anuncios</TableHead>
            <TableHead className="w-36">Estado</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.id} className="relative">
              <TableCell className="text-muted-foreground">{r.make_name}</TableCell>
              <TableCell>
                <Link
                  href={variantHref(r.id, filters)}
                  className="font-medium after:absolute after:inset-0 hover:underline focus-visible:outline-none"
                >
                  {r.model_name}
                </Link>
              </TableCell>
              <TableCell className="max-w-[16rem] whitespace-normal">{r.trim_name ?? "—"}</TableCell>
              <TableCell className="tabular-nums">{r.model_year}</TableCell>
              <TableCell className="hidden whitespace-normal md:table-cell">{engineText(r) || "—"}</TableCell>
              <TableCell className="hidden lg:table-cell">{r.body_style ?? "—"}</TableCell>
              <TableCell className="hidden md:table-cell">{r.countries.join(", ") || "—"}</TableCell>
              <TableCell className="text-right tabular-nums">{formatInt(r.listings)}</TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {r.status === "accepted" ? (
                    <span className="text-xs text-muted-foreground">{statusLabel(r.status)}</span>
                  ) : (
                    <Badge variant={r.status === "rejected" ? "destructive" : "secondary"}>
                      {statusLabel(r.status)}
                    </Badge>
                  )}
                  {r.open_cases > 0 && (
                    <Badge variant="outline">
                      {r.open_cases} {r.open_cases === 1 ? "caso abierto" : "casos abiertos"}
                    </Badge>
                  )}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
