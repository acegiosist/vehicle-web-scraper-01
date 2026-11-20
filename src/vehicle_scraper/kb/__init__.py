"""Vehicle knowledge base: make -> model -> trim -> variant, with per-field provenance.

Built in PostgreSQL from the scraped listings in ``data/vehicles.sqlite`` (read-only).
See ``python -m vehicle_scraper kb --help`` and the README's "Knowledge base" section.
"""
