"""Spending limit for Claude batches, per day / week / month.

``KB_AI_BUDGET_USD`` (the limit) and ``KB_AI_BUDGET_PERIOD`` (daily, weekly or monthly; default
daily) live in the repository's .env and are re-read on every check (settings.env_setting).
Without a valid limit nothing is sent. A run counts in the period it was submitted in, with its
real cost once collected (``ai_run.actual_cost_usd``) and its estimate until then.

Every submission goes through ``commands.ai_submit``, which checks the budget under the writer
lock: the CLI and the website's worker share it, so two submissions can't overrun it together.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .settings import env_setting

LIMIT_ENV = "KB_AI_BUDGET_USD"
PERIOD_ENV = "KB_AI_BUDGET_PERIOD"
PERIODS = {"daily": "hoy", "weekly": "esta semana", "monthly": "este mes"}
EPS = 1e-9


def period_bounds(period: str, now: datetime) -> tuple[datetime, datetime]:
    """Start and end of the period containing ``now`` (an aware datetime, the worker's local
    time): the day from 00:00, the week from Monday, the month from the 1st."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "daily":
        return day, day + timedelta(days=1)
    if period == "weekly":
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=7)
    start = day.replace(day=1)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end


@dataclass
class Budget:
    limit_usd: Optional[float]
    period: str
    period_start: datetime
    resets_at: datetime
    spent_usd: float
    error: Optional[str] = None     # the limit or the period in .env is missing or invalid

    @property
    def remaining_usd(self) -> Optional[float]:
        return None if self.limit_usd is None else max(0.0, self.limit_usd - self.spent_usd)

    def refusal(self, cost: float) -> Optional[str]:
        """Why a submission costing ``cost`` must not be sent (None: it fits)."""
        if self.error:
            return f"No se puede enviar a Claude: {self.error}"
        if self.spent_usd + cost > self.limit_usd + EPS:
            return (f"Se superó el límite de gasto en IA: llevas US${self.spent_usd:.2f} de "
                    f"US${self.limit_usd:.2f} {PERIODS[self.period]} y este envío costaría US${cost:.2f}. "
                    f"Se reinicia el {self.resets_at:%d/%m %H:%M}.")
        return None

    def as_json(self, cost: Optional[float] = None) -> dict:
        """What the website needs to show the budget and block the send button."""
        message = self.refusal(cost) if cost is not None else None
        return {"limit_usd": self.limit_usd, "period": self.period,
                "period_start": self.period_start.isoformat(), "resets_at": self.resets_at.isoformat(),
                "spent_usd": round(self.spent_usd, 4), "remaining_usd": self.remaining_usd,
                "allows": cost is not None and message is None, "error": self.error, "message": message}

    def describe(self) -> str:
        if self.error:
            return f"Budget: {self.error}"
        return (f"Budget: US${self.spent_usd:.2f} spent of US${self.limit_usd:.2f} ({self.period}), "
                f"resets {self.resets_at:%Y-%m-%d %H:%M}")


def _settings() -> tuple[Optional[float], str, Optional[str]]:
    period = (env_setting(PERIOD_ENV) or "daily").lower()
    if period not in PERIODS:
        return None, "daily", f"{PERIOD_ENV}={period!r} no es válido (usa daily, weekly o monthly)."
    raw = env_setting(LIMIT_ENV)
    if not raw:
        return None, period, (f"falta {LIMIT_ENV} en el .env (el límite de gasto en IA por periodo, "
                              f"por ejemplo {LIMIT_ENV}=5).")
    try:
        limit = float(raw)
    except ValueError:
        limit = -1.0
    if not 0 <= limit < 1e7:
        return None, period, f"{LIMIT_ENV}={raw!r} no es un monto válido en dólares."
    return limit, period, None


def spent_since(conn, start: datetime) -> float:
    row = conn.execute("""SELECT COALESCE(SUM(COALESCE(actual_cost_usd, est_cost_usd)), 0) AS usd
                          FROM kb.ai_run WHERE submitted_at >= %s""", (start,)).fetchone()
    return float(row["usd"])


def budget_status(conn, now: Optional[datetime] = None) -> Budget:
    limit, period, error = _settings()
    now = now or datetime.now().astimezone()
    start, end = period_bounds(period, now)
    return Budget(limit, period, start, end, spent_since(conn, start), error)
