"""Jev 层从 .env / Settings 提升到进程环境的行为。"""

from __future__ import annotations

import os
from pathlib import Path

from src.modules.market.jev_news import enabled
from src.platform.runtime.config import Settings, apply_jev_env


def test_jev_settings_defaults_are_optional(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_NEWS", raising=False)

    settings = Settings(_env_file=None)

    assert settings.typesafe_api_key == ""
    assert settings.jev_news is True


def test_settings_reads_jev_keys_from_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TYPESAFE_API_KEY=from-file\nJEV_NEWS=0\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_NEWS", raising=False)

    settings = Settings(_env_file=env_file)

    assert settings.typesafe_api_key == "from-file"
    assert settings.jev_news is False


def test_apply_jev_env_promotes_dotenv_key_into_process_env(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_NEWS", raising=False)

    apply_jev_env(Settings(_env_file=None, typesafe_api_key="sk-test", jev_news=True))

    assert os.environ["TYPESAFE_API_KEY"] == "sk-test"
    assert os.environ["JEV_NEWS"] == "1"
    assert enabled() is True


def test_apply_jev_env_promotes_off_flag(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_NEWS", raising=False)

    apply_jev_env(Settings(_env_file=None, typesafe_api_key="sk-test", jev_news=False))

    assert os.environ["JEV_NEWS"] == "0"
    assert enabled() is False


def test_apply_jev_env_does_not_override_process_env(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "from-shell")
    monkeypatch.setenv("JEV_NEWS", "1")

    apply_jev_env(Settings(_env_file=None, typesafe_api_key="from-file", jev_news=False))

    assert os.environ["TYPESAFE_API_KEY"] == "from-shell"
    assert os.environ["JEV_NEWS"] == "1"


def test_apply_jev_env_skips_blank_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("JEV_NEWS", raising=False)

    apply_jev_env(Settings(_env_file=None, typesafe_api_key="  "))

    assert "TYPESAFE_API_KEY" not in os.environ


def test_env_example_documents_jev_keys():
    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
        encoding="utf-8"
    )

    assert "TYPESAFE_API_KEY" in text
    assert "JEV_NEWS" in text
