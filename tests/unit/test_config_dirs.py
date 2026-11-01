from __future__ import annotations

import sys
from pathlib import Path

from localdub import paths
from localdub.config import Settings


def test_source_checkout_keeps_data_next_to_the_code(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "INSTALLED_MARKER", tmp_path / "missing")
    s = Settings()
    assert s.data_dir == paths.REPO_ROOT / "data"
    assert s.models_dir == paths.REPO_ROOT / "models"


def test_installed_copy_uses_the_users_own_folder(monkeypatch, tmp_path):
    marker = tmp_path / ".installed"
    marker.write_text("setup", encoding="utf-8")
    monkeypatch.setattr(paths, "INSTALLED_MARKER", marker)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("HOME", str(tmp_path / "Home"))
    root = paths.user_root()
    if sys.platform == "darwin":
        assert root == tmp_path / "Home" / "Library" / "Application Support" / "LocalDub Studio"
    else:
        assert root == tmp_path / "Local" / "LocalDub Studio"
    s = Settings()
    assert s.data_dir == root / "data"
    assert s.models_dir == root / "models"


def test_the_user_folder_on_a_mac(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.user_root() == tmp_path / "Library" / "Application Support" / "LocalDub Studio"


def test_environment_overrides_still_win(monkeypatch, tmp_path):
    marker = tmp_path / ".installed"
    marker.write_text("setup", encoding="utf-8")
    monkeypatch.setattr(paths, "INSTALLED_MARKER", marker)
    monkeypatch.setenv("LOCALDUB_DATA_DIR", str(tmp_path / "mine"))
    assert Settings().data_dir == Path(tmp_path / "mine")
