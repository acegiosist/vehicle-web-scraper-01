import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";

import { NoAccess } from "@/components/no-access";
import { PageSizeSelect } from "@/components/page-size-select";
import { Pagination } from "@/components/pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { userWithRole } from "@/lib/auth/current-user";
import { formatValue } from "@/lib/fields";
import { formatInt } from "@/lib/format";
import { DEFAULT_PAGE_SIZE, PAGE_SIZES } from "@/lib/paging";
import { getCatalogs } from "@/lib/queries/knowledge";
import { identityCountries, identityList } from "@/lib/queries/final";
import { identityHref, identityListHref, parseIdentityFilters, statusLabel, yearRange } from "@/lib/vehicle-identity";

export const metadata: Metadata = { title: "Fichas" };

export default function IdentityListPage(props: PageProps<"/fichas">) {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Fichas</h1>
        <p className="text-sm text-muted-foreground">
          La ficha de identidad de cada vehículo (una variante comercial: generación, tren motriz, país y versión), con lo
          que la base sabe de él y de dónde sale cada dato. Solo valores de la base, nunca de un anuncio suelto. Se
          actualiza al recalcular.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <IdentityList {...props} />
      </Suspense>
    </main>
  );
}

async function IdentityList({ searchParams }: PageProps<"/fichas">) {
  if (!(await userWithRole("lector"))) return <NoAccess needed="lector" />;
  const filters = parseIdentityFilters(await searchParams);
  const [{ rows, total }, countries, catalogs] = await Promise.all([
    identityList(filters), identityCountries(), getCatalogs(),
  ]);
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
        <NativeSelect name="estado" defaultValue={filters.status ?? ""} className="w-44" aria-label="Estado">
          <option value="">Todos los estados</option>
          <option value="verificadas">Verificadas</option>
          <option value="provisionales">Provisionales</option>
        </NativeSelect>
        <NativeSelect name="version" defaultValue={filters.knownTrim ? "conocida" : ""} className="w-52" aria-label="Versión">
          <option value="">Con y sin versión</option>
          <option value="conocida">Solo con versión conocida</option>
        </NativeSelect>
        <Input name="q" defaultValue={filters.q ?? ""} placeholder="Buscar marca, modelo, versión…" className="w-72" />
        <Button type="submit" variant="outline">
          Filtrar
        </Button>
      </form>
      <p className="text-sm text-muted-foreground" data-testid="identity-total">
        {formatInt(total)} {total === 1 ? "ficha" : "fichas"}
      </p>
      {total === 0 && !filters.country && !filters.status && !filters.knownTrim && !filters.q ? (
        <p className="text-sm">Todavía no hay fichas: se llenan con el siguiente recálculo.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Vehículo</TableHead>
              <TableHead>Generación</TableHead>
              <TableHead>País</TableHead>
              <TableHead>Vendida</TableHead>
              <TableHead>Motor</TableHead>
              <TableHead>Transmisión</TableHead>
              <TableHead>Tracción</TableHead>
              <TableHead className="text-right">Potencia</TableHead>
              <TableHead className="text-right">Anuncios</TableHead>
              <TableHead>Estado</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={String(r.variant_id)} data-testid="identity-row">
                <TableCell>
                  <Link href={identityHref(r.variant_id, filters)} className="underline-offset-2 hover:underline">
                    {r.make} {r.model} {r.trim ?? <span className="text-muted-foreground">(sin versión)</span>}
                  </Link>
                </TableCell>
                <TableCell>
                  {r.generation_name}{" "}
                  <span className="text-muted-foreground tabular-nums">{yearRange(r.year_from, r.year_to)}</span>
                </TableCell>
                <TableCell>{r.country_code}</TableCell>
                <TableCell className="tabular-nums">{yearRange(r.sale_year_from, r.sale_year_to)}</TableCell>
                <TableCell>
                  {[formatValue("engine_displacement_l", r.engine_displacement_l), formatValue("fuel_type", r.fuel_type, catalogs)]
                    .filter((v) => v !== "—").join(" · ") || "—"}
                </TableCell>
                <TableCell>{formatValue("transmission_type", r.transmission_type, catalogs)}</TableCell>
                <TableCell>{formatValue("drivetrain", r.drivetrain, catalogs)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatValue("horsepower_hp", r.horsepower_hp)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatInt(r.listings)}</TableCell>
                <TableCell>
                  <Badge variant={r.variant_status === "verified" ? "secondary" : "outline"}>{statusLabel(r.variant_status)}</Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <div className="flex items-center justify-between gap-4">
        <PageSizeSelect
          size={filters.size}
          options={PAGE_SIZES.map((size) => ({ size, href: identityListHref({ ...filters, size, page: 1 }) }))}
        />
        <div className="flex-1">
          <Pagination page={filters.page} pageCount={pageCount} href={(p) => identityListHref(filters, p)} />
        </div>
      </div>
    </div>
  );
}
