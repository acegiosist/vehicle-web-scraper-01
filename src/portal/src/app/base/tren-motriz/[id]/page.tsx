import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import { RecentActions } from "@/components/edit/recent-actions";
import { Sheet } from "@/components/knowledge/sheet";
import { NoAccess } from "@/components/no-access";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { userWithRole } from "@/lib/auth/current-user";
import { hasRole } from "@/lib/auth/roles";
import { POWERTRAIN_SHEET } from "@/lib/fields";
import { formatInt } from "@/lib/format";
import { recentActionsFor } from "@/lib/queries/actions";
import { getCatalogs, powertrain } from "@/lib/queries/knowledge";

export const metadata: Metadata = { title: "Tren motriz" };

export default function PowertrainPage(props: PageProps<"/base/tren-motriz/[id]">) {
  return (
    <main className="space-y-6">
      <Suspense fallback={<Skeleton className="h-96" />}>
        <PowertrainView {...props} />
      </Suspense>
    </main>
  );
}

async function PowertrainView({ params }: PageProps<"/base/tren-motriz/[id]">) {
  const user = await userWithRole("lector");
  if (!user) return <NoAccess needed="lector" />;
  const { id } = await params;
  const [found, catalogs, actions] = await Promise.all([
    powertrain(id),
    getCatalogs(),
    recentActionsFor([{ entity_type: "powertrain", entity_id: Number(id) }]),
  ]);
  if (!found) notFound();
  const { p, evidence } = found;
  const editor = hasRole(user.role, "editor");
  return (
    <div className="space-y-6">
      <Link href={`/base/generacion/${p.generation_id}`} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline">
        <ArrowLeft className="size-4" aria-hidden /> {p.make_name} {p.generation_name}
      </Link>
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Tren motriz #{String(p.id)}</h1>
        <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <Badge variant="outline">{p.status}</Badge>
          {formatInt(p.listings)} anuncios · creado con: <code>{p.match_key}</code>
        </p>
      </div>
      <RecentActions actions={actions} />
      <Card>
        <CardHeader>
          <CardTitle>Nivel 2 · Mecánica</CardTitle>
          <CardDescription>
            Cilindraje, combustible, transmisión y tracción identifican el tren motriz: se corrigen en el sitio. El resto
            se publica desde la mejor fuente.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Sheet
            fields={POWERTRAIN_SHEET}
            values={p as Record<string, unknown>}
            evidence={evidence}
            catalogs={catalogs}
            edit={editor ? { entityType: "powertrain", entityId: id } : undefined}
          />
        </CardContent>
      </Card>
    </div>
  );
}
