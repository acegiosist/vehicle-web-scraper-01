from __future__ import annotations

import json
from pathlib import Path

import pytest

from vehicle_scraper.config import Settings
from vehicle_scraper.http import Response

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    """Stands in for PoliteClient: serves fixture files by URL substring."""

    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.calls: list[tuple[str, str]] = []
        self.session = type("S", (), {"headers": {}})()
        self.robots_exempt: set[str] = set()

    def _serve(self, method: str, url: str) -> Response:
        self.calls.append((method, url))
        for key, path in self.routes.items():
            if key in url:
                return Response(url, 200, (FIXTURES / path).read_text(encoding="utf-8"), {})
        raise AssertionError(f"unexpected request {method} {url}")

    def get(self, url, **kw):
        return self._serve("GET", url)

    def post(self, url, **kw):
        return self._serve("POST", url)

    def close(self):
        pass


@pytest.fixture
def cfg(tmp_path):
    return Settings(data_dir=tmp_path, request_delay_s=0)


@pytest.fixture
def fixture_json():
    return lambda name: json.loads((FIXTURES / name).read_text(encoding="utf-8"))
