import { Suspense } from "react";
import Link from "next/link";
import { CarFront } from "lucide-react";

import { getReviewer } from "@/lib/reviewer";

import { NavLinks, NavLinksView } from "./nav-links";
import { ReviewerForm } from "./reviewer-form";

export function SiteHeader() {
  return (
    <header className="border-b bg-background/95">
      <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
        <Link href="/cola" className="flex items-center gap-2 font-semibold">
          <CarFront className="size-5" aria-hidden />
          <span>Revisión KB</span>
        </Link>
        <Suspense fallback={<NavLinksView />}>
          <NavLinks />
        </Suspense>
        <div className="ml-auto">
          <Suspense fallback={<div className="h-8 w-48" />}>
            <Reviewer />
          </Suspense>
        </div>
      </div>
    </header>
  );
}

async function Reviewer() {
  return <ReviewerForm current={await getReviewer()} />;
}
