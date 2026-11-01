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
    from localdub.core.translation import ollama_setup

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(catalog, "PLATFORM", "win32")
        mp.setattr(config, "DEFAULT_ASR_ID", "whisper-large-v3")
        # the CI machines have no Ollama; tests that care say so themselves
        mp.setattr(ollama_setup, "is_present", lambda: True)
        yield


@pytest.fixture(autouse=True)
def _fresh_ollama_answers() -> None:
    """The short-lived shared answer about Ollama's models must not leak from one test to the next."""
    from localdub.core.translation.ollama_provider import forget_tags

    forget_tags()
