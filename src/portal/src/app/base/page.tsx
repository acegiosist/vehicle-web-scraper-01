import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";

import { NoAccess } from "@/components/no-access";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { userWithRole } from "@/lib/auth/current-user";
import { formatInt } from "@/lib/format";
import { makes } from "@/lib/queries/knowledge";

export const metadata: Metadata = { title: "Base" };

export default function BasePage(props: PageProps<"/base">) {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Base de conocimiento</h1>
        <p className="text-sm text-muted-foreground">Marca → modelo → generación → tren motriz → variante por país.</p>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Makes {...props} />
      </Suspense>
    </main>
  );
}

async function Makes({ searchParams }: PageProps<"/base">) {
  if (!(await userWithRole("lector"))) return <NoAccess needed="lector" />;
  const sp = await searchParams;
  const q = (Array.isArray(sp.q) ? sp.q[0] : sp.q)?.trim().slice(0, 60) || undefined;
  const rows = await makes(q);
  return (
    <div className="space-y-4">
      <form className="flex gap-2" action="/base">
        <Input name="q" defaultValue={q ?? ""} placeholder="Buscar marca…" className="w-72" />
        <Button type="submit" variant="outline">
          Buscar
        </Button>
      </form>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Marca</TableHead>
            <TableHead className="text-right">Modelos</TableHead>
            <TableHead className="text-right">Generaciones</TableHead>
            <TableHead className="text-right">Anuncios</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((m) => (
            <TableRow key={String(m.id)}>
              <TableCell>
                <Link href={`/base/marca/${m.id}`} className="font-medium underline-offset-2 hover:underline">
                  {m.name}
                </Link>
                {m.status !== "accepted" && <span className="ml-2 text-xs text-muted-foreground">(pendiente de revisión)</span>}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatInt(m.models)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatInt(m.generations)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatInt(m.listings)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
