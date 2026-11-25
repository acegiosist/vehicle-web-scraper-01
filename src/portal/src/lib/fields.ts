/**
 * Labels and units of the fields the portal shows, by level column name (kb/levels.py) and
 * listing field name (models.py). tests/test_portal_sync.py checks every level column has one.
 */
export interface FieldInfo {
  label: string;
  unit?: string;
  /** catalog table whose name_es replaces the code when shown */
  catalog?: string;
  kind?: "bool" | "number" | "text" | "code";
}

const b = (label: string): FieldInfo => ({ label, kind: "bool" });
const n = (label: string, unit?: string): FieldInfo => ({ label, unit, kind: "number" });
const c = (label: string, catalog: string): FieldInfo => ({ label, catalog, kind: "code" });

export const FIELDS: Record<string, FieldInfo> = {
  // level 1
  segment_code: c("Segmento", "segment"),
  body_style_code: c("Carrocería", "body_style"),
  length_mm: n("Largo", "mm"),
  width_mm: n("Ancho", "mm"),
  height_mm: n("Alto", "mm"),
  wheelbase_mm: n("Distancia entre ejes", "mm"),
  doors: n("Puertas"),
  seats: n("Asientos"),
  cargo_capacity_l: n("Maletero", "L"),
  fuel_tank_capacity_l: n("Tanque", "L"),
  year_from: n("Año inicio"),
  year_to: n("Año fin"),
  // level 2
  engine_code: { label: "Código de motor", kind: "text" },
  engine_name: { label: "Motor", kind: "text" },
  engine_displacement_l: n("Cilindraje", "L"),
  engine_cylinders: n("Cilindros"),
  fuel_type_code: c("Combustible", "fuel_type"),
  horsepower_hp: n("Potencia", "hp"),
  torque_nm: n("Torque", "Nm"),
  transmission_type_code: c("Transmisión", "transmission_type"),
  gears: n("Velocidades"),
  drivetrain_code: c("Tracción", "drivetrain"),
  fuel_economy_kml: n("Consumo", "km/L"),
  ev_range_km: n("Autonomía eléctrica", "km"),
  ev_charging_speed_kw: n("Carga rápida", "kW"),
  // level 3
  country_of_manufacture: { label: "País de fabricación", kind: "text" },
  airbags_count: n("Bolsas de aire"),
  screen_size_in: n("Pantalla", "in"),
  wheel_size_in: n("Rines", "in"),
  tire_size: { label: "Llantas", kind: "text" },
  headlight_type_code: c("Faros", "headlight_type"),
  brake_front_code: c("Frenos delanteros", "brake_type"),
  brake_rear_code: c("Frenos traseros", "brake_type"),
  wireless_charger: b("Cargador inalámbrico"),
  abs: b("ABS"),
  stability_control: b("Control de estabilidad"),
  traction_control: b("Control de tracción"),
  adaptive_cruise_control: b("Crucero adaptativo"),
  lane_assist: b("Asistente de carril"),
  automatic_emergency_braking: b("Frenado autónomo de emergencia"),
  blind_spot_monitoring: b("Monitor de punto ciego"),
  led_lights: b("Luces LED"),
  fog_lights: b("Exploradoras"),
  sunroof: b("Techo corredizo"),
  panoramic_roof: b("Techo panorámico"),
  roof_rails: b("Barras de techo"),
  alloy_wheels: b("Rines de aleación"),
  leather_seats: b("Cojinería en cuero"),
  power_seats: b("Asientos eléctricos"),
  heated_seats: b("Asientos calefactados"),
  cooled_seats: b("Asientos ventilados"),
  memory_seats: b("Asientos con memoria"),
  climate_control: b("Climatizador"),
  dual_zone_ac: b("Aire bizona"),
  keyless_entry: b("Acceso sin llave"),
  push_button_start: b("Encendido por botón"),
  bluetooth: b("Bluetooth"),
  apple_carplay: b("Apple CarPlay"),
  android_auto: b("Android Auto"),
  navigation: b("Navegador"),
  reverse_camera: b("Cámara de reversa"),
  camera_360: b("Cámara 360°"),
  front_camera: b("Cámara frontal"),
  parking_sensors: b("Sensores de parqueo"),
  automatic_parking: b("Parqueo automático"),
  alarm: b("Alarma"),
  immobilizer: b("Inmovilizador"),
  tow_package: b("Enganche de remolque"),
  bed_liner: b("Protector de platón"),
  // listing-level names used by review cases (clean_listing columns / schema fields)
  body_style: c("Carrocería", "body_style"),
  fuel_type: c("Combustible", "fuel_type"),
  transmission_type: c("Transmisión", "transmission_type"),
  drivetrain: c("Tracción", "drivetrain"),
  // and the final record's (kb.final_listing, schema names)
  headlight_type: c("Faros", "headlight_type"),
  brake_front: c("Frenos delanteros", "brake_type"),
  brake_rear: c("Frenos traseros", "brake_type"),
};

/** Level columns grouped for the sheets, in display order. */
export const GENERATION_SHEET = [
  "segment_code",
  "length_mm",
  "width_mm",
  "height_mm",
  "wheelbase_mm",
  "doors",
  "seats",
  "cargo_capacity_l",
  "fuel_tank_capacity_l",
] as const;
export const POWERTRAIN_SHEET = [
  "engine_code",
  "engine_name",
  "engine_displacement_l",
  "engine_cylinders",
  "fuel_type_code",
  "horsepower_hp",
  "torque_nm",
  "transmission_type_code",
  "gears",
  "drivetrain_code",
  "fuel_economy_kml",
  "ev_range_km",
  "ev_charging_speed_kw",
] as const;
export const VARIANT_SHEET_GROUPS: [string, string[]][] = [
  ["General", ["country_of_manufacture", "seats", "wheel_size_in", "tire_size", "headlight_type_code", "brake_front_code", "brake_rear_code"]],
  ["Seguridad", ["abs", "airbags_count", "stability_control", "traction_control"]],
  ["Asistencias (ADAS)", ["adaptive_cruise_control", "lane_assist", "automatic_emergency_braking", "blind_spot_monitoring"]],
  ["Exterior", ["led_lights", "fog_lights", "sunroof", "panoramic_roof", "roof_rails", "alloy_wheels"]],
  ["Interior y confort", ["leather_seats", "power_seats", "heated_seats", "cooled_seats", "memory_seats", "climate_control", "dual_zone_ac", "keyless_entry", "push_button_start"]],
  ["Conectividad", ["screen_size_in", "bluetooth", "apple_carplay", "android_auto", "navigation", "wireless_charger"]],
  ["Cámaras y parqueo", ["reverse_camera", "camera_360", "front_camera", "parking_sensors", "automatic_parking"]],
  ["Seguridad del vehículo y utilidad", ["alarm", "immobilizer", "tow_package", "bed_liner"]],
];

export function fieldLabel(field: string | null | undefined): string {
  if (!field) return "—";
  return FIELDS[field]?.label ?? field;
}

export type Catalogs = Record<string, Record<string, string>>;

/** A stored value as text: sí/no, catalog names instead of codes, units. */
export function formatValue(field: string | null | undefined, value: unknown, catalogs?: Catalogs): string {
  if (value === null || value === undefined || value === "") return "—";
  const info = field ? FIELDS[field] : undefined;
  if (typeof value === "boolean") return value ? "Sí" : "No";
  if (info?.catalog && typeof value === "string") return catalogs?.[info.catalog]?.[value] ?? value;
  if (typeof value === "number") {
    const text = new Intl.NumberFormat("es", { maximumFractionDigits: 3 }).format(value);
    return info?.unit ? `${text} ${info.unit}` : text;
  }
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${formatValue(undefined, v, catalogs)}`)
      .join("; ");
  }
  return String(value);
}

export const SOURCE_LABELS: Record<string, string> = {
  manual: "Manual",
  external: "Fuente externa",
  listings: "Anuncios",
  ai: "IA",
};
/** kb/sources CAPTURE: what the capture template saved, first among external values. */
export const CAPTURE_SOURCE = "captura";

/** "Manual", "Anuncios", "Fuente externa · Captura", "Fuente externa · fueleconomy.gov (EPA / DOE)". */
export function sourceLabel(kind: string, code?: string | null, name?: string | null): string {
  const label = SOURCE_LABELS[kind] ?? kind;
  if (kind !== "external" || !code) return label;
  return `${label} · ${code === CAPTURE_SOURCE ? "Captura" : (name ?? code)}`;
}

/** kb/levels.py SOURCE_RANK: the published value is the best accepted evidence. */
export const SOURCE_RANK: Record<string, number> = { manual: 0, external: 1, listings: 2, ai: 3 };
