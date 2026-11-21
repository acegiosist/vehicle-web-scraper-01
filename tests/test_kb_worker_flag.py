"""The worker's switch for sending batches to Claude from the website is re-read from .env on
every submission, so turning it on or off needs no restart (no database needed here)."""
import pytest

pytest.importorskip("psycopg")

from vehicle_scraper.kb import settings, worker


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(settings, "ENV_FILE", str(path))
    monkeypatch.delenv(worker.AI_SUBMIT_ENV, raising=False)
    return path


def test_switch_follows_the_env_file_without_restart(env_file):
    env_file.write_text("OTHER=1\nKB_ALLOW_WEB_AI_SUBMIT=true\n", encoding="utf-8")
    assert worker.ai_submit_allowed() is True
    env_file.write_text("OTHER=1\nKB_ALLOW_WEB_AI_SUBMIT=false\n", encoding="utf-8")
    assert worker.ai_submit_allowed() is False
    env_file.write_text("KB_ALLOW_WEB_AI_SUBMIT=Yes\n", encoding="utf-8")
    assert worker.ai_submit_allowed() is True


def test_env_file_wins_over_the_environment(env_file, monkeypatch):
    monkeypatch.setenv(worker.AI_SUBMIT_ENV, "true")       # what .env had when the worker started
    env_file.write_text("KB_ALLOW_WEB_AI_SUBMIT=\n", encoding="utf-8")   # switched off since
    assert worker.ai_submit_allowed() is False


def test_without_the_key_in_env_file_the_environment_decides(env_file, monkeypatch):
    env_file.write_text("OTHER=1\n", encoding="utf-8")
    assert worker.ai_submit_allowed() is False
    monkeypatch.setenv(worker.AI_SUBMIT_ENV, "true")
    assert worker.ai_submit_allowed() is True


def test_missing_env_file_falls_back_to_the_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv(worker.AI_SUBMIT_ENV, "1")
    assert worker.ai_submit_allowed() is True
