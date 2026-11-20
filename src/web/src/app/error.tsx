"use client";

import { Button } from "@/components/ui/button";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="space-y-3">
      <h1 className="text-xl font-semibold">Algo falló</h1>
      <p className="max-w-2xl text-sm text-muted-foreground">
        No se pudo cargar la página. Si es la primera vez que lo abres, revisa que
        <code className="mx-1">REVIEW_WEB_DATABASE_URL</code> en <code>.env.local</code> apunte a la base y que la
        migración 0002 esté aplicada.
        {error.digest ? ` (referencia ${error.digest})` : ""}
      </p>
      <Button onClick={reset}>Reintentar</Button>
    </main>
  );
}
