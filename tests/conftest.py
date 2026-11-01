"""Shared test setup."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _windows_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests describe the Windows catalogue (faster-whisper ids); the Mac one is tested in
    tests/unit/test_macos.py with an explicit platform. Pin the Windows view on any system."""
    from localdub import config
    from localdub.core.modelmgr import catalog

    monkeypatch.setattr(catalog, "PLATFORM", "win32")
    monkeypatch.setattr(config, "DEFAULT_ASR_ID", "whisper-large-v3")
