"""CARS24 (India; also cars24.ae / cars24.com.au) — https://www.cars24.com

Status Nov 2026: UNVERIFIED. Our test request got a Cloudflare 403 page
("Attention Required!"), which can be geographic (the site targets India).
The scraper detects that wall and skips the site instead of bypassing it.

When reachable it uses the generic pipeline: JSON-LD, Next.js __NEXT_DATA__
(searched for name/value spec pairs) and HTML spec tables. Run with
USE_BROWSER=true because listing pages are rendered with JavaScript.

Detail URL pattern: /buy-used-<make>-<model>-<year>-cars-<city>-<appointmentId>/
"""
from __future__ import annotations

from .base import register
from .html_site import HtmlSiteScraper


@register
class Cars24Scraper(HtmlSiteScraper):
    name = "cars24"
    base_url = "https://www.cars24.com"
    country = "IN"
    currency = "INR"
    status = "unverified"
    notes = "Cloudflare 403 from Central America during testing; try from India or ask for a partner feed."
    start_urls = ["https://www.cars24.com/buy-used-car/"]
    page_url_template = "https://www.cars24.com/buy-used-car/?page={page}"
    first_page = 2
    link_pattern = r"/buy-used-[a-z0-9-]+-\d{6,}/?$"
    id_pattern = r"-(\d{6,})/?$"
    wait_selector = "a[href*='/buy-used-']"
