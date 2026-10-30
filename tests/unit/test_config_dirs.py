from __future__ import annotations

from pathlib import Path

from localdub import config
from localdub.config import Settings


def test_source_checkout_keeps_data_next_to_the_code(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "INSTALLED_MARKER", tmp_path / "missing")
    s = Settings()
    assert s.data_dir == config.REPO_ROOT / "data"
    assert s.models_dir == config.REPO_ROOT / "models"


def test_installed_copy_uses_localappdata(monkeypatch, tmp_path):
    marker = tmp_path / ".installed"
    marker.write_text("setup", encoding="utf-8")
    monkeypatch.setattr(config, "INSTALLED_MARKER", marker)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    s = Settings()
    assert s.data_dir == tmp_path / "Local" / "LocalDub Studio" / "data"
    assert s.models_dir == tmp_path / "Local" / "LocalDub Studio" / "models"


def test_environment_overrides_still_win(monkeypatch, tmp_path):
    marker = tmp_path / ".installed"
    marker.write_text("setup", encoding="utf-8")
    monkeypatch.setattr(config, "INSTALLED_MARKER", marker)
    monkeypatch.setenv("LOCALDUB_DATA_DIR", str(tmp_path / "mine"))
    assert Settings().data_dir == Path(tmp_path / "mine")
