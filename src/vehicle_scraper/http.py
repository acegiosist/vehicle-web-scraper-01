"""Polite HTTP client: robots.txt, per-host delay, retries, block detection."""
from __future__ import annotations

import logging
import random
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from .config import Settings, settings as default_settings
from .extract import detect_block

log = logging.getLogger(__name__)


class BlockedError(RuntimeError):
    """The site served an anti-bot wall (CAPTCHA, challenge, verification)."""


class DisallowedError(RuntimeError):
    """robots.txt disallows this URL for our user agent."""


@dataclass
class Response:
    url: str
    status: int
    text: str
    headers: dict

    def json(self) -> Any:
        import json
        return json.loads(self.text)


class PoliteClient:
    def __init__(self, cfg: Settings = default_settings, extra_headers: Optional[dict] = None):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": cfg.user_agent,
            "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
            **(extra_headers or {}),
        })
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self._browser = None
        self.robots_exempt: set[str] = set()     # hosts of official, authenticated APIs

    # -- robots.txt ----------------------------------------------------------
    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        if not self.cfg.respect_robots or p.netloc in self.robots_exempt:
            return True
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.session.get(f"{base}/robots.txt", timeout=self.cfg.timeout_s)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                self._robots[base] = rp
            except requests.RequestException:
                self._robots[base] = None          # unreachable robots.txt -> allow
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.cfg.user_agent, url)

    def crawl_delay(self, url: str) -> float:
        p = urlparse(url)
        rp = self._robots.get(f"{p.scheme}://{p.netloc}")
        d = rp.crawl_delay(self.cfg.user_agent) if rp else None
        return max(float(d or 0), self.cfg.request_delay_s)

    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        wait = self.crawl_delay(url) - (time.monotonic() - self._last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.5))
        self._last_hit[host] = time.monotonic()

    # -- requests ------------------------------------------------------------
    def request(self, method: str, url: str, *, check_block: bool = True, **kw) -> Response:
        if not self.allowed(url):
            raise DisallowedError(f"robots.txt disallows {url}")
        kw.setdefault("timeout", self.cfg.timeout_s)
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.cfg.max_retries + 1):
            self._throttle(url)
            try:
                r = self.session.request(method, url, **kw)
            except requests.RequestException as e:
                last_exc = e
                log.warning("%s %s failed (%s), attempt %d", method, url, e, attempt)
            else:
                if r.status_code in (500, 502, 503, 504) and attempt < self.cfg.max_retries:
                    log.warning("HTTP %s for %s, retrying", r.status_code, url)
                elif r.status_code == 429 and attempt < self.cfg.max_retries:
                    time.sleep(float(r.headers.get("Retry-After", 30)))
                else:
                    resp = Response(r.url, r.status_code, r.text, dict(r.headers))
                    if check_block:
                        reason = detect_block(resp.status, resp.text, resp.url)
                        if reason:
                            raise BlockedError(f"{reason} at {url}")
                    if r.status_code >= 400:
                        raise requests.HTTPError(f"HTTP {r.status_code} for {url}")
                    return resp
            time.sleep(min(60, 2 ** attempt + random.random()))
        raise last_exc or RuntimeError(f"giving up on {url}")

    def get(self, url: str, **kw) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> Response:
        return self.request("POST", url, **kw)

    # -- optional headless browser ------------------------------------------
    def render(self, url: str, wait_selector: Optional[str] = None, wait_ms: int = 2500) -> Response:
        """Load a JS-rendered page with Playwright (only if USE_BROWSER=true)."""
        if not self.allowed(url):
            raise DisallowedError(f"robots.txt disallows {url}")
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self.cfg.headless)
            self._page = self._browser.new_page(user_agent=self.cfg.user_agent, locale="es-419")
        self._throttle(url)
        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=self.cfg.timeout_s * 1000)
        if wait_selector:
            try:
                self._page.wait_for_selector(wait_selector, timeout=10000)
            except Exception:  # noqa: BLE001 - selector is a best-effort hint
                pass
        self._page.wait_for_timeout(wait_ms)
        out = Response(self._page.url, resp.status if resp else 0, self._page.content(), {})
        reason = detect_block(out.status, out.text, out.url)
        if reason:
            raise BlockedError(f"{reason} at {url}")
        return out

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._pw.stop()
            self._browser = None
        self.session.close()
