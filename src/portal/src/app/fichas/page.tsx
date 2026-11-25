import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";

import { NoAccess } from "@/components/no-access";
import { PageSizeSelect } from "@/components/page-size-select";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { userWithRole } from "@/lib/auth/current-user";
import { formatValue } from "@/lib/fields";
import {
  finalListHref,
  finalRecordHref,
  parseFinalFilters,
  reasonLabel,
  UNASSIGNED_REASONS,
} from "@/lib/final-listing";
import { formatInt, formatMoney } from "@/lib/format";
import { DEFAULT_PAGE_SIZE, PAGE_SIZES } from "@/lib/paging";
import { getCatalogs } from "@/lib/queries/knowledge";
import { finalCountries, finalList } from "@/lib/queries/final";

export const metadata: Metadata = { title: "Fichas" };

export default function FinalListPage(props: PageProps<"/fichas">) {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Fichas</h1>
        <p className="text-sm text-muted-foreground">
          La ficha final de cada anuncio: lo que hereda de la base (que gana) y lo que el anuncio completa. Se
          actualiza al recalcular.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <FinalList {...props} />
      </Suspense>
    </main>
  );
}

async function FinalList({ searchParams }: PageProps<"/fichas">) {
  if (!(await userWithRole("lector"))) return <NoAccess needed="lector" />;
  const filters = parseFinalFilters(await searchParams);
  const [{ rows, total }, countries, catalogs] = await Promise.all([finalList(filters), finalCountries(), getCatalogs()]);
  const pageCount = Math.max(1, Math.ceil(total / filters.size));
  return (
    <div className="space-y-4">
      <form className="flex flex-wrap items-end gap-2" action="/fichas">
        {filters.size !== DEFAULT_PAGE_SIZE && <input type="hidden" name="por" value={filters.size} />}
        <NativeSelect name="pais" defaultValue={filters.country ?? ""} className="w-44" aria-label="País">
          <option value="">Todos los países</option>
          {countries.map((c) => (
            <option key={c} value={c}>
              {catalogs.country?.[c] ?? c}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect name="estado" defaultValue={filters.status ?? ""} className="w-56" aria-label="Estado">
          <option value="">Todos los estados</option>
          <option value="asignados">Asignados</option>
          <option value="sin-asignar">Sin asignar (todos)</option>
          {Object.entries(UNASSIGNED_REASONS).map(([code, label]) => (
            <option key={code} value={code}>
              Sin asignar: {label}
            </option>
          ))}
        </NativeSelect>
        <Input name="anio" type="number" min={1990} max={2100} defaultValue={filters.year ?? ""} placeholder="Año"
          className="w-24" aria-label="Año" />
        <Input name="q" defaultValue={filters.q ?? ""} placeholder="Buscar marca, modelo, versión…" className="w-72" />
        <Button type="submit" variant="outline">
          Filtrar
        </Button>
      </form>
      <p className="text-sm text-muted-foreground" data-testid="final-total">
        {formatInt(total)} {total === 1 ? "ficha" : "fichas"}
      </p>
      {total === 0 && !filters.country && !filters.status && !filters.year && !filters.q ? (
        <p className="text-sm">Todavía no hay fichas: se llenan con el siguiente recálculo.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Marca y modelo</TableHead>
              <TableHead>Versión</TableHead>
              <TableHead>Año</TableHead>
              <TableHead>País</TableHead>
              <TableHead>Combustible</TableHead>
              <TableHead>Transmisión</TableHead>
              <TableHead className="text-right">Potencia</TableHead>
              <TableHead className="text-right">Precio</TableHead>
              <TableHead className="text-right">Km</TableHead>
              <TableHead>Estado</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={`${r.source_site}:${r.listing_id}`} data-testid="final-row">
                <TableCell>
                  <Link href={finalRecordHref(r.source_site, r.listing_id, filters)} className="underline-offset-2 hover:underline">
                    {r.make ?? "—"} {r.model ?? ""}
                  </Link>
                </TableCell>
                <TableCell className="max-w-48 truncate">{r.trim ?? "—"}</TableCell>
                <TableCell className="tabular-nums">{r.model_year ?? "—"}</TableCell>
                <TableCell>{r.country_code}</TableCell>
                <TableCell>{formatValue("fuel_type", r.fuel_type, catalogs)}</TableCell>
                <TableCell>{formatValue("transmission_type", r.transmission_type, catalogs)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatValue("horsepower_hp", r.horsepower_hp)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatMoney(r.price, r.currency)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatInt(r.mileage_km)}</TableCell>
                <TableCell className={r.variant_id ? "" : "text-muted-foreground"}>
                  {r.variant_id ? "Asignado" : reasonLabel(r.unassigned_reason)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <div className="flex items-center justify-between gap-4">
        <PageSizeSelect
          size={filters.size}
          options={PAGE_SIZES.map((size) => ({ size, href: finalListHref({ ...filters, size, page: 1 }) }))}
        />
        <div className="flex-1">
          <Pagination page={filters.page} pageCount={pageCount} href={(p) => finalListHref(filters, p)} />
        </div>
      </div>
    </div>
  );
}
