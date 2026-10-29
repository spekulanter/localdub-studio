from __future__ import annotations

import sys
from pathlib import Path

import pytest

from localdub.core.media import ffmpeg
from localdub.core.media.ffmpeg import MediaError, find_tool


def test_configured_path_wins_and_must_exist(tmp_path: Path):
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"")
    assert find_tool("tool", exe) == exe
    with pytest.raises(MediaError, match="not found at"):
        find_tool("tool", tmp_path / "missing.exe")


def test_falls_back_to_the_fresh_registry_path(monkeypatch, tmp_path: Path):
    exe = tmp_path / "faketool.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name, path=None: str(exe) if path else None)
    monkeypatch.setattr(ffmpeg, "_which_fresh", lambda name: str(exe))
    assert find_tool("faketool") == exe


def test_missing_tool_gives_install_hint(monkeypatch):
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name, path=None: None)
    monkeypatch.setattr(ffmpeg, "_which_fresh", lambda name: None)
    with pytest.raises(MediaError, match="winget install Gyan.FFmpeg"):
        find_tool("ffmpeg")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry")
def test_fresh_path_finds_a_system_tool():
    assert ffmpeg._which_fresh("cmd") is not None
