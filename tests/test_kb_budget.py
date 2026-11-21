"""The AI spending limit (kb/budget.py): periods, settings re-read from .env, refusal messages.
No database: spent_since is fed by a fake connection."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

pytest.importorskip("dotenv")

from vehicle_scraper.kb import budget, settings

TZ = timezone(timedelta(hours=-5))          # the worker's local time (Bogotá)
NOW = datetime(2026, 11, 21, 15, 30, tzinfo=TZ)   # a Saturday


class FakeConn:
    def __init__(self, spent):
        self.spent, self.since = spent, None

    def execute(self, sql, params):
        self.since = params[0]
        spent = self.spent

        class Row:
            def fetchone(self):
                return {"usd": Decimal(str(spent))}
        return Row()


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings, "ENV_FILE", str(path))
    monkeypatch.delenv(budget.LIMIT_ENV, raising=False)
    monkeypatch.delenv(budget.PERIOD_ENV, raising=False)
    return path


def test_period_bounds():
    day = datetime(2026, 11, 21, tzinfo=TZ)
    assert budget.period_bounds("daily", NOW) == (day, day + timedelta(days=1))
    monday = datetime(2026, 11, 16, tzinfo=TZ)
    assert budget.period_bounds("weekly", NOW) == (monday, monday + timedelta(days=7))
    assert budget.period_bounds("monthly", NOW) == (datetime(2026, 11, 1, tzinfo=TZ), datetime(2026, 12, 1, tzinfo=TZ))
    dec = datetime(2026, 12, 31, 23, 59, tzinfo=TZ)
    assert budget.period_bounds("monthly", dec)[1] == datetime(2027, 1, 1, tzinfo=TZ)


def test_without_a_limit_nothing_is_sent(env):
    b = budget.budget_status(FakeConn(0), NOW)
    assert b.limit_usd is None and "falta KB_AI_BUDGET_USD" in b.refusal(0.01)
    env.write_text("KB_AI_BUDGET_USD=cinco\n", encoding="utf-8")
    assert "no es un monto válido" in budget.budget_status(FakeConn(0), NOW).refusal(0.01)
    env.write_text("KB_AI_BUDGET_USD=5\nKB_AI_BUDGET_PERIOD=yearly\n", encoding="utf-8")
    assert "daily, weekly o monthly" in budget.budget_status(FakeConn(0), NOW).refusal(0.01)


def test_limit_and_period_follow_the_env_file(env, monkeypatch):
    monkeypatch.setenv(budget.LIMIT_ENV, "100")            # .env wins over the environment
    env.write_text("KB_AI_BUDGET_USD=5\n", encoding="utf-8")
    conn = FakeConn(4.80)
    b = budget.budget_status(conn, NOW)
    assert (b.limit_usd, b.period, b.spent_usd) == (5.0, "daily", 4.8)
    assert conn.since == datetime(2026, 11, 21, tzinfo=TZ)                # counted from 00:00 today
    assert b.refusal(0.20) is None                                          # exactly at the limit: allowed
    msg = b.refusal(0.40)
    assert msg == ("Se superó el límite de gasto en IA: llevas US$4.80 de US$5.00 hoy y este envío costaría "
                   "US$0.40. Se reinicia el 22/11 00:00.")
    env.write_text("KB_AI_BUDGET_USD=5\nKB_AI_BUDGET_PERIOD=weekly\n", encoding="utf-8")   # no restart
    conn = FakeConn(1)
    assert budget.budget_status(conn, NOW).period == "weekly" and conn.since.day == 16


def test_json_for_the_website(env):
    env.write_text("KB_AI_BUDGET_USD=5\nKB_AI_BUDGET_PERIOD=monthly\n", encoding="utf-8")
    j = budget.budget_status(FakeConn(1.25), NOW).as_json(0.5)
    assert j["allows"] and j["remaining_usd"] == 3.75 and j["message"] is None
    assert j["period_start"] == "2026-11-01T00:00:00-05:00" and j["resets_at"] == "2026-12-01T00:00:00-05:00"
    j = budget.budget_status(FakeConn(4.9), NOW).as_json(0.5)
    assert not j["allows"] and "este mes" in j["message"]
