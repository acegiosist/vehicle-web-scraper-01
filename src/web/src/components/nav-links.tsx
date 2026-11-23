"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "cn";

const LINKS = [
  { href: "/cola", label: "Cola" },
  { href: "/base", label: "Base" },
  { href: "/decisiones", label: "Decisiones" },
  { href: "/tareas", label: "Tareas" },
  { href: "/estado", label: "Estado" },
] as const;

/** The menu, highlighting the current section. The pathname is request data, so the header
 *  renders it inside <Suspense> with <NavLinksView /> (no highlight) as the fallback. */
export function NavLinks() {
  const pathname = usePathname();
  return <NavLinksView pathname={pathname} />;
}

export function NavLinksView({ pathname }: { pathname?: string }) {
  return (
    <nav aria-label="Principal" className="flex items-center gap-1 text-sm">
      {LINKS.map((l) => {
        const active = !!pathname && (pathname === l.href || pathname.startsWith(`${l.href}/`));
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
