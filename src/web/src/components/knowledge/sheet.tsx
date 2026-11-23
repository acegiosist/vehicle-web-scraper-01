import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { fieldLabel, FIELDS, formatValue } from "@/lib/fields";
import { formatDate, formatInt, formatPercent } from "@/lib/format";
import { issueInfo } from "@/lib/issues";
import { cellKey, sourceLabel, statusLabel } from "@/lib/knowledge";
import type { VariantCase, VariantEvidence, variantHistory } from "@/lib/queries/knowledge";

type Winners = Map<string, VariantEvidence>;
type OpenCases = Map<string, VariantCase>;

/** Open cases by spec cell (``cellKey(field, country)``); the first one wins. */
export function casesByCell(cases: VariantCase[]): OpenCases {
  const map: OpenCases = new Map();
  for (const c of cases) {
    if (!c.field) continue;
    const key = cellKey(c.field, c.country ?? "");
    if (!map.has(key)) map.set(key, c);
  }
  return map;
}

export const MECH_FIELDS = Object.keys(FIELDS).filter((f) => FIELDS[f].group === "mech");
export const EQUIP_FIELDS = Object.keys(FIELDS).filter((f) => FIELDS[f].group === "equip");

/** The mechanical sheet (one value per variant, every country), with where each value comes from. */
export function MechTable({
  spec,
  winners,
  cases,
}: {
  spec: Record<string, unknown> | null;
  winners: Winners;
  cases: OpenCases;
}) {
  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Campo</TableHead>
            <TableHead>Valor</TableHead>
            <TableHead className="hidden md:table-cell">Fuente</TableHead>
            <TableHead className="w-40">Revisión</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {MECH_FIELDS.map((f) => {
            const value = spec?.[f];
            const known = value !== null && value !== undefined;
            return (
              <TableRow key={f}>
                <TableCell className="text-muted-foreground">{fieldLabel(f)}</TableCell>
                <TableCell className={known ? "font-medium" : "text-muted-foreground"}>
                  {known ? formatValue(f, value) : "Sin dato"}
                </TableCell>
                <TableCell className="hidden whitespace-normal md:table-cell">
                  {known && <Provenance evidence={winners.get(cellKey(f))} />}
                </TableCell>
                <TableCell>
                  <CaseLink item={cases.get(cellKey(f))} />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/** Equipment: one column per country the variant was seen in. */
export function EquipTable({
  countries,
  marketSpecs,
  winners,
  cases,
}: {
  countries: { country: string; listings_seen: number }[];
  marketSpecs: (Record<string, unknown> & { country: string })[];
  winners: Winners;
  cases: OpenCases;
}) {
  if (countries.length === 0) {
    return <p className="text-sm text-muted-foreground">La variante aún no tiene anuncios en ningún país.</p>;
  }
  const byCountry = new Map(marketSpecs.map((m) => [m.country, m]));
  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Campo</TableHead>
            {countries.map((c) => (
              <TableHead key={c.country}>
                {c.country}{" "}
                <span className="font-normal text-muted-foreground">
                  ({formatInt(c.listings_seen)} {c.listings_seen === 1 ? "anuncio" : "anuncios"})
                </span>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {EQUIP_FIELDS.map((f) => (
            <TableRow key={f}>
              <TableCell className="text-muted-foreground">{fieldLabel(f)}</TableCell>
              {countries.map(({ country }) => {
                const value = byCountry.get(country)?.[f];
                const known = value !== null && value !== undefined;
                const evidence = winners.get(cellKey(f, country));
                const item = cases.get(cellKey(f, country));
                return (
                  <TableCell key={country} className="whitespace-normal">
                    <div className={known ? "font-medium" : "text-muted-foreground"}>
                      {known ? formatValue(f, value) : "Sin dato"}
                    </div>
                    {known && evidence && (
                      <div className="text-xs text-muted-foreground">{sourceLabel(evidence.source_kind)}</div>
                    )}
                    <CaseLink item={item} />
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function Provenance({ evidence }: { evidence: VariantEvidence | undefined }) {
  if (!evidence) return <span className="text-xs text-muted-foreground">—</span>;
  const details = [
    evidence.confidence !== null ? `confianza ${formatPercent(evidence.confidence)}` : null,
    evidence.support_count > 0 && evidence.source_kind.startsWith("listing")
      ? `${formatInt(evidence.support_count)} ${evidence.support_count === 1 ? "anuncio" : "anuncios"}`
      : null,
    evidence.sites.length > 0 ? evidence.sites.join(", ") : null,
  ].filter(Boolean);
  return (
    <div>
      <div>{sourceLabel(evidence.source_kind)}</div>
      {details.length > 0 && <div className="text-xs text-muted-foreground">{details.join(" · ")}</div>}
    </div>
  );
}

function CaseLink({ item }: { item: VariantCase | undefined }) {
  if (!item?.id) return null;
  return (
    <Link href={`/cola/${item.id}`} className="inline-flex" title={issueInfo(item.issue).title}>
      <Badge variant="secondary">En revisión · caso #{item.id}</Badge>
    </Link>
  );
}

/** Every candidate value, the published one marked. */
export function EvidenceTable({ evidence, winners }: { evidence: VariantEvidence[]; winners: Winners }) {
  if (evidence.length === 0) return <p className="text-sm text-muted-foreground">No hay evidencia registrada.</p>;
  const published = new Set([...winners.values()].map((e) => e.id));
  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Campo</TableHead>
            <TableHead>País</TableHead>
            <TableHead>Valor</TableHead>
            <TableHead>Fuente</TableHead>
            <TableHead>Estado</TableHead>
            <TableHead className="text-right">Soporte</TableHead>
            <TableHead className="text-right">Acuerdo</TableHead>
            <TableHead className="text-right">Confianza</TableHead>
            <TableHead>Portales</TableHead>
            <TableHead>Motivo</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {evidence.map((e) => (
            <TableRow key={e.id}>
              <TableCell>{fieldLabel(e.field)}</TableCell>
              <TableCell>{e.country || "Todos"}</TableCell>
              <TableCell className="font-medium">{formatValue(e.field, e.value)}</TableCell>
              <TableCell>{sourceLabel(e.source_kind)}</TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  <span className="text-xs">{statusLabel(e.status)}</span>
                  {published.has(e.id) && <Badge>Publicada</Badge>}
                </div>
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatInt(e.support_count)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPercent(e.agreement)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPercent(e.confidence)}</TableCell>
              <TableCell>{e.sites.join(", ") || "—"}</TableCell>
              <TableCell className="max-w-[16rem] whitespace-normal text-xs text-muted-foreground">
                {e.reason ?? "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

type HistoryRow = Awaited<ReturnType<typeof variantHistory>>[number];

export function HistoryTable({ rows }: { rows: HistoryRow[] }) {
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">Sin cambios registrados.</p>;
  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Fecha</TableHead>
            <TableHead>Campo</TableHead>
            <TableHead>País</TableHead>
            <TableHead>Antes</TableHead>
            <TableHead>Después</TableHead>
            <TableHead className="hidden md:table-cell">Fuente</TableHead>
            <TableHead className="hidden md:table-cell">Motivo</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((h) => (
            <TableRow key={h.id}>
              <TableCell className="text-muted-foreground">{formatDate(h.changed_at)}</TableCell>
              <TableCell>{fieldLabel(h.field)}</TableCell>
              <TableCell>{h.country || "Todos"}</TableCell>
              <TableCell>{formatValue(h.field, h.old_value)}</TableCell>
              <TableCell className="font-medium">{formatValue(h.field, h.new_value)}</TableCell>
              <TableCell className="hidden md:table-cell">{sourceLabel(h.new_source)}</TableCell>
              <TableCell className="hidden text-xs text-muted-foreground md:table-cell">{h.reason ?? "—"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
