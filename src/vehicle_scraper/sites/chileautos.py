"""Chileautos (Chile) — https://www.chileautos.cl

Status Nov 2026: BLOCKED BY SITE. Every page is protected by DataDome
(geo.captcha-delivery.com). This scraper does not bypass CAPTCHAs: when the wall
is served it raises BlockedError and the run skips the site.

Chileautos belongs to carsales.com; ask them for a data feed/partner API.
The parsing logic below (JSON-LD + spec tables) is ready for when access is granted
(e.g. via an allow-listed IP or an official feed export saved as HTML).

Known URL patterns:
  search:  https://www.chileautos.cl/vehiculos/?offset=0  (12 per page)
  detail:  https://www.chileautos.cl/vehiculos/detalles/<make>-<model>/<ID>  (ID like GI-AD-959505)
"""
from __future__ import annotations

from .base import register
from .html_site import HtmlSiteScraper


@register
class ChileautosScraper(HtmlSiteScraper):
    name = "chileautos"
    base_url = "https://www.chileautos.cl"
    country = "CL"
    currency = "CLP"
    status = "blocked-by-site"
    notes = "DataDome CAPTCHA on all pages; request a data feed from carsales.com."
    page_url_template = "https://www.chileautos.cl/vehiculos/?offset={offset}"
    first_page = 1
    link_pattern = r"/vehiculos/detalles/[^/]+/[A-Z]{2}-AD-\d+"
    id_pattern = r"/([A-Z]{2}-AD-\d+)"
    wait_selector = "h1"
