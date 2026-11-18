"""Settings loaded from environment variables / a .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    user_agent: str = os.getenv(
        "USER_AGENT",
        "VehicleScraper/1.0 (+contact: you@example.com) Mozilla/5.0 (compatible)",
    )
    request_delay_s: float = float(os.getenv("REQUEST_DELAY_SECONDS", "2.0"))
    timeout_s: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    respect_robots: bool = _bool("RESPECT_ROBOTS_TXT", True)
    use_browser: bool = _bool("USE_BROWSER", False)          # Playwright fallback for JS pages
    headless: bool = _bool("BROWSER_HEADLESS", True)
    data_dir: Path = Path(os.getenv("DATA_DIR", "data"))
    save_raw: bool = _bool("SAVE_RAW", False)                  # keep raw HTML/JSON for debugging
    # Mercado Libre (TuCarro) official API
    ml_access_token: str = os.getenv("ML_ACCESS_TOKEN", "")
    ml_site_id: str = os.getenv("ML_SITE_ID", "MCO")           # MCO = Colombia, MLV = Venezuela
    extra: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vehicles.sqlite"


settings = Settings()
