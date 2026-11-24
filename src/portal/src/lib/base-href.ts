import { DEFAULT_PAGE_SIZE, parsePaging } from "@/lib/paging";

export interface BaseFilters {
  q?: string;
  page: number;
  size: number;
}

/** The make list's search, page and size from the url (also forwarded to a make's page). */
export function parseBaseFilters(sp: Record<string, string | string[] | undefined>): BaseFilters {
  const q = (Array.isArray(sp.q) ? sp.q[0] : sp.q)?.trim().slice(0, 60) || undefined;
  return { q, ...parsePaging(sp) };
}

/** `?q=&por=&pagina=` for the make list; empty when everything is at its default. */
export function baseQuery(f: BaseFilters): string {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  if (f.size !== DEFAULT_PAGE_SIZE) p.set("por", String(f.size));
  if (f.page > 1) p.set("pagina", String(f.page));
  const s = p.toString();
  return s ? `?${s}` : "";
}
