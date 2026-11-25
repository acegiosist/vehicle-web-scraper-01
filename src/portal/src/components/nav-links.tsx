"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "cn";

const LINKS = [
  { href: "/", label: "Estado" },
  { href: "/revision", label: "Revisión" },
  { href: "/base", label: "Base" },
  { href: "/fichas", label: "Fichas" },
  { href: "/captura", label: "Captura" },
  { href: "/fuentes", label: "Fuentes" },
  { href: "/catalogos", label: "Catálogos" },
  { href: "/acciones", label: "Acciones" },
  { href: "/usuarios", label: "Usuarios" },
] as const;

/** The menu, highlighting the current section. The pathname is request data, so the header
 *  renders it inside <Suspense> with <NavLinksView /> (no highlight) as the fallback. */
export function NavLinks() {
  const pathname = usePathname();
  return <NavLinksView pathname={pathname} />;
}

export function NavLinksView({ pathname }: { pathname?: string }) {
  return (
    <nav aria-label="Principal" className="flex flex-wrap items-center gap-1 text-sm">
      {LINKS.map((l) => {
        const active =
          !!pathname && (l.href === "/" ? pathname === "/" : pathname === l.href || pathname.startsWith(`${l.href}/`));
        return (
          <Link
            key={l.href}
            href={l.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "rounded-md px-2.5 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
              active && "bg-muted font-medium text-foreground",
            )}
          >
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
