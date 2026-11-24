import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";

interface Props {
  page: number;
  pageCount: number;
  href: (page: number) => string;
}

export function Pagination({ page, pageCount, href }: Props) {
  if (pageCount <= 1) return null;
  return (
    <nav aria-label="Paginación" className="flex items-center justify-end gap-2 text-sm">
      {page > 1 ? (
        <Button asChild variant="outline" size="sm">
          <Link href={href(page - 1)} rel="prev">
            <ChevronLeft aria-hidden /> Anterior
          </Link>
        </Button>
      ) : (
        <Button variant="outline" size="sm" disabled>
          <ChevronLeft aria-hidden /> Anterior
        </Button>
      )}
      <span className="tabular-nums text-muted-foreground">
        {page} / {pageCount}
      </span>
      {page < pageCount ? (
        <Button asChild variant="outline" size="sm">
          <Link href={href(page + 1)} rel="next">
            Siguiente <ChevronRight aria-hidden />
          </Link>
        </Button>
      ) : (
        <Button variant="outline" size="sm" disabled>
          Siguiente <ChevronRight aria-hidden />
        </Button>
      )}
    </nav>
  );
}
