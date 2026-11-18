"""Scaffold a dedicated scraper for a new site from one URL.

``scaffold_site`` probes the site through the polite client (robots.txt, crawl delay and
block detection all still apply), infers how to discover listings and where the specs live
on a detail page, and renders ``sites/<name>.py``, a test fixture and a snapshot test.
``write_scaffold`` puts them on disk and adds the module to ``sites/__init__.py``.
"""
from __future__ import annotations

import dataclasses
import math
import re
import types
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import mean
from string import Template
from typing import Optional
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup, Comment

from . import extract as X
from .config import Settings
from .http import DisallowedError, Response
from .mapping import RecordBuilder, match_label
from .models import SCHEMA_FIELDS, VehicleRecord
from .sites.base import REGISTRY, Listing

SITES_DIR = Path(__file__).resolve().parent / "sites"
TESTS_DIR = Path(__file__).resolve().parents[2] / "tests"

TLD_MARKETS = {
    "co": ("CO", "COP"), "cl": ("CL", "CLP"), "gt": ("GT", "GTQ"), "cr": ("CR", "CRC"),
    "mx": ("MX", "MXN"), "pe": ("PE", "PEN"), "ec": ("EC", "USD"), "ar": ("AR", "ARS"),
    "uy": ("UY", "UYU"), "py": ("PY", "PYG"), "bo": ("BO", "BOB"), "ve": ("VE", "VES"),
    "pa": ("PA", "USD"), "hn": ("HN", "HNL"), "ni": ("NI", "NIO"), "sv": ("SV", "USD"),
    "do": ("DO", "DOP"), "br": ("BR", "BRL"), "in": ("IN", "INR"), "es": ("ES", "EUR"),
    "us": ("US", "USD"), "ca": ("CA", "CAD"), "uk": ("GB", "GBP"), "au": ("AU", "AUD"),
    "za": ("ZA", "ZAR"),
}
_GENERIC_LABELS = {"www", "m", "com", "co", "net", "org", "gob", "gov", "edu", "ac"}
_NOT_DETAIL = {"blog", "noticias", "news", "page", "pagina", "tag", "tags", "category", "categoria",
               "categorias", "author", "autor", "wp-content", "wp-json", "feed", "ayuda", "help"}
_ASSET = re.compile(r"\.(?:jpe?g|png|gif|webp|svg|css|js|pdf|xml|ico|mp4|json)$", re.I)
_PAGE_EXT = re.compile(r"^(.+?)(\.(?:html?|php|aspx?|jsp))$", re.I)
_UUID_RX = "[0-9a-fA-F-]{36}"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_YEAR = re.compile(r"(?<!\d)(?:19[5-9]\d|20[0-4]\d)(?!\d)")
_MAKES = re.compile(
    r"(?<![a-z])(?:toyota|honda|mazda|chevrolet|nissan|kia|hyundai|ford|renault|volkswagen|vw|"
    r"mitsubishi|suzuki|bmw|mercedes|audi|jeep|subaru|peugeot|fiat|dodge|ram|lexus|volvo|chery|jac|"
    r"byd|mg|citroen|isuzu|porsche|land-rover|tesla|ssangyong|great-wall|changan|dfsk|geely|haval|"
    r"skoda|seat|mini|infiniti|acura|cadillac|chrysler|gmc|buick|lincoln|jaguar|foton|baic|opel|"
    r"dacia|tata|mahindra|maruti)(?![a-z])")
_KINDS = ("num", "uuid", "slugnum", "slugyear", "slug")
_ID_KINDS = ("num", "uuid", "slugnum")
_SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_VEHICLE_SITEMAP = re.compile(r"auto|car|veh|invent|usad|catalog|listing|stock|anunci|ficha", re.I)
_PAGINATION = (
    (re.compile(r"([?&](?:page|pagina|pag|pg|p)=)(\d+)", re.I), "page"),
    (re.compile(r"(/(?:page|pagina|pag|p)/)(\d+)", re.I), "page"),
    (re.compile(r"([?&](?:offset|start|desde|from|skip)=)(\d+)", re.I), "offset"),
)
_SAFE_TOKEN = re.compile(r"^[A-Za-z][\w-]*$")
# Utility (Tailwind/Bootstrap) and hashed (CSS-modules, styled-components) classes change
# between deploys or match many elements, so they make poor selectors.
_UNSTABLE_CLASS = re.compile(
    r"\d{3,}|__[A-Za-z0-9]{5}$|^(?:css|sc|jsx|svelte|emotion)-"
    r"|^-?(?:[mp][xytblrse]?|[wh]|gap|inset|top|left|right|bottom|z|order|d|col|row)-"
    r"|^(?:flex|grid|block|inline|hidden|relative|absolute|sticky|rounded|bg-|text-|font-|border|"
    r"shadow|items-|justify-|space-|container$|min-|max-|overflow|leading-|tracking-|self-|place-|"
    r"object-|opacity|transition|duration|ease|cursor|select-|ring|divide|align-)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CONTACT_HREF = re.compile(r'(href=["\'])(?:tel:|mailto:|https?://(?:wa\.me|api\.whatsapp\.com)/)[^"\']*', re.I)
_INTL_PHONE = re.compile(r"\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}")


class ScaffoldError(RuntimeError):
    """The site could not be scaffolded (no listings found, nothing parseable, ...)."""


@dataclass
class UrlGroup:
    pattern: str            # regex matching every detail URL of this shape
    id_pattern: str         # regex with one group -> listing id
    urls: list[str]
    score: float


@dataclass
class Discovery:
    attrs: dict             # HtmlSiteScraper class attributes
    description: str
    group: UrlGroup
    alternatives: list[UrlGroup] = field(default_factory=list)


@dataclass
class SiteProbe:
    url: str
    name: str
    base_url: str
    country: str
    currency: Optional[str]
    discovery: Discovery
    samples: list[tuple[str, str]]              # (url, cleaned html)
    has_jsonld: bool
    has_embedded: bool
    spec: Optional[tuple[str, str]]             # ("selector", css) | ("heading", text)
    wait_selector: Optional[str]
    unmapped: dict[str, str]
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def class_name(self) -> str:
        return "".join(p.capitalize() for p in self.name.split("_") if p) + "Scraper"


@dataclass
class Scaffold:
    probe: SiteProbe
    module_src: str
    test_src: str
    fixture_html: str
    record: VehicleRecord
    sample_results: list[tuple[str, Optional[VehicleRecord], str]]   # (url, record, error)


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

def site_name(host: str) -> str:
    """``www.autos-xyz.com.co`` -> ``autos_xyz``."""
    labels = [label for label in host.lower().split(":")[0].split(".") if label]
    if labels and labels[0] in ("www", "m"):
        labels = labels[1:]
    core = [label for label in labels[:-1] if label not in _GENERIC_LABELS] or labels or ["site"]
    name = re.sub(r"[^a-z0-9]+", "_", core[0]).strip("_") or "site"
    return name if name[0].isalpha() else f"site_{name}"


# ---------------------------------------------------------------------------
# URL shapes: group candidate URLs and infer a detail-page regex
# ---------------------------------------------------------------------------

def _esc(s: str) -> str:
    return re.escape(s).replace(r"\-", "-")


def _split_ext(seg: str) -> tuple[str, str]:
    m = _PAGE_EXT.match(seg)
    return (m.group(1), m.group(2)) if m else (seg, "")


def _kind(stem: str) -> str:
    if stem.isdigit():
        return "num"
    if _UUID.fullmatch(stem):
        return "uuid"
    if re.fullmatch(r".*[A-Za-z].*-\d{3,}", stem):
        return "slugnum"
    if _YEAR.search(stem) and stem.count("-") >= 2:
        return "slugyear"
    return "slug"


def _shape_key(segs: list[str]) -> tuple:
    key = []
    for i, seg in enumerate(segs):
        stem, ext = _split_ext(seg)
        k = _kind(stem)
        # A plain first segment is usually a section ("/autos/", "/blog/"): keep it literal so
        # different sections land in different groups.
        key.append((stem if i == 0 and k == "slug" else k, ext.lower()))
    return tuple(key)


def _char_class(stems: list[str]) -> str:
    if all(re.fullmatch(r"[a-z0-9-]+", s) for s in stems):
        return "[a-z0-9-]+"
    if all(re.fullmatch(r"[A-Za-z0-9-]+", s) for s in stems):
        return "[A-Za-z0-9-]+"
    return "[^/]+"


def _build_group(key: tuple, members: list[tuple[str, list[str]]]) -> Optional[UrlGroup]:
    urls = [u for u, _ in members]
    cols: list[str] = []
    id_cols: list[tuple[int, str]] = []
    for i, (k, _) in enumerate(key):
        k = k if k in _KINDS else "slug"
        stems, exts = zip(*(_split_ext(segs[i]) for _, segs in members))
        ext = _esc(exts[0])
        if k == "num":
            rx, idrx = r"\d+", r"/(\d+)"
        elif k == "uuid":
            rx, idrx = _UUID_RX, f"/({_UUID_RX})"
        elif k == "slugnum":
            rx, idrx = _char_class([re.sub(r"-\d+$", "", s) for s in stems]) + r"-\d+", r"-(\d+)"
        elif len(set(stems)) == 1 and k == "slug":
            rx, idrx = _esc(stems[0]), ""
        else:
            rx, idrx = _char_class(list(stems)), ""
        cols.append(rx + ext)
        if k in _ID_KINDS:
            id_cols.append((i, idrx + ext))

    paths = [urlparse(u).path.lower() for u in urls]
    frac_year = mean(bool(_YEAR.search(p)) for p in paths)
    frac_make = mean(bool(_MAKES.search(p)) for p in paths)
    has_id = bool(id_cols)
    if not has_id and frac_year < 0.5:
        return None                       # brand/category/static pages, not listings

    pattern = "/" + "/".join(cols) + "/?$"
    id_pattern = r"/([^/]+)/?$"
    if has_id:
        i, idrx = id_cols[-1]
        candidate = idrx + "".join("/" + c for c in cols[i + 1:]) + "/?$"
        ids = [m.group(1) if (m := re.search(candidate, u)) else None for u in urls]
        if None not in ids and len(set(ids)) == len(ids):   # e.g. "corolla-2019" is not an id
            id_pattern = candidate
    score = len(urls) * (1 + has_id + frac_make + frac_year)
    return UrlGroup(pattern, id_pattern, urls, score)


def url_groups(urls: list[str], min_size: int = 2) -> list[UrlGroup]:
    """Group URLs by path shape and return detail-page-looking groups, best first."""
    buckets: dict[tuple, list[tuple[str, list[str]]]] = {}
    for url in dict.fromkeys(urls):
        path = urlparse(url).path
        segs = [s for s in path.split("/") if s]
        if not segs or _ASSET.search(path) or segs[0].lower() in _NOT_DETAIL:
            continue
        buckets.setdefault(_shape_key(segs), []).append((url, segs))
    groups = [g for key, members in buckets.items()
              if len(members) >= min_size and (g := _build_group(key, members))]
    return sorted(groups, key=lambda g: -g.score)


def detect_pagination(page_url: str, hrefs: list[str]) -> Optional[dict]:
    """Infer ``page_url_template`` (+ ``first_page``/``page_size``) from pagination links."""
    page = urlparse(page_url)
    base_path = page.path.rstrip("/")
    found: dict[tuple[str, str], set[int]] = {}
    for href in [page_url, *hrefs]:
        if urlparse(href).netloc != page.netloc:
            continue
        for rx, kind in _PAGINATION:
            m = rx.search(href)
            if not m:
                continue
            if urlparse(href[:m.start()]).path.rstrip("/") != base_path:
                break
            esc = lambda s: s.replace("{", "{{").replace("}", "}}")   # noqa: E731
            tmpl = esc(href[:m.start(2)]) + "{" + kind + "}" + esc(href[m.end(2):])
            found.setdefault((tmpl, kind), set()).add(int(m.group(2)))
            break
    if not found:
        return None
    (tmpl, kind), nums = max(found.items(), key=lambda kv: len(kv[1]))
    if kind == "page":
        return {"page_url_template": tmpl, "first_page": 0 if 0 in nums else 1}
    steps = sorted(nums | {0})
    diffs = [b - a for a, b in zip(steps, steps[1:]) if b > a]
    return {"page_url_template": tmpl, "first_page": 1, "page_size": min(diffs) if diffs else 12}


# ---------------------------------------------------------------------------
# Fetching helpers
# ---------------------------------------------------------------------------

def _try_get(client, url: str) -> Optional[str]:
    """GET that treats 404s, network errors and robots-disallowed URLs as 'not available'."""
    try:
        return client.get(url).text
    except (requests.RequestException, DisallowedError):
        return None


def _fetch(client, url: str, browser: bool) -> str:
    return (client.render(url) if browser else client.get(url)).text


def _robots_info(client, base_url: str) -> tuple[list[str], list[str]]:
    text = _try_get(client, f"{base_url}/robots.txt") or ""
    sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", text)
    signals = sorted({line.strip() for line in text.splitlines()
                      if not line.lstrip().startswith("#")
                      and (re.match(r"(?i)\s*content-signal\s*:", line) or re.search(r"(?i)ai-train\s*=\s*no", line))})
    return sitemaps, signals


def _sitemap_urls(client, url: str, out: list[tuple[str, str]], children: set[str],
                  limit: int = 3000, depth: int = 0) -> None:
    """Collect (page_url, sitemap_url) pairs; vehicle-looking child sitemaps are read first."""
    xml = _try_get(client, url)
    if not xml:
        return
    try:
        root = ET.fromstring(xml.encode())
    except ET.ParseError:
        return
    kids = [loc.text.strip() for loc in root.findall(".//s:sitemap/s:loc", _SITEMAP_NS) if loc.text]
    children.update(kids)
    if depth < 2:
        for kid in sorted(kids, key=lambda u: not _VEHICLE_SITEMAP.search(urlparse(u).path))[:6]:
            if len(out) >= limit:
                return
            _sitemap_urls(client, kid, out, children, limit, depth + 1)
    for loc in root.findall(".//s:url/s:loc", _SITEMAP_NS):
        if loc.text and len(out) < limit:
            out.append((loc.text.strip(), url))


def _discover_sitemap(client, sitemaps: list[str]) -> Optional[Discovery]:
    for top in sitemaps[:3]:
        out: list[tuple[str, str]] = []
        children: set[str] = set()
        _sitemap_urls(client, top, out, children)
        groups = url_groups([u for u, _ in out], min_size=3)
        if not groups:
            continue
        g = groups[0]
        source = dict(out)
        files = {source[u] for u in g.urls}
        chosen = top
        if len(files) == 1 and (f := next(iter(files))) != top:
            # Point straight at the child sitemap, unless it's one of a numbered series.
            stem = re.sub(r"\d+", "", f)
            if sum(re.sub(r"\d+", "", c) == stem for c in children) == 1:
                chosen = f
        attrs = {"sitemap_url": chosen, "sitemap_pattern": g.pattern}
        return Discovery(attrs, f"sitemap {chosen}", g, groups[1:4])
    return None


def _page_links(soup: BeautifulSoup, page_url: str) -> tuple[list[str], list[str]]:
    """(raw same-host hrefs, detail-link candidates normalized like HtmlSiteScraper._links)."""
    host = urlparse(page_url).netloc
    hrefs = []
    for a in soup.find_all("a", href=True):
        raw = urljoin(page_url, a["href"]).split("#")[0]
        if urlparse(raw).netloc == host:
            hrefs.append(raw)
    return hrefs, list(dict.fromkeys(h.split("?")[0] for h in hrefs))


def _discover_listing(client, pages: list[tuple[str, Optional[str]]], browser: bool,
                      warnings: list[str]) -> Optional[Discovery]:
    for page_url, html in pages:
        if html is None:
            try:
                html = _fetch(client, page_url, browser)
            except requests.RequestException:
                continue
        hrefs, links = _page_links(X.soup_of(html), page_url)
        groups = url_groups(links)
        if not groups:
            continue
        g = groups[0]
        pag = detect_pagination(page_url, hrefs)
        if pag:
            attrs = {**pag, "link_pattern": g.pattern}
            desc = f"listing pages {pag['page_url_template']}"
        else:
            attrs = {"start_urls": [page_url], "link_pattern": g.pattern}
            desc = f"listing page {page_url} (no pagination found)"
            warnings.append(f"no pagination links found on {page_url}: only the listings it links to "
                            "will be scraped. Set page_url_template if the site has more pages.")
        return Discovery(attrs, desc, g, groups[1:4])
    return None


# ---------------------------------------------------------------------------
# Detail-page analysis
# ---------------------------------------------------------------------------

def clean_html(html: str) -> str:
    """Shrink a page into a fixture: drop scripts (except JSON data), styles and comments, and
    blank out contact details so no personal data lands in the repo."""
    soup = X.soup_of(html)
    for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for t in soup.find_all(["style", "link", "noscript", "iframe", "template"]):
        t.decompose()
    for s in soup.find_all("script"):
        keep = (s.get("type") == "application/ld+json" or s.get("id") == "__NEXT_DATA__"
                or re.search(r"window\.__\w+__\s*=", s.string or ""))
        if not keep:
            s.decompose()
    for svg in soup.find_all("svg"):
        svg.clear()
        svg.attrs = {}
    text = _CONTACT_HREF.sub(r"\1#", str(soup))
    text = _EMAIL.sub("email@example.com", text)
    return _INTL_PHONE.sub("+00 000 000 0000", text)


def _norm_ws(s: str) -> str:
    return " ".join(str(s).split())


def _heading_text(h) -> str:
    return _norm_ws(h.get_text(" ", strip=True)).lower()


def _own_heading(soup: BeautifulSoup, el) -> Optional[str]:
    """Text of a heading that is a direct child of ``el`` and is the first such heading on the page."""
    h = el.find(["h2", "h3", "h4"], recursive=False)
    if h is None:
        return None
    text = _heading_text(h)
    if not 3 <= len(text) <= 40:
        return None
    first = next((x for x in soup.find_all(["h2", "h3", "h4"]) if text in _heading_text(x)), None)
    return text if first is h else None


def _id_selector(soup: BeautifulSoup, el) -> Optional[str]:
    el_id = el.get("id")
    if el_id and _SAFE_TOKEN.match(el_id) and not _UNSTABLE_CLASS.search(el_id):
        if soup.select_one(f"#{el_id}") is el:
            return f"#{el_id}"
    return None


def _class_selector(soup: BeautifulSoup, el) -> Optional[str]:
    for cls in el.get("class") or []:
        if _SAFE_TOKEN.match(cls) and not _UNSTABLE_CLASS.search(cls):
            sel = f"{el.name}.{cls}"
            if soup.select(sel) == [el]:
                return sel
    return None


def find_spec_section(soup: BeautifulSoup) -> Optional[tuple[str, str]]:
    """Locate the element holding most mapped label/value pairs and describe how to find it
    again: ``("selector", css)`` or ``("heading", heading text)``. None -> use the whole page."""
    root = soup.find("main") or soup.body or soup
    labels = [label for label, _ in X.html_pairs(root) if match_label(label)]
    if len(labels) < 3:
        return None
    nodes = [n for lab in labels
             if (n := root.find(string=lambda s, lab=lab: _norm_ws(s).startswith(lab))) is not None]
    need = max(2, math.ceil(0.8 * len(nodes)))
    counts: Counter = Counter()
    index: dict[int, object] = {}
    for node in nodes:
        for anc in node.parents:
            counts[id(anc)] += 1
            index[id(anc)] = anc
            if anc is root:
                break
    candidates = [index[k] for k, c in counts.items() if c >= need and index[k] is not root]
    if not candidates:
        return None
    el = max(candidates, key=lambda e: len(list(e.parents)))
    limit = len(X.html_pairs(el)) * 1.5 + 2      # don't climb into containers with extra noise
    cur = el
    while cur is not None and cur is not root and len(X.html_pairs(cur)) <= limit:
        sel = _id_selector(soup, cur)
        if sel:
            return ("selector", sel)
        head = _own_heading(soup, cur)
        if head:
            return ("heading", head)
        sel = _class_selector(soup, cur)
        if sel:
            return ("selector", sel)
        cur = cur.parent
    return None


def _analyze(html: str) -> dict:
    soup = X.soup_of(html)
    b = RecordBuilder("probe", "", "")
    cars = X.jsonld_vehicles(soup)
    for car in cars:
        X.apply_jsonld(b, car)
    site_currency = b.values.get("currency")
    blobs = X.embedded_json(soup)
    emb_pairs = [p for blob in blobs for p in X.walk_json_pairs(blob)]
    b.add_pairs(emb_pairs)
    html_pairs = X.html_pairs(soup.find("main") or soup.body or soup)
    b.add_pairs(html_pairs)
    return {
        "jsonld": bool(cars),
        "blobs": len(blobs),
        "embedded": any(match_label(label) for label, _ in emb_pairs),
        "mapped_html": sum(1 for label, _ in html_pairs if match_label(label)),
        "currency": site_currency,
        "unmapped": b.unmapped,
    }


def _section(soup: BeautifulSoup, spec: tuple[str, str]):
    if spec[0] == "selector":
        return soup.select_one(spec[1])
    h = next((h for h in soup.find_all(["h2", "h3", "h4"]) if spec[1] in _heading_text(h)), None)
    return h.parent if h else None


def _section_unmapped(samples: list[tuple[str, str]], spec: tuple[str, str]) -> dict[str, str]:
    """Unmapped labels from what the generated parser reads (structured data + spec section),
    leaving out menus, footers and other page chrome."""
    unmapped: dict[str, str] = {}
    for _, html in samples:
        soup = X.soup_of(html)
        section = _section(soup, spec)
        if section is None:
            continue
        b = RecordBuilder("probe", "", "")
        for car in X.jsonld_vehicles(soup):
            X.apply_jsonld(b, car)
        for blob in X.embedded_json(soup):
            b.add_pairs(X.walk_json_pairs(blob))
        b.add_pairs(X.html_pairs(section))
        for k, v in b.unmapped.items():
            unmapped.setdefault(k, v)
    return unmapped


def _spread(urls: list[str], n: int = 3) -> list[str]:
    if len(urls) <= n:
        return list(urls)
    return [urls[0], urls[len(urls) // 2], urls[-1]][:n]


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

def probe_site(url: str, *, client, name: Optional[str] = None, country: Optional[str] = None,
               currency: Optional[str] = None, browser: bool = False) -> SiteProbe:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ScaffoldError(f"expected an http(s) URL, got {url!r}")
    base_url = f"{p.scheme}://{p.netloc}"
    name = name or site_name(p.netloc)
    warnings: list[str] = []

    sitemaps, signals = _robots_info(client, base_url)
    notes = [f"robots.txt: {s}" for s in signals]
    first_html = _fetch(client, url, browser)              # Blocked/Disallowed propagate: stop here
    first_is_detail = bool(X.jsonld_vehicles(X.soup_of(first_html)))

    discovery = _discover_sitemap(client, sitemaps or [f"{base_url}/sitemap.xml"])
    if discovery is None:
        home = f"{base_url}/"
        pages = [(url, first_html)] + ([(home, None)] if url.rstrip("/") != base_url else [])
        if first_is_detail:
            pages.reverse()
        discovery = _discover_listing(client, pages, browser, warnings)
    if discovery is None:
        raise ScaffoldError("could not find listing URLs in a sitemap or among the page's links. "
                            "Pass the URL of a search/listing page that links to individual cars.")
    g = discovery.group
    if re.search(g.pattern, url.split("?")[0]):
        first_is_detail = True

    samples: list[tuple[str, str]] = []
    for su in dict.fromkeys(([url] if first_is_detail else []) + _spread(g.urls)):
        if len(samples) == 3:
            break
        try:
            html = first_html if su == url else _fetch(client, su, browser)
        except requests.RequestException as e:
            warnings.append(f"could not fetch sample {su}: {e}")
            continue
        samples.append((su, clean_html(html)))
    if not samples:
        raise ScaffoldError("none of the sample detail pages could be fetched")

    analyses = [_analyze(html) for _, html in samples]
    main = analyses[0]
    soup = X.soup_of(samples[0][1])
    spec = find_spec_section(soup)
    if spec and spec[0] == "heading":
        missing = [u for (u, h) in samples[1:] if spec[1] not in h.lower()]
        if missing:
            warnings.append(f"spec heading '{spec[1]}' not found on {len(missing)} other sample(s)")
    unmapped = _section_unmapped(samples, spec) if spec else {}
    if not spec:
        for a in analyses:
            for k, v in a["unmapped"].items():
                if len(k) <= 40:
                    unmapped.setdefault(k, v)

    tld_country, tld_currency = TLD_MARKETS.get(p.netloc.rsplit(".", 1)[-1].lower(), ("", None))
    country = (country or tld_country or "").upper()
    currency = (currency or tld_currency or "").upper() or None
    site_currency = next((a["currency"] for a in analyses if a["currency"]), None)
    if currency and site_currency and site_currency != currency:
        warnings.append(f"the site's structured data says {site_currency} but the module will force "
                        f"{currency}; check a listing's price to see which is right (--currency)")
    elif not currency and not site_currency:
        warnings.append("no currency found; pass --currency")
    if not country:
        warnings.append("country unknown from the domain; pass --country (ISO code)")

    has_embedded = any(a["embedded"] for a in analyses)
    if any(a["blobs"] for a in analyses) and not has_embedded:
        warnings.append("the page embeds JSON state but no spec labels were recognized in it; the data "
                        "may come from an API (see carroya.py for an API-based scraper)")
    if not browser and not main["jsonld"] and not has_embedded and main["mapped_html"] < 2:
        warnings.append("almost no specs found in the HTML: the page may be rendered with JavaScript. "
                        "Retry with --browser")

    wait_selector = None
    if browser:
        wait_selector = spec[1] if spec and spec[0] == "selector" else ("h1" if soup.find("h1") else "body")

    return SiteProbe(url=url, name=name, base_url=base_url, country=country, currency=currency,
                     discovery=discovery, samples=samples, has_jsonld=any(a["jsonld"] for a in analyses),
                     has_embedded=has_embedded, spec=spec, wait_selector=wait_selector,
                     unmapped=unmapped, notes=notes, warnings=warnings)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

MODULE_TEMPLATE = Template('''r"""$title

Scaffolded by `vehicle_scraper new-site` on $today from $source_url
$findings
"""
from __future__ import annotations

from .. import extract as X
from ..mapping import RecordBuilder
from ..models import VehicleRecord
from .base import Listing, register
from .html_site import HtmlSiteScraper


@register
class $cls(HtmlSiteScraper):
$attrs

    def parse(self, listing: Listing) -> VehicleRecord:
        soup = X.soup_of(self.fetch_html(listing.url, self.wait_selector))
        b = RecordBuilder(self.name, listing.url, listing.listing_id)

        # Most reliable sources first: the first value set for a field wins.
$steps
        return self.finish(b.build())
''')

TEST_TEMPLATE = Template('''"""Snapshot of what the $name scraper extracted from its sample page when it was scaffolded
($today). After improving the parser, check the new values and update EXPECTED."""
from vehicle_scraper.sites.base import Listing
from vehicle_scraper.sites.$name import $cls

from .conftest import FakeClient

URL = $url
EXPECTED = {
$expected
}


def test_${name}_detail(cfg):
    client = FakeClient({$route: "${name}_detail.html"})
    rec = $cls(cfg, client=client).parse(Listing($listing_id, URL))
    got = {k: v for k, v in rec.model_dump(exclude={"scraped_at", "parse_warnings"}).items() if v is not None}
    assert got == EXPECTED
''')


def _rx(pattern: str) -> str:
    if '"' not in pattern and not pattern.endswith("\\"):
        return f'r"{pattern}"'
    return repr(pattern)


def _attr_lines(pr: SiteProbe) -> list[str]:
    notes = "; ".join(["Scaffolded by new-site; review before marking verified", *pr.notes])
    lines = [
        f"name = {pr.name!r}",
        f"base_url = {pr.base_url!r}",
        f"country = {pr.country!r}",
        f"currency = {pr.currency!r}",
        'status = "unverified"',
        f"notes = {notes!r}",
        "",
    ]
    for key, value in pr.discovery.attrs.items():
        lines.append(f"{key} = {_rx(value) if key.endswith('pattern') else repr(value)}")
    lines.append(f"id_pattern = {_rx(pr.discovery.group.id_pattern)}")
    if pr.spec and pr.spec[0] == "selector":
        lines.append(f"spec_selector = {pr.spec[1]!r}")
    if pr.wait_selector:
        lines.append(f"wait_selector = {pr.wait_selector!r}")
    return ["    " + line if line else "" for line in lines]


def _step_lines(pr: SiteProbe) -> list[str]:
    s = ["for car in X.jsonld_vehicles(soup):",
         "    X.apply_jsonld(b, car)"]
    if pr.has_embedded:
        s += ["for blob in X.embedded_json(soup):",
              "    b.add_pairs(X.walk_json_pairs(blob))"]
    if pr.spec:
        if pr.spec[0] == "selector":
            s += ["", "section = soup.select_one(self.spec_selector)"]
        else:
            s += ["",
                  "h = next((h for h in soup.find_all([\"h2\", \"h3\", \"h4\"])",
                  f"          if {pr.spec[1]!r} in \" \".join(h.get_text(\" \", strip=True).split()).lower()), None)",
                  "section = h.parent if h else None"]
        s += ["if section is None:",
              "    b.warn(\"spec section not found; reading the whole page\")",
              "    X.apply_html(b, soup)",
              "else:",
              "    b.add_pairs(X.html_pairs(section))",
              "    b.add_feature_list(X.html_feature_items(soup.find(\"main\") or soup))"]
    else:
        s += ["X.apply_html(b, soup)   # label/value pairs and equipment lists anywhere in <main>"]
    s += ["",
          "title = soup.find(\"h1\") or soup.find(\"title\")",
          "if title:",
          "    b.add_title(title.get_text(\" \", strip=True))",
          "desc = soup.find(\"meta\", attrs={\"name\": \"description\"})",
          "if desc and desc.get(\"content\"):",
          "    b.add_free_text(desc[\"content\"])"]
    if pr.unmapped:
        s += ["",
              "# TODO: labels on the sample pages that don't map to the schema yet. If one matters, add",
              "# a synonym to mapping.LABEL_RULES / FEATURE_PATTERNS (with a test) or handle it here.",
              *[f"#   {label}" for label in list(pr.unmapped)[:15]]]
    return ["        " + line if line else "" for line in s]


def _findings(pr: SiteProbe) -> str:
    d = pr.discovery
    spec = {"selector": f"CSS {pr.spec[1]!r}", "heading": f"heading {pr.spec[1]!r}"}[pr.spec[0]] if pr.spec \
        else "none found, reads the whole page"
    lines = [
        f"* Discovery: {d.description}, detail URLs like {d.group.pattern} "
        f"({len(d.group.urls)} seen while probing).",
        f"* Detail page: JSON-LD Car: {'yes' if pr.has_jsonld else 'no'}; "
        f"embedded JSON specs: {'yes' if pr.has_embedded else 'no'}; spec section: {spec}.",
        *[f"* {n}" for n in pr.notes],
        *[f"* Warning: {w}" for w in pr.warnings],
    ]
    return "\n".join(lines)


def render_module(pr: SiteProbe) -> str:
    title = pr.base_url.split("://", 1)[1] + (f" ({pr.country})" if pr.country else "") + f" — {pr.base_url}"
    return MODULE_TEMPLATE.substitute(
        title=title, today=date.today().isoformat(), source_url=pr.url, findings=_findings(pr),
        cls=pr.class_name, attrs="\n".join(_attr_lines(pr)), steps="\n".join(_step_lines(pr)),
    )


def render_test(pr: SiteProbe, url: str, listing_id: str, rec: VehicleRecord) -> str:
    data = rec.model_dump(exclude={"scraped_at", "parse_warnings"})
    expected = "\n".join(f"    {k!r}: {v!r}," for k, v in data.items() if v is not None)
    route = urlparse(url).path or url
    return TEST_TEMPLATE.substitute(
        name=pr.name, cls=pr.class_name, today=date.today().isoformat(), url=repr(url),
        expected=expected, route=repr(route), listing_id=repr(listing_id),
    )


class _StaticClient:
    """Serves already-fetched pages so the generated module can be tried without the network."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.session = type("S", (), {"headers": {}})()
        self.robots_exempt: set[str] = set()

    def get(self, url: str, **kw) -> Response:
        return Response(url, 200, self.pages[url], {})

    def render(self, url: str, wait_selector: Optional[str] = None, **kw) -> Response:
        return self.get(url)

    def close(self) -> None:
        pass


def load_module_class(source: str, name: str):
    """Execute generated module source and return its scraper class, leaving REGISTRY as it was."""
    mod = types.ModuleType(f"vehicle_scraper.sites._scaffold_{name}")
    mod.__package__ = "vehicle_scraper.sites"
    before = REGISTRY.get(name)
    try:
        exec(compile(source, f"<scaffold {name}>", "exec"), mod.__dict__)
        return REGISTRY[name]
    finally:
        if before is None:
            REGISTRY.pop(name, None)
        else:
            REGISTRY[name] = before


def scaffold_site(url: str, *, client, cfg: Settings, name: Optional[str] = None,
                  country: Optional[str] = None, currency: Optional[str] = None,
                  browser: bool = False) -> Scaffold:
    """Probe ``url`` and render the scraper module, fixture and test (nothing is written)."""
    pr = probe_site(url, client=client, name=name, country=country, currency=currency, browser=browser)
    module_src = render_module(pr)
    cls = load_module_class(module_src, pr.name)
    preview_cfg = dataclasses.replace(cfg, use_browser=False, request_delay_s=0)
    id_rx = re.compile(pr.discovery.group.id_pattern)
    results: list[tuple[str, Optional[VehicleRecord], str]] = []
    for su, html in pr.samples:
        m = id_rx.search(su.split("?")[0])
        listing_id = m.group(1) if m else su.rstrip("/").rsplit("/", 1)[-1]
        try:
            rec = cls(preview_cfg, client=_StaticClient({su: html})).parse(Listing(listing_id, su))
            results.append((su, rec, ""))
        except Exception as e:  # noqa: BLE001 - reported to the user, not fatal per sample
            results.append((su, None, f"{type(e).__name__}: {e}"))
    good = [(u, r) for u, r, _ in results if r is not None]
    if not good:
        raise ScaffoldError(f"the generated parser failed on every sample: {results[0][2]}")
    url0, rec0 = good[0]
    html0 = dict(pr.samples)[url0]
    test_src = render_test(pr, url0, rec0.listing_id, rec0)
    return Scaffold(pr, module_src, test_src, html0, rec0, results)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _with_import(init_text: str, name: str) -> str:
    m = re.search(r"^from \. import ([\w, ]+?)(\s+# noqa.*)?$", init_text, re.M)
    if not m:
        raise ScaffoldError("could not find the 'from . import ...' line in sites/__init__.py")
    mods = sorted({x.strip() for x in m.group(1).split(",") if x.strip()} | {name})
    line = f"from . import {', '.join(mods)}{m.group(2) or ''}"
    return init_text[:m.start()] + line + init_text[m.end():]


def write_scaffold(sc: Scaffold, sites_dir: Path = SITES_DIR, tests_dir: Optional[Path] = TESTS_DIR) -> list[Path]:
    name = sc.probe.name
    init = sites_dir / "__init__.py"
    init_text = _with_import(init.read_text(encoding="utf-8"), name)   # fail before writing anything
    files = {sites_dir / f"{name}.py": sc.module_src}
    if tests_dir is not None:
        files[tests_dir / "fixtures" / f"{name}_detail.html"] = sc.fixture_html
        files[tests_dir / f"test_site_{name}.py"] = sc.test_src
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    init.write_text(init_text, encoding="utf-8", newline="\n")
    return [*files, init]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def format_report(sc: Scaffold) -> str:
    pr, d = sc.probe, sc.probe.discovery
    out = [
        f"Site:        {pr.name}  ({pr.base_url}, country {pr.country or '?'}, currency {pr.currency or 'from site'})",
        f"Discovery:   {d.description}",
        f"             detail URLs {d.group.pattern}  ({len(d.group.urls)} seen)",
        f"             id_pattern {d.group.id_pattern}",
    ]
    for alt in d.alternatives:
        out.append(f"             other URL shape: {alt.pattern}  ({len(alt.urls)} seen)")
    spec = f"{pr.spec[0]} {pr.spec[1]!r}" if pr.spec else "whole page"
    out.append(f"Parsing:     JSON-LD {'yes' if pr.has_jsonld else 'no'} | embedded JSON "
               f"{'yes' if pr.has_embedded else 'no'} | spec section: {spec}")
    out.append("Samples:")
    for url, rec, err in sc.sample_results:
        if rec is None:
            out.append(f"  {url}\n      parse failed: {err}")
            continue
        filled = [f for f in SCHEMA_FIELDS if getattr(rec, f) is not None]
        extras = [f for f in ("price", "currency", "mileage_km") if getattr(rec, f) is not None]
        out.append(f"  {url}\n      {len(filled)}/{len(SCHEMA_FIELDS)} schema fields + {', '.join(extras) or 'no price/mileage'}: "
                   f"{', '.join(filled)}")
        for w in rec.parse_warnings:
            out.append(f"      parse warning: {w}")
    if pr.unmapped:
        out.append("Unmapped labels (add to mapping.LABEL_RULES / FEATURE_PATTERNS if they matter):")
        out += [f"  {k} = {v}" for k, v in list(pr.unmapped.items())[:25]]
    for n in pr.notes:
        out.append(f"Note:        {n}")
    for w in pr.warnings:
        out.append(f"Warning:     {w}")
    return "\n".join(out)


def cli_new_site(args) -> int:
    from .config import settings
    from .http import BlockedError, PoliteClient

    name = args.name or site_name(urlparse(args.url).netloc)
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        print(f"Invalid site name {name!r}: use lowercase letters, digits and underscores (--name).")
        return 1
    if not args.force and (name in REGISTRY or (SITES_DIR / f"{name}.py").exists()):
        print(f"A site named {name!r} already exists. Choose another --name, or --force to overwrite.")
        return 1
    if args.browser:
        settings.use_browser = True
    client = PoliteClient(settings)
    try:
        sc = scaffold_site(args.url, client=client, cfg=settings, name=name, country=args.country,
                           currency=args.currency, browser=args.browser)
    except (BlockedError, DisallowedError) as e:
        print(f"Stopped: {e}\nNothing was generated. The scraper doesn't bypass anti-bot walls or robots.txt.")
        return 2
    except ScaffoldError as e:
        print(f"Could not scaffold {args.url}: {e}")
        return 1
    finally:
        client.close()

    print(format_report(sc))
    if args.dry_run:
        print(f"\n--- sites/{name}.py " + "-" * 50 + f"\n{sc.module_src}")
        print(f"--- tests/test_site_{name}.py " + "-" * 40 + f"\n{sc.test_src}")
        print(f"(dry run: nothing written; fixture would be {len(sc.fixture_html):,} bytes)")
        return 0
    tests_dir = TESTS_DIR if (TESTS_DIR / "conftest.py").exists() else None
    paths = write_scaffold(sc, SITES_DIR, tests_dir)
    print("\nWrote:")
    for path in paths:
        print(f"  {path}")
    print(f"""
Next steps:
  1. Review the fixture for personal data before committing it (contact details are blanked).
  2. PYTHONPATH=src python -m vehicle_scraper run --site {name} --limit 5 -v
  3. Check data/coverage.csv and parse_warnings, then refine parse() in sites/{name}.py.
  4. python -m pytest tests/test_site_{name}.py""")
    return 0
