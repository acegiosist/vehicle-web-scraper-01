/**
 * kb.final_listing on the portal (/fichas): filters, links, field groups and the unassigned
 * reasons. tests/test_portal_sync.py checks FINAL_SHEET_GROUPS against kb/final.py SOURCES
 * and UNASSIGNED_REASONS against the listing_level check constraint.
 */
import { DEFAULT_PAGE_SIZE, parsePaging } from "@/lib/paging";

/** kb.listing_level.unassigned_reason, in Spanish. */
export const UNASSIGNED_REASONS: Record<string, string> = {
  model_not_accepted: "Modelo no aceptado",
  ambiguous_body: "Carrocería ambigua",
  no_generation_for_year: "Sin generación para el año",
  ambiguous_powertrain: "Tren motriz ambiguo",
  powertrain_rejected: "Tren motriz rechazado",
  variant_rejected: "Variante rechazada",
};

export function reasonLabel(reason: string | null | undefined): string {
  if (!reason) return "Asignado";
  return UNASSIGNED_REASONS[reason] ?? reason;
}

/**
 * The record's columns by group, in display order (final_listing names: the schema's, so
 * `fuel_type` rather than the level's `fuel_type_code`). Identity, price and links are shown
 * in the header instead.
 */
export const FINAL_SHEET_GROUPS: [string, string[]][] = [
  ["Generación", ["body_style", "segment_code", "length_mm", "width_mm", "height_mm", "wheelbase_mm", "doors", "seats", "cargo_capacity_l", "fuel_tank_capacity_l"]],
  ["Tren motriz", ["engine_code", "engine_name", "engine_displacement_l", "engine_cylinders", "fuel_type", "horsepower_hp", "torque_nm", "transmission_type", "gears", "drivetrain", "fuel_economy_kml", "ev_range_km", "ev_charging_speed_kw"]],
  ["General", ["country_of_manufacture", "wheel_size_in", "tire_size", "headlight_type", "brake_front", "brake_rear"]],
  ["Seguridad", ["abs", "airbags_count", "stability_control", "traction_control"]],
  ["Asistencias (ADAS)", ["adaptive_cruise_control", "lane_assist", "automatic_emergency_braking", "blind_spot_monitoring"]],
  ["Exterior", ["led_lights", "fog_lights", "sunroof", "panoramic_roof", "roof_rails", "alloy_wheels"]],
  ["Interior y confort", ["leather_seats", "power_seats", "heated_seats", "cooled_seats", "memory_seats", "climate_control", "dual_zone_ac", "keyless_entry", "push_button_start"]],
  ["Conectividad", ["screen_size_in", "bluetooth", "apple_carplay", "android_auto", "navigation", "wireless_charger"]],
  ["Cámaras y parqueo", ["reverse_camera", "camera_360", "front_camera", "parking_sensors", "automatic_parking"]],
  ["Seguridad del vehículo y utilidad", ["alarm", "immobilizer", "tow_package", "bed_liner"]],
];

/** "Estado" filter: every record, the assigned ones, the unassigned ones, or one reason. */
export type FinalStatus = "asignados" | "sin-asignar" | keyof typeof UNASSIGNED_REASONS;

export interface FinalFilters {
  country?: string;
  status?: FinalStatus;
  year?: number;
  q?: string;
  page: number;
  size: number;
}

type SearchParams = Record<string, string | string[] | undefined>;

const YEAR_MIN = 1990;
const YEAR_MAX = 2100;

/** `?pais=&estado=&anio=&q=&pagina=&por=`; anything invalid is ignored. */
export function parseFinalFilters(sp: SearchParams): FinalFilters {
  const one = (k: string) => (Array.isArray(sp[k]) ? sp[k][0] : sp[k]);
  const country = (one("pais") ?? "").trim().toUpperCase();
  const status = one("estado") ?? "";
  const year = Number.parseInt(one("anio") ?? "", 10);
  const q = (one("q") ?? "").trim().slice(0, 80);
  return {
    country: /^[A-Z]{2}$/.test(country) ? country : undefined,
    status: status === "asignados" || status === "sin-asignar" || Object.hasOwn(UNASSIGNED_REASONS, status)
      ? (status as FinalStatus) : undefined,
    year: year >= YEAR_MIN && year <= YEAR_MAX ? year : undefined,
    q: q || undefined,
    ...parsePaging(sp),
  };
}

export function finalListHref(f: FinalFilters, page = f.page): string {
  const p = new URLSearchParams();
  if (f.country) p.set("pais", f.country);
  if (f.status) p.set("estado", f.status);
  if (f.year) p.set("anio", String(f.year));
  if (f.q) p.set("q", f.q);
  if (f.size !== DEFAULT_PAGE_SIZE) p.set("por", String(f.size));
  if (page > 1) p.set("pagina", String(page));
  const s = p.toString();
  return s ? `/fichas?${s}` : "/fichas";
}

/** One listing's record; `back` keeps the list's filters for "Volver a la lista". */
export function finalRecordHref(site: string, listingId: string, back?: FinalFilters): string {
  const path = `/fichas/${encodeURIComponent(site)}/${encodeURIComponent(listingId)}`;
  if (!back) return path;
  const list = finalListHref(back);
  return `${path}${list.slice("/fichas".length)}`;
}
