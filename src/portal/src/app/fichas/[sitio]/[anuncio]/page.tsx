import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { KeyValues } from "@/components/key-values";
import { NoAccess } from "@/components/no-access";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { userWithRole } from "@/lib/auth/current-user";
import { fieldLabel, formatValue } from "@/lib/fields";
import { FINAL_SHEET_GROUPS, finalListHref, parseFinalFilters, reasonLabel } from "@/lib/final-listing";
import { formatDate, formatInt, formatMoney } from "@/lib/format";
import { getCatalogs } from "@/lib/queries/knowledge";
import { finalRecord } from "@/lib/queries/final";

export const metadata: Metadata = { title: "Ficha" };

export default function FinalRecordPage(props: PageProps<"/fichas/[sitio]/[anuncio]">) {
  return (
    <main className="space-y-6">
      <Suspense fallback={<Skeleton className="h-96" />}>
        <FinalRecordView {...props} />
      </Suspense>
    </main>
  );
}

async function FinalRecordView({ params, searchParams }: PageProps<"/fichas/[sitio]/[anuncio]">) {
  if (!(await userWithRole("lector"))) return <NoAccess needed="lector" />;
  const [{ sitio, anuncio }, sp] = await Promise.all([params, searchParams]);
  const [r, catalogs] = await Promise.all([finalRecord(sitio, anuncio), getCatalogs()]);
  if (!r) notFound();
  const values = r as unknown as Record<string, unknown>;
  const link = (href: string, text: string) => (
    <Link href={href} className="underline">
      {text}
    </Link>
  );
  return (
    <div className="space-y-6">
      <Link href={finalListHref(parseFinalFilters(sp))} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft className="size-4" aria-hidden /> Volver a la lista
      </Link>
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight" data-testid="final-name">
          {r.make ?? "—"} {r.model ?? ""} {r.trim ?? "(sin versión)"} {r.model_year ?? ""}
        </h1>
        <p className="text-sm text-muted-foreground">
          {catalogs.country?.[r.country_code] ?? r.country_code} · {formatMoney(r.price, r.currency)} ·{" "}
          {formatInt(r.mileage_km)} km
          {r.source_url && (
            <>
              {" · "}
              <a href={r.source_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 underline">
                ver en {r.source_site} <ExternalLink className="size-3" aria-hidden />
              </a>
            </>
          )}
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>En la base</CardTitle>
        </CardHeader>
        <CardContent>
          <KeyValues
            items={[
              ["Estado", <span key="s" data-testid="final-status">{reasonLabel(r.variant_id ? null : r.unassigned_reason)}</span>],
              ["Generación", r.generation_id ? link(`/base/generacion/${r.generation_id}`, r.generation_name ?? "Ver") : "—"],
              ["Tren motriz", r.powertrain_id ? link(`/base/tren-motriz/${r.powertrain_id}`, "Ver tren motriz") : "—"],
              ["Variante", r.variant_id ? link(`/base/variante/${r.variant_id}`, "Ver variante") : "—"],
              ["Publicado", formatDate(r.listed_at)],
              ["Ficha calculada", formatDate(r.built_at)],
            ]}
          />
          <p className="mt-3 text-xs text-muted-foreground">
            Gana el valor de la base; el anuncio solo llena lo que falta. Las notas de evolución aplican desde su año. El
            origen de cada valor se ve en la generación, el tren motriz o la variante.
          </p>
        </CardContent>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        {FINAL_SHEET_GROUPS.map(([title, fields]) => (
          <Card key={title}>
            <CardHeader>
              <CardTitle>{title}</CardTitle>
            </CardHeader>
            <CardContent>
              <KeyValues items={fields.map((f) => [fieldLabel(f), <span key={f} data-field={f}>{formatValue(f, values[f], catalogs)}</span>])} />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
