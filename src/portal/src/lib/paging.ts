/** Rows per page the user can pick (multiples of 10; the default is the largest). */
export const PAGE_SIZES = [10, 20, 30, 40, 50] as const;
export const DEFAULT_PAGE_SIZE = 50;

type SearchParams = Record<string, string | string[] | undefined>;

const first = (sp: SearchParams, k: string) => (Array.isArray(sp[k]) ? sp[k][0] : sp[k]);

/** `?pagina=` and `?por=` from the url; anything invalid falls back to page 1 / the default size. */
export function parsePaging(sp: SearchParams): { page: number; size: number } {
  const page = Number.parseInt(first(sp, "pagina") ?? "1", 10);
  const size = Number.parseInt(first(sp, "por") ?? "", 10);
  return {
    page: page > 0 ? page : 1,
    size: (PAGE_SIZES as readonly number[]).includes(size) ? size : DEFAULT_PAGE_SIZE,
  };
}
