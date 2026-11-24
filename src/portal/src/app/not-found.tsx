import Link from "next/link";

export default function NotFound() {
  return (
    <main className="space-y-2">
      <h1 className="text-xl font-semibold">No encontrado</h1>
      <p className="text-sm text-muted-foreground">La página, el caso o la ficha no existe, o el enlace está mal.</p>
      <Link href="/" className="text-sm underline">
        Volver al inicio
      </Link>
    </main>
  );
}
