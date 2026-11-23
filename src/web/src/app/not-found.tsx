import Link from "next/link";

export default function NotFound() {
  return (
    <main className="space-y-2">
      <h1 className="text-xl font-semibold">No encontrado</h1>
      <p className="text-sm text-muted-foreground">El caso o la variante no existe, o el enlace está mal.</p>
      <Link href="/cola" className="text-sm underline">
        Volver a la cola
      </Link>
    </main>
  );
}
