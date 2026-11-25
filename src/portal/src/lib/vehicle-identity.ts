/**
 * kb.vehicle_identity on the portal (/fichas): one identity sheet per commercial variant, with
 * the three levels' values (kb/vehicle.py). Its value columns have kb.final_listing's names, so
 * the sheet reuses FINAL_SHEET_GROUPS; tests/test_portal_sync.py checks they cover them all.
 */
import { DEFAULT_PAGE_SIZE, parsePaging } from "@/lib/paging";

/** A level's status (kb.generation / powertrain / commercial_variant), in Spanish. */
export const LEVEL_STATUS: Record<string, string> = {
  provisional: "Provisional",
  verified: "Verificada",
  rejected: "Rechazada",
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return "—";
  return LEVEL_STATUS[status] ?? status;
}

/** "2017–2022", "2017–" (still on sale or not confirmed), or "—". */
export function yearRange(from: number | null | undefined, to: number | null | undefined): string {
  if (!from && !to) return "—";
  if (from === to) return String(from);
  return `${from ?? "?"}–${to ?? ""}`;
}

/** "Estado" filter: the variant's status; "Versión": hide the variants without a known trim. */
export type IdentityStatus = "verificadas" | "provisionales";

export interface IdentityFilters {
  country?: string;
  status?: IdentityStatus;
  knownTrim: boolean;
  q?: string;
  page: number;
  size: number;
}

type SearchParams = Record<string, string | string[] | undefined>;

/** `?pais=&estado=&version=conocida&q=&pagina=&por=`; anything invalid is ignored. */
export function parseIdentityFilters(sp: SearchParams): IdentityFilters {
  const one = (k: string) => (Array.isArray(sp[k]) ? sp[k][0] : sp[k]);
  const country = (one("pais") ?? "").trim().toUpperCase();
  const status = one("estado") ?? "";
  const q = (one("q") ?? "").trim().slice(0, 80);
  return {
    country: /^[A-Z]{2}$/.test(country) ? country : undefined,
    status: status === "verificadas" || status === "provisionales" ? status : undefined,
    knownTrim: one("version") === "conocida",
    q: q || undefined,
    ...parsePaging(sp),
  };
}

function query(f: IdentityFilters, page = f.page): string {
  const p = new URLSearchParams();
  if (f.country) p.set("pais", f.country);
  if (f.status) p.set("estado", f.status);
  if (f.knownTrim) p.set("version", "conocida");
  if (f.q) p.set("q", f.q);
  if (f.size !== DEFAULT_PAGE_SIZE) p.set("por", String(f.size));
  if (page > 1) p.set("pagina", String(page));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function identityListHref(f: IdentityFilters, page = f.page): string {
  return `/fichas${query(f, page)}`;
}

/** One vehicle's sheet (by its variant id); `back` keeps the list's filters for "Fichas". */
export function identityHref(variantId: string | number, back?: IdentityFilters): string {
  return `/fichas/${variantId}${back ? query(back, back.page) : ""}`;
}
