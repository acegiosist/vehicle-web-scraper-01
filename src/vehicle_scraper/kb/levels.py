"""Which field lives on which level of the knowledge base, and how its value is published.

* Level 1, ``kb.generation`` (one per model + body style + life cycle): dimensions, segment,
  cargo, fuel tank, doors, seats.
* Level 2, ``kb.powertrain`` (per generation): engine, displacement, cylinders, fuel, power,
  torque, transmission, gears, drivetrain, fuel economy, EV range/charging.
* Level 3, ``kb.commercial_variant`` (generation + powertrain + country + trim): equipment,
  wheels, tires, headlights, brakes, country of manufacture, a seats override.

``FROM_LISTINGS`` says which of them listings can vote for (the rest come from external
sources, Claude or a person). Mechanical numbers are published from one plausible listing;
equipment needs ``EQUIP_MIN_SUPPORT`` listings agreeing at ``EQUIP_MIN_AGREEMENT``.
Migration 0006 freezes the column lists; ``tests/test_kb_levels.py`` checks they still match.
"""
from __future__ import annotations

from ..models import BOOLEAN_FIELDS, FEATURE_FIELDS

EQUIP_MIN_SUPPORT = 2
EQUIP_MIN_AGREEMENT = 0.7
MECH_DISAGREEMENT = 0.10          # values more than 10 % from the median open a case
EVOLUTION_MIN_SUPPORT = 2         # listings needed on each side of the year

# Source precedence for the published value (lower wins): manual > external > listings > ai.
SOURCE_RANK = {"manual": 0, "external": 1, "listings": 2, "ai": 3}

GENERATION_FROM_LISTINGS = ["doors", "seats", "cargo_capacity_l", "fuel_tank_capacity_l"]
POWERTRAIN_FROM_LISTINGS = ["horsepower_hp", "engine_cylinders", "fuel_economy_kml", "ev_range_km",
                            "ev_charging_speed_kw"]
VARIANT_EXTRA_FROM_LISTINGS = ["wheel_size_in", "tire_size", "country_of_manufacture"]
# Schema field -> level column when they differ (catalog-backed columns end in _code). Evidence
# is stored under the column name, so an evidence field is always a column.
COLUMN_OF = {"headlight_type": "headlight_type_code", "brake_front": "brake_front_code",
             "brake_rear": "brake_rear_code"}
LISTING_FIELD_OF = {column: f for f, column in COLUMN_OF.items()}      # column -> schema field
VARIANT_FROM_LISTINGS = [COLUMN_OF.get(f, f) for f in FEATURE_FIELDS] + VARIANT_EXTRA_FROM_LISTINGS

# Published columns per level (same names as the schema fields where one exists).
GENERATION_COLUMNS = ["segment_code", "length_mm", "width_mm", "height_mm", "wheelbase_mm",
                      *GENERATION_FROM_LISTINGS]
POWERTRAIN_COLUMNS = ["engine_code", "engine_name", "gears", "torque_nm", *POWERTRAIN_FROM_LISTINGS]
VARIANT_COLUMNS = [*VARIANT_FROM_LISTINGS, "seats"]

EQUIPMENT_FIELDS = set(VARIANT_FROM_LISTINGS)
BOOLEAN = set(BOOLEAN_FIELDS)

# Plausible ranges for numbers voted from listings (outside: ignored as a vote).
RANGES = {"doors": (2, 5), "seats": (1, 9), "cargo_capacity_l": (10, 5000), "fuel_tank_capacity_l": (3, 400),
          "horsepower_hp": (3, 2000), "engine_cylinders": (1, 16), "fuel_economy_kml": (2, 80),
          "ev_range_km": (10, 1500), "ev_charging_speed_kw": (1, 500), "wheel_size_in": (8, 30),
          "airbags_count": (0, 14), "screen_size_in": (2, 25)}
