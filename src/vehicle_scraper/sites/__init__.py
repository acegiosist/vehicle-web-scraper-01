"""Site scrapers. Importing this package registers all built-in sites."""
from __future__ import annotations

from pathlib import Path

import yaml

from . import carroya, cars24, chileautos, cofino, tucarro  # noqa: F401  (registers sites)
from .base import REGISTRY, Listing, SiteScraper, register
from .html_site import GenericScraper, HtmlSiteScraper


def load_yaml_sites(path: Path) -> list[str]:
    """Register extra sites from a YAML file (see config/sites.yaml)."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    added = []
    for entry in data.get("sites") or []:
        if entry.get("enabled", True) is False:
            continue
        cls = GenericScraper.from_config(entry)
        REGISTRY[entry["name"]] = cls
        added.append(entry["name"])
    return added


__all__ = ["REGISTRY", "Listing", "SiteScraper", "register", "GenericScraper", "HtmlSiteScraper", "load_yaml_sites"]
