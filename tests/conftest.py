"""Shared test setup."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True, scope="session")
def _windows_catalogue() -> Iterator[None]:
    """Most tests describe the Windows catalogue (faster-whisper ids); the Mac one is tested in
    tests/unit/test_macos.py with an explicit platform. Pin the Windows view on any system, before
    any module-level fixture builds its settings."""
    from localdub import config
    from localdub.core.modelmgr import catalog

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(catalog, "PLATFORM", "win32")
        mp.setattr(config, "DEFAULT_ASR_ID", "whisper-large-v3")
        yield
