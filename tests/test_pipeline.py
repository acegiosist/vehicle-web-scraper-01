"""End-to-end: discover -> parse -> SQLite -> CSV export -> coverage, offline."""
import json

from vehicle_scraper import cli
from vehicle_scraper.http import BlockedError
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
