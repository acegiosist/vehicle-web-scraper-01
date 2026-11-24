"""Catalogs, source sites and the staging area for imported listings.

* ``kb``: closed lists (country, vehicle class, fuel, transmission, drivetrain, body style,
  segment, headlight type, brake type) and ``source_site`` (country and data-use flags per
  scraped site).
* ``staging``: ``import_batch`` (one row per ``kb import``) and ``raw_listing`` (each scraped
  listing as read from vehicles.sqlite, one version per change; the current one has
  ``valid_to IS NULL``).

The seed values are frozen here on purpose: a migration must not change when the code does.
``tests/test_kb_catalogs.py`` checks that fuel/transmission/drivetrain/body codes still match
``models.py``; when they don't, add a new migration.

Revision ID: 0001_catalogs_staging
Revises:
"""
from __future__ import annotations

from alembic import op

revision = "0001_catalogs_staging"
down_revision = None
branch_labels = None
depends_on = None

# (code, name_es, name_en). Codes for fuel/transmission/drivetrain/body are the values the
# scraper writes (models.py), so imported listings map to them without translation.
VEHICLE_CLASSES = [
    ("car", "Automóvil", "Car"),
    ("motorcycle", "Motocicleta", "Motorcycle"),
]
FUEL_TYPES = [
    ("Gasoline", "Gasolina", "Gasoline"),
    ("Diesel", "Diésel", "Diesel"),
    ("Hybrid", "Híbrido", "Hybrid"),
    ("EV", "Eléctrico", "Electric"),
    ("CNG", "Gas natural (GNV)", "Compressed natural gas"),
]
TRANSMISSION_TYPES = [
    ("Manual", "Manual", "Manual"),
    ("Automatic", "Automática", "Automatic"),
    ("CVT", "Variable continua (CVT)", "Continuously variable (CVT)"),
    ("DCT", "Doble embrague (DCT)", "Dual-clutch (DCT)"),
]
DRIVETRAINS = [
    ("FWD", "Delantera", "Front-wheel drive"),
    ("RWD", "Trasera", "Rear-wheel drive"),
    ("AWD", "Integral (AWD)", "All-wheel drive"),
    ("4WD", "4x4", "Four-wheel drive"),
    ("2WD", "4x2 (eje sin precisar)", "Two-wheel drive (axle not stated)"),
]
BODY_STYLES = [
    ("SUV", "SUV", "SUV"),
    ("Sedan", "Sedán", "Sedan"),
    ("Hatchback", "Hatchback", "Hatchback"),
    ("Pickup", "Pickup", "Pickup"),
    ("Coupe", "Coupé", "Coupe"),
    ("Convertible", "Convertible", "Convertible"),
    ("Wagon", "Station wagon", "Wagon"),
    ("Minivan", "Minivan", "Minivan"),
    ("Van", "Van", "Van"),
    ("Truck", "Camión", "Truck"),
    ("Motorcycle", "Motocicleta", "Motorcycle"),
]
HEADLIGHT_TYPES = [
    ("Halogen", "Halógeno", "Halogen"),
    ("Xenon", "Xenón", "Xenon"),
    ("LED", "LED", "LED"),
    ("MatrixLED", "LED matricial", "Matrix LED"),
]
BRAKE_TYPES = [
    ("Disc", "Disco", "Disc"),
    ("Drum", "Tambor", "Drum"),
]
SEGMENTS: list[tuple[str, str, str]] = []   # values added in 0002_segments

CATALOGS = {
    "vehicle_class": ("Clase de vehículo dentro del alcance de la base", VEHICLE_CLASSES),
    "fuel_type": ("Combustible", FUEL_TYPES),
    "transmission_type": ("Tipo de transmisión", TRANSMISSION_TYPES),
    "drivetrain": ("Tracción", DRIVETRAINS),
    "body_style": ("Carrocería", BODY_STYLES),
    "segment": ("Segmento de mercado", SEGMENTS),
    "headlight_type": ("Tipo de faros", HEADLIGHT_TYPES),
    "brake_type": ("Tipo de frenos (delanteros o traseros)", BRAKE_TYPES),
}

# (code, name_es, name_en, currency)
COUNTRIES = [
    ("CO", "Colombia", "Colombia", "COP"),
    ("US", "Estados Unidos", "United States", "USD"),
    ("IN", "India", "India", "INR"),
    ("GT", "Guatemala", "Guatemala", "GTQ"),
]

# (code, name, country, base_url, notes). Every site starts with ai_allowed and
# training_allowed false: switch them on only after reviewing each site's terms.
SOURCE_SITES = [
    ("carroya", "CarroYa", "CO", "https://www.carroya.com", None),
    ("cofino", "Cofiño Usados", "GT", "https://www.cofinousados.com",
     "robots.txt: ai-train=no, use=reference. Never send its text to an AI or use it for training."),
    ("cars24", "CARS24", "IN", "https://www.cars24.com", None),
    ("driveway", "Driveway", "US", "https://www.driveway.com", None),
    ("truecar", "TrueCar", "US", "https://www.truecar.com", None),
]


def _lit(value) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _values(rows) -> str:
    return ",\n    ".join("(" + ", ".join(_lit(v) for v in row) + ")" for row in rows)


def upgrade() -> None:
    op.execute("CREATE SCHEMA kb")
    op.execute("CREATE SCHEMA staging")
    op.execute("COMMENT ON SCHEMA kb IS 'Base de conocimiento de vehículos: catálogos, sitios y niveles'")
    op.execute("COMMENT ON SCHEMA staging IS 'Anuncios importados tal como los guardó el scraper, versionados'")

    op.execute("""
CREATE TABLE kb.country (
    code text PRIMARY KEY CHECK (code ~ '^[A-Z]{2}$'),
    name_es text NOT NULL,
    name_en text NOT NULL,
    currency_code text NOT NULL CHECK (currency_code ~ '^[A-Z]{3}$'),
    active boolean NOT NULL DEFAULT true
)""")
    op.execute("COMMENT ON TABLE kb.country IS 'País (mercado) de una variante comercial, ISO 3166-1 alfa-2'")
    op.execute(f"INSERT INTO kb.country (code, name_es, name_en, currency_code) VALUES\n    {_values(COUNTRIES)}")

    for table, (comment, rows) in CATALOGS.items():
        op.execute(f"""
CREATE TABLE kb.{table} (
    code text PRIMARY KEY CHECK (code ~ '^[A-Za-z0-9]+$'),
    name_es text NOT NULL,
    name_en text NOT NULL,
    sort_order smallint NOT NULL DEFAULT 0,
    active boolean NOT NULL DEFAULT true
)""")
        op.execute(f"COMMENT ON TABLE kb.{table} IS {_lit('Catálogo: ' + comment)}")
        if rows:
            ordered = [(code, es, en, i + 1) for i, (code, es, en) in enumerate(rows)]
            op.execute(f"INSERT INTO kb.{table} (code, name_es, name_en, sort_order) VALUES\n    "
                       f"{_values(ordered)}")

    op.execute("""
CREATE TABLE kb.source_site (
    code text PRIMARY KEY CHECK (code ~ '^[a-z0-9_]+$'),
    name text NOT NULL,
    country_code text NOT NULL REFERENCES kb.country(code),
    base_url text,
    ai_allowed boolean NOT NULL DEFAULT false,
    training_allowed boolean NOT NULL DEFAULT false,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("COMMENT ON TABLE kb.source_site IS 'Sitio scrapeado: país y si su contenido puede ir a una IA o a entrenamiento'")
    op.execute("COMMENT ON COLUMN kb.source_site.ai_allowed IS 'Su texto puede enviarse a un modelo de IA (p. ej. Claude)'")
    op.execute("COMMENT ON COLUMN kb.source_site.training_allowed IS 'Sus datos pueden usarse para entrenar modelos'")
    op.execute(f"INSERT INTO kb.source_site (code, name, country_code, base_url, notes) VALUES\n    "
               f"{_values(SOURCE_SITES)}")

    op.execute("""
CREATE TABLE staging.import_batch (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_file text NOT NULL,
    file_sha256 text NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
    rows_read integer NOT NULL DEFAULT 0,
    new_listings integer NOT NULL DEFAULT 0,
    new_versions integer NOT NULL DEFAULT 0,
    unchanged integer NOT NULL DEFAULT 0,
    skipped jsonb NOT NULL DEFAULT '{}'::jsonb,
    imported_at timestamptz NOT NULL DEFAULT now()
)""")
    op.execute("CREATE INDEX import_batch_sha ON staging.import_batch (file_sha256)")
    op.execute("COMMENT ON COLUMN staging.import_batch.skipped IS "
               "'Filas no importadas por sitio no registrado en kb.source_site: {sitio: cantidad}'")

    op.execute("""
CREATE TABLE staging.raw_listing (
    source_site text NOT NULL REFERENCES kb.source_site(code),
    listing_id text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    row_hash text NOT NULL CHECK (row_hash ~ '^[0-9a-f]{64}$'),
    data jsonb NOT NULL,
    listed_at timestamptz,
    scraped_at timestamptz,
    import_batch_id bigint NOT NULL REFERENCES staging.import_batch(id),
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    PRIMARY KEY (source_site, listing_id, version),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
)""")
    op.execute("CREATE UNIQUE INDEX raw_listing_current ON staging.raw_listing (source_site, listing_id) "
               "WHERE valid_to IS NULL")
    op.execute("COMMENT ON TABLE staging.raw_listing IS "
               "'Fila de vehicles.sqlite tal cual (data), una versión nueva solo cuando cambia row_hash'")
    op.execute("COMMENT ON COLUMN staging.raw_listing.row_hash IS "
               "'sha256 de la fila sin scraped_at: volver a scrapear sin cambios no crea versión'")

    op.execute("""
CREATE VIEW staging.current_listing AS
SELECT r.source_site, s.country_code, r.listing_id, r.version, r.data, r.listed_at, r.scraped_at,
       r.valid_from, r.import_batch_id
FROM staging.raw_listing r
JOIN kb.source_site s ON s.code = r.source_site
WHERE r.valid_to IS NULL""")


def downgrade() -> None:
    op.execute("DROP SCHEMA staging CASCADE")
    op.execute("DROP SCHEMA kb CASCADE")
