"""`new-site` scaffolding: URL-shape inference, probing and code generation, all offline."""
import re

import pytest
import requests

from vehicle_scraper import scaffold as S
from vehicle_scraper.http import BlockedError
from vehicle_scraper.sites import REGISTRY
from vehicle_scraper.sites.base import Listing
from vehicle_scraper.sites.cofino import CofinoScraper

from .conftest import FakeClient

COFINO_URLS = [
    "https://cofinousados.com/catalogo/honda-hr-v-exl-2022-6390",
    "https://cofinousados.com/catalogo/toyota-hilux-sr-2021-6391",
    "https://cofinousados.com/catalogo/mazda-cx-5-grand-touring-2023-6392",
]


class Fake404(FakeClient):
    """FakeClient that answers unknown URLs with a 404 instead of failing the test."""

    def _serve(self, method, url):
        try:
            return super()._serve(method, url)
        except AssertionError:
            raise requests.HTTPError(f"HTTP 404 for {url}") from None


def test_site_name():
    assert S.site_name("www.autos-xyz.com.co") == "autos_xyz"
    assert S.site_name("cofinousados.com") == "cofinousados"
    assert S.site_name("www.chileautos.cl") == "chileautos"
    assert S.site_name("123carros.com") == "site_123carros"


def test_url_groups_picks_detail_pages():
    noise = ["https://x.com/marcas/toyota", "https://x.com/marcas/honda",
             "https://x.com/blog/post-uno-2024", "https://x.com/contacto", "https://x.com/logo.png"]
    groups = S.url_groups([u.replace("cofinousados.com", "x.com") for u in COFINO_URLS] + noise)
    assert [g.pattern for g in groups] == [r"/catalogo/[a-z0-9-]+-\d+/?$"]
    assert groups[0].id_pattern == r"-(\d+)/?$"


def test_url_groups_uuid_in_deep_path():
    urls = [
        "https://c.com/detalle/usado/hyundai/tucson/2010/bogota/928d091b-9e37-4938-a3f3-a091dc538590",
        "https://c.com/detalle/usado/mazda/cx-5/2019/medellin/0a1b2c3d-1111-2222-3333-444455556666",
    ]
    g = S.url_groups(urls)[0]
    assert g.pattern == r"/detalle/usado/[a-z0-9-]+/[a-z0-9-]+/\d+/[a-z0-9-]+/[0-9a-fA-F-]{36}/?$"
    assert g.id_pattern == r"/([0-9a-fA-F-]{36})/?$"


def test_url_groups_year_is_not_an_id():
    urls = ["https://x.com/autos/toyota-corolla-2019", "https://x.com/autos/mazda-3-2019",
            "https://x.com/autos/kia-rio-2020"]
    g = S.url_groups(urls)[0]
    assert g.pattern == r"/autos/[a-z0-9-]+-\d+/?$"
    assert g.id_pattern == r"/([a-z0-9-]+-\d+)/?$"     # "2019" repeats, so the whole slug is the id


def test_url_groups_id_falls_back_to_unique_segment():
    base = "https://www.truecar.com/used-cars-for-sale/listing"
    urls = [f"{base}/19UDE4G77TA007881/2026-acura-integra/", f"{base}/19UDE4G70TA001234/2026-acura-integra/",
            f"{base}/1GYKNDRS6LZ120420/2020-cadillac-xt5/"]
    g = S.url_groups(urls)[0]
    assert g.id_pattern == r"/([A-Za-z0-9-]+)/[a-z0-9-]+/?$" and g.id_unique   # the VIN, not the model slug
    assert re.search(g.id_pattern, urls[0]).group(1) == "19UDE4G77TA007881"


def test_detect_pagination():
    page = "https://x.com/usados"
    assert S.detect_pagination(page, [f"{page}?page=2", f"{page}?page=3", "https://x.com/otros?page=2"]) == \
        {"page_url_template": "https://x.com/usados?page={page}", "first_page": 1}
    assert S.detect_pagination(page, [f"{page}/pagina/2"]) == \
        {"page_url_template": "https://x.com/usados/pagina/{page}", "first_page": 1}
    assert S.detect_pagination(page, [f"{page}?orden=precio&offset=24", f"{page}?orden=precio&offset=48"]) == \
        {"page_url_template": "https://x.com/usados?orden=precio&offset={offset}", "first_page": 1, "page_size": 24}
    assert S.detect_pagination(page, ["https://x.com/autos/kia-rio-2018-104514"]) is None


def test_clean_html_drops_scripts_and_contact_data():
    html = ('<html><head><script src="app.js"></script><style>p{}</style>'
            '<script type="application/ld+json">{"@type":"Car"}</script></head><body>'
            '<a href="tel:+573001234567">Llamar</a> <p>ventas@dealer.com +57 300 123 4567</p>'
            '<p>Call (630) 286-6801 or 1-888-878-3227. VIN 1GYKNDRS6LZ120420, $34,662</p></body></html>')
    out = S.clean_html(html)
    assert "app.js" not in out and "<style" not in out and '"@type":"Car"' in out
    assert "3001234567" not in out and "ventas@dealer.com" not in out and "300 123 4567" not in out
    assert "286-6801" not in out and "878-3227" not in out
    assert "1GYKNDRS6LZ120420" in out and "$34,662" in out


def test_scaffold_from_sitemap(cfg, tmp_path):
    client = FakeClient({"robots.txt": "scaffold_robots.txt", "sitemap.xml": "scaffold_sitemap.xml",
                         "/catalogo/": "cofino_detail.html", "cofinousados.com": "scaffold_listing.html"})
    sc = S.scaffold_site("https://cofinousados.com", client=client, cfg=cfg, name="zz_scaffold_probe", currency="GTQ")
    pr = sc.probe

    assert pr.discovery.attrs == {"sitemap_url": "https://cofinousados.com/sitemap.xml",
                                  "sitemap_pattern": r"/catalogo/[a-z0-9-]+-\d+/?$"}
    assert pr.discovery.group.id_pattern == r"-(\d+)/?$"
    assert pr.spec == ("heading", "detalles del auto")
    assert pr.has_jsonld and not pr.has_embedded
    assert pr.notes == ["robots.txt: Content-Signal: search=yes, ai-train=no"]
    assert list(pr.unmapped) == ["Código interno", "Blindaje", "Ubicación"]
    assert any("MXN" in w and "GTQ" in w for w in pr.warnings)
    assert "zz_scaffold_probe" not in REGISTRY                     # previewing must not register the site

    # The generated parser reads the page the same way the hand-written CofinoScraper does.
    hand = CofinoScraper(cfg, client=FakeClient({"/catalogo/": "cofino_detail.html"}))
    expected = hand.parse(Listing(sc.record.listing_id, sc.record.source_url))
    skip = {"scraped_at", "source_site"}
    assert sc.record.model_dump(exclude=skip) == expected.model_dump(exclude=skip)

    sites_dir, tests_dir = tmp_path / "sites", tmp_path / "tests"
    sites_dir.mkdir()
    (sites_dir / "__init__.py").write_text(
        "from . import carroya, cofino, tucarro  # noqa: F401  (registers sites)\n", encoding="utf-8")
    written = S.write_scaffold(sc, sites_dir, tests_dir)
    assert (sites_dir / "__init__.py").read_text(encoding="utf-8").startswith(
        "from . import carroya, cofino, tucarro, zz_scaffold_probe  # noqa: F401")
    assert {p.name for p in written} == {"zz_scaffold_probe.py", "zz_scaffold_probe_detail.html",
                                         "test_site_zz_scaffold_probe.py", "__init__.py"}
    compile(sc.test_src, "test_site_zz_scaffold_probe.py", "exec")
    assert "'model': 'HR-V EXL'" in sc.test_src and "'currency': 'GTQ'" in sc.test_src
    module = (sites_dir / "zz_scaffold_probe.py").read_text(encoding="utf-8")
    assert "class ZzScaffoldProbeScraper(HtmlSiteScraper)" in module and "'detalles del auto'" in module


def test_scaffold_from_listing_page(cfg):
    client = Fake404({"/autos/": "cofino_detail.html", "/usados": "scaffold_listing.html"})
    sc = S.scaffold_site("https://www.example-autos.com.co/usados", client=client, cfg=cfg)
    pr = sc.probe
    assert (pr.name, pr.country, pr.currency) == ("example_autos", "CO", "COP")
    assert pr.discovery.attrs == {
        "page_url_template": "https://www.example-autos.com.co/usados?page={page}",
        "first_page": 1,
        "link_pattern": r"/autos/[a-z0-9-]+-\d+/?$",
    }
    assert sc.record.listing_id == "104512" and sc.record.make == "Honda"

    # The generated discover() walks the listing pages and stops when a page adds nothing new.
    cls = S.load_module_class(sc.module_src, pr.name)
    listings = list(cls(cfg, client=client).discover())
    assert [li.listing_id for li in listings] == ["104512", "104513", "104514"]


def test_blocked_site_generates_nothing(cfg):
    class Blocked(FakeClient):
        def get(self, url, **kw):
            raise BlockedError(f"DataDome CAPTCHA at {url}")

    with pytest.raises(BlockedError):
        S.scaffold_site("https://www.chileautos.cl/vehiculos/", client=Blocked({}), cfg=cfg)


def test_with_import_is_idempotent():
    text = "x = 1\nfrom . import a, c  # noqa: F401\n"
    once = S._with_import(text, "b")
    assert once == "x = 1\nfrom . import a, b, c  # noqa: F401\n"
    assert S._with_import(once, "b") == once
