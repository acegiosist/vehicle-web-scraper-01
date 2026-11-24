import { Suspense } from "react";
import Link from "next/link";
import { CarFront } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { getCurrentUser } from "@/lib/auth/current-user";
import { IapError } from "@/lib/auth/iap";
import { ROLE_LABEL } from "@/lib/auth/roles";

import { NavLinks, NavLinksView } from "./nav-links";

export function SiteHeader() {
  return (
    <header className="border-b bg-background/95">
      <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <CarFront className="size-5" aria-hidden />
          <span>Omnibase</span>
        </Link>
        <Suspense fallback={<NavLinksView />}>
          <NavLinks />
        </Suspense>
        <div className="ml-auto text-sm">
          <Suspense fallback={<div className="h-6 w-48" />}>
            <Who />
          </Suspense>
        </div>
      </div>
    </header>
  );
}

async function Who() {
  const user = await getCurrentUser().catch((e: unknown) => {
    if (e instanceof IapError) return null;
    throw e;
  });
  if (!user) return <span className="text-destructive">No autenticado</span>;
  return (
    <span className="flex items-center gap-2 text-muted-foreground">
      <span data-testid="current-user">{user.email}</span>
      <Badge variant={user.role ? "secondary" : "destructive"}>{user.role ? ROLE_LABEL[user.role] : "Sin acceso"}</Badge>
    </span>
  );
}
