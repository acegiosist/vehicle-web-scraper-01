"""Vehicle knowledge base on PostgreSQL (database ``omnibase``).

Two schemas:

* ``staging``: the scraper's listings exactly as read from ``vehicles.sqlite``, one version per
  change (``importer.py``).
* ``kb``: closed catalogs (fuel, transmission, drivetrain, body style, ...), source sites and,
  in later migrations, the three levels: generation -> powertrain -> commercial variant per
  country.

The database itself is created by its owner; this package only creates objects through the
Alembic migrations in ``migrations/`` (``vehicle_scraper kb migrate``).
"""
