"""Standardized vehicle schema shared by every site scraper."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

VehicleType = Literal["SUV", "Sedan", "Pickup", "Hatchback", "Coupe", "Van", "Convertible", "Wagon", "Truck", "Minivan"]
FuelType = Literal["Gasoline", "Diesel", "Hybrid", "EV"]
TransmissionType = Literal["Manual", "Automatic", "CVT", "DCT"]
Drivetrain = Literal["FWD", "RWD", "AWD", "4WD"]

# Ordered list of the schema fields (used by CSV export and the coverage report).
IDENTITY_FIELDS = [
    "vehicle_type", "make", "model", "trim", "model_year", "body_style", "country_of_manufacture",
]
TECH_FIELDS = [
    "engine_displacement_l", "engine_cylinders", "horsepower_hp", "fuel_type", "fuel_tank_capacity_l",
    "transmission_type", "drivetrain", "seats", "doors", "cargo_capacity_l", "wheel_size_in", "tire_size",
    "fuel_economy_kml", "ev_range_km", "ev_charging_speed_kw",
]
FEATURE_FIELDS = [
    # Safety
    "abs", "airbags_count", "stability_control", "traction_control",
    # ADAS
    "adaptive_cruise_control", "lane_assist", "automatic_emergency_braking", "blind_spot_monitoring",
    # Exterior
    "led_lights", "fog_lights", "sunroof", "panoramic_roof", "roof_rails", "alloy_wheels",
    # Interior
    "leather_seats", "power_seats", "heated_seats", "cooled_seats", "memory_seats",
    # Comfort
    "climate_control", "dual_zone_ac", "keyless_entry", "push_button_start",
    # Infotainment
    "screen_size_in", "bluetooth", "apple_carplay", "android_auto", "navigation",
    # Cameras
    "reverse_camera", "camera_360", "front_camera",
    # Parking
    "parking_sensors", "automatic_parking",
    # Security
    "alarm", "immobilizer",
    # Utility
    "tow_package", "bed_liner",
]
SCHEMA_FIELDS = IDENTITY_FIELDS + TECH_FIELDS + FEATURE_FIELDS
LISTING_FIELDS = ["price", "currency", "mileage_km"]
META_FIELDS = ["source_site", "source_url", "listing_id", "scraped_at", "parse_warnings"]
ALL_FIELDS = META_FIELDS[:3] + LISTING_FIELDS + SCHEMA_FIELDS + META_FIELDS[3:]

BOOLEAN_FIELDS = [f for f in FEATURE_FIELDS if f not in ("airbags_count", "screen_size_in")]


class VehicleRecord(BaseModel):
    # --- Metadata ---
    source_site: str
    source_url: str
    listing_id: str
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    parse_warnings: list[str] = Field(default_factory=list)

    # --- Listing extras (not in the attribute list, but useful) ---
    price: Optional[float] = None
    currency: Optional[str] = None
    mileage_km: Optional[int] = None

    # --- Vehicle identity ---
    vehicle_type: Optional[VehicleType] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    model_year: Optional[int] = None
    body_style: Optional[VehicleType] = None
    country_of_manufacture: Optional[str] = None

    # --- Technical specifications ---
    engine_displacement_l: Optional[float] = None
    engine_cylinders: Optional[int] = None
    horsepower_hp: Optional[int] = None
    fuel_type: Optional[FuelType] = None
    fuel_tank_capacity_l: Optional[float] = None
    transmission_type: Optional[TransmissionType] = None
    drivetrain: Optional[Drivetrain] = None
    seats: Optional[int] = None
    doors: Optional[int] = None
    cargo_capacity_l: Optional[int] = None
    wheel_size_in: Optional[int] = None
    tire_size: Optional[str] = None
    fuel_economy_kml: Optional[float] = None
    ev_range_km: Optional[int] = None
    ev_charging_speed_kw: Optional[float] = None

    # --- Equipment & features ---
    abs: Optional[bool] = None
    airbags_count: Optional[int] = None
    stability_control: Optional[bool] = None
    traction_control: Optional[bool] = None
    adaptive_cruise_control: Optional[bool] = None
    lane_assist: Optional[bool] = None
    automatic_emergency_braking: Optional[bool] = None
    blind_spot_monitoring: Optional[bool] = None
    led_lights: Optional[bool] = None
    fog_lights: Optional[bool] = None
    sunroof: Optional[bool] = None
    panoramic_roof: Optional[bool] = None
    roof_rails: Optional[bool] = None
    alloy_wheels: Optional[bool] = None
    leather_seats: Optional[bool] = None
    power_seats: Optional[bool] = None
    heated_seats: Optional[bool] = None
    cooled_seats: Optional[bool] = None
    memory_seats: Optional[bool] = None
    climate_control: Optional[bool] = None
    dual_zone_ac: Optional[bool] = None
    keyless_entry: Optional[bool] = None
    push_button_start: Optional[bool] = None
    screen_size_in: Optional[float] = None
    bluetooth: Optional[bool] = None
    apple_carplay: Optional[bool] = None
    android_auto: Optional[bool] = None
    navigation: Optional[bool] = None
    reverse_camera: Optional[bool] = None
    camera_360: Optional[bool] = None
    front_camera: Optional[bool] = None
    parking_sensors: Optional[bool] = None
    automatic_parking: Optional[bool] = None
    alarm: Optional[bool] = None
    immobilizer: Optional[bool] = None
    tow_package: Optional[bool] = None
    bed_liner: Optional[bool] = None

    @field_validator("model_year")
    @classmethod
    def _year_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1900 <= v <= datetime.now().year + 2):
            raise ValueError(f"model_year out of range: {v}")
        return v

    def to_row(self) -> dict:
        """Flat dict in a stable column order (for CSV/SQLite)."""
        data = self.model_dump()
        row = {k: data.get(k) for k in ALL_FIELDS}
        row["scraped_at"] = self.scraped_at.isoformat()
        row["parse_warnings"] = " | ".join(self.parse_warnings)
        return row
