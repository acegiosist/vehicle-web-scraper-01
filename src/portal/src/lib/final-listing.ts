/**
 * kb.final_listing on the portal (/fichas/anuncio/...): links, field groups (shared with the
 * vehicle's identity sheet) and the unassigned reasons. tests/test_portal_sync.py checks
 * FINAL_SHEET_GROUPS against kb/final.py SOURCES (and kb/vehicle.py VALUES) and
 * UNASSIGNED_REASONS against the listing_level check constraint.
 */

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

/** One listing's final record (the vehicle's sheet is /fichas/[id], lib/vehicle-identity.ts). */
export function finalRecordHref(site: string, listingId: string): string {
  return `/fichas/anuncio/${encodeURIComponent(site)}/${encodeURIComponent(listingId)}`;
}
