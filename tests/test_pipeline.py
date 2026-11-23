"""End-to-end: discover -> parse -> SQLite -> CSV export -> coverage, offline."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from vehicle_scraper import cli
from vehicle_scraper.http import BlockedError
from vehicle_scraper.models import VehicleRecord
from vehicle_scraper.normalize import to_datetime
from vehicle_scraper.report import write_coverage
from vehicle_scraper.sites import REGISTRY
from vehicle_scraper.sites.base import Listing
from vehicle_scraper.sites.carroya import CarroYaScraper
from vehicle_scraper.storage import Storage

from .conftest import FakeClient


def _search_fixture(tmp_path):
    page = {"count": 2, "pages": 1, "results": {"superHighlights": [
        {"id": "928d091b-9e37-4938-a3f3-a091dc538590"}, {"id": "928d091b-9e37-4938-a3f3-a091dc538590"}]}}
    p = tmp_path / "search.json"
    p.write_text(json.dumps(page))
    return p


def test_carroya_discover_dedupes(cfg, tmp_path):
    p = _search_fixture(tmp_path)
    client = FakeClient({"find-filters": str(p)})
    found = list(CarroYaScraper(cfg, client=client).discover())
    assert [l.listing_id for l in found] == ["928d091b-9e37-4938-a3f3-a091dc538590"]


def test_run_site_store_export_coverage(cfg, tmp_path, monkeypatch):
    p = _search_fixture(tmp_path)
    client = FakeClient({"find-filters": str(p), "find-vehicle-detail": "carroya_detail.json"})

    class Patched(CarroYaScraper):
        def __init__(self, c):
            super().__init__(c, client=client)

    monkeypatch.setitem(REGISTRY, "carroya", Patched)
    monkeypatch.setattr(cli, "settings", cfg)
    store = Storage(cfg.db_path)
    stats = cli.run_site("carroya", store, limit=None, refresh=False)
    assert stats["saved"] == 1 and stats["status"] == "ok"
    # second run skips stored listings (resumable)
    assert cli.run_site("carroya", store, limit=None, refresh=False)["skipped"] == 1

    assert store.export_csv(tmp_path / "out.csv") == 1
    header = (tmp_path / "out.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert header.startswith("source_site,source_url,listing_id,price")
    table = write_coverage(store.rows(), tmp_path / "coverage.csv")
    assert "horsepower_hp" in table and "100%" in table
    rows = json.loads((store.export_json(tmp_path / "o.json") and (tmp_path / "o.json").read_text()))
    assert rows[0]["abs"] is True
    store.close()


def test_blocked_site_stops_cleanly(cfg, monkeypatch):
    class Blocked(CarroYaScraper):
        def __init__(self, c):
            super().__init__(c, client=FakeClient({}))

        def discover(self, limit=None):
            raise BlockedError("DataDome CAPTCHA at https://example")
            yield Listing("x", "y")

    monkeypatch.setitem(REGISTRY, "blocked", Blocked)
    monkeypatch.setattr(cli, "settings", cfg)
    store = Storage(cfg.db_path)
    stats = cli.run_site("blocked", store, None, False)
    assert stats["status"].startswith("blocked")
    store.close()



NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)


def _ago(days):
    return NOW - timedelta(days=days)


class _DatedScraper(CarroYaScraper):
    """Listing dates known at discovery (like a sitemap <lastmod>), except 'p' (date found only
    on the page: 3000 days old) and 'n' (no date anywhere)."""
    LISTINGS = [("a", 10), ("b", 2500), ("c", 400), ("p", None), ("n", None), ("d", 1)]
    fetched: list = []

    def __init__(self, c):
        super().__init__(c, client=FakeClient({}))

    def discover(self, limit=None):
        for i, (lid, days) in enumerate(self.LISTINGS):
            if limit is not None and i >= limit:
                return
            yield Listing(lid, f"https://x/{lid}", listed_at=None if days is None else _ago(days))

    def parse(self, listing):
        self.fetched.append(listing.listing_id)
        if listing.listing_id == "p":
            listing.listed_at = _ago(3000)
        return VehicleRecord(source_site="dated", source_url=listing.url, listing_id=listing.listing_id)


@pytest.fixture
def dated(cfg, monkeypatch):
    monkeypatch.setitem(REGISTRY, "dated", _DatedScraper)
    monkeypatch.setattr(cli, "settings", cfg)
    monkeypatch.setattr(_DatedScraper, "fetched", [])
    store = Storage(cfg.db_path)
    yield store
    store.close()


def test_max_age_filters_on_listing_date(dated):
    stats = cli.run_site("dated", dated, limit=None, refresh=False, listed_since=NOW - cli.parse_max_age("5"))
    assert {r["listing_id"] for r in dated.rows()} == {"a", "c", "d"}
    assert stats["saved"] == 3 and stats["too_old"] == 2 and stats["no_date"] == 1
    assert "b" not in _DatedScraper.fetched            # known-old at discovery: never fetched


def test_max_age_cutoff_is_passed_to_the_scraper(dated, monkeypatch):
    seen = []
    orig = _DatedScraper.discover
    monkeypatch.setattr(_DatedScraper, "discover", lambda self, limit=None: (seen.append(self.listed_since),
                                                                             orig(self, limit))[1])
    since = NOW - cli.parse_max_age("5")
    cli.run_site("dated", dated, limit=None, refresh=False, listed_since=since)
    assert seen == [since]                             # newest-first scrapers may stop paging there


def test_max_age_limit_counts_only_recent_listings(dated):
    # a plain --limit 2 would stop after a, b; with the filter it keeps going until 2 pass
    stats = cli.run_site("dated", dated, limit=2, refresh=False, listed_since=NOW - cli.parse_max_age("1y"))
    # b, c are known-old (never fetched); p, n had to be fetched to learn they don't qualify
    assert stats["saved"] == 2 and _DatedScraper.fetched == ["a", "p", "n", "d"]
    assert {r["listing_id"] for r in dated.rows()} == {"a", "d"}


@pytest.mark.parametrize("text,days", [("5", 1825), ("5y", 1825), ("6m", 180), ("2w", 14), ("30D", 30)])
def test_parse_max_age(text, days):
    assert cli.parse_max_age(text) == timedelta(days=days)


@pytest.mark.parametrize("bad", ["", "-1", "5 years", "1.5y"])
def test_parse_max_age_rejects(bad):
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_max_age(bad)


def test_sitemap_lastmod_becomes_listed_at(cfg, tmp_path):
    from vehicle_scraper.sites.cars24 import Cars24Scraper
    sm = tmp_path / "sitemap.xml"
    sm.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.cars24.com/buy-used-honda-amaze-2013-cars-pune-11/</loc><lastmod>2026-09-19T05:00:00.000Z</lastmod></url>
  <url><loc>https://www.cars24.com/buy-used-kia-seltos-2022-cars-pune-22/</loc></url>
  <url><loc>https://www.cars24.com/news/some-news-2026/</loc><lastmod>2026-11-01</lastmod></url>
</urlset>""")
    got = list(Cars24Scraper(cfg, client=FakeClient({"sitemap.xml": str(sm)})).discover())
    assert [(l.listing_id, l.listed_at) for l in got] == [
        ("11", datetime(2026, 9, 19, 5, tzinfo=timezone.utc)), ("22", None)]


def test_carroya_discover_reads_publication_date(cfg, tmp_path):
    page = {"pages": 1, "results": {"superHighlights": [
        {"id": "x1", "clfechapub": "2026-11-14T20:40:46.000Z", "cfechapublicacion": "2026-11-19T16:41:39.000Z"},
        {"id": "x2", "cfecharegistro": "2026-01-02T00:00:00.000Z"}, {"id": "x3"}]}}
    p = tmp_path / "search.json"
    p.write_text(json.dumps(page))
    got = list(CarroYaScraper(cfg, client=FakeClient({"find-filters": str(p)})).discover())
    assert [l.listed_at for l in got] == [to_datetime("2026-11-14T20:40:46Z"),
                                          to_datetime("2026-01-02"), None]
