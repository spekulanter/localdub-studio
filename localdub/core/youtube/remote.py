"""Connects a project that came from a YouTube link to the pipeline's download stage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from localdub.config import Settings
from localdub.core.media.ffmpeg import find_tool
from localdub.core.youtube import ytdlp
from localdub.pipeline import RemoteSource


def make_remote(project: dict[str, Any], settings: Settings) -> RemoteSource:
    url = str(project["source_url"])
    quality = str(project["download_quality"] or "auto")
    cookies = str(project["cookies_browser"] or "none")

    def fetch(dest: Path, say: Any) -> None:
        ffmpeg = find_tool("ffmpeg", settings.ffmpeg_path).parent

        def on_progress(percent: float | None, speed: str | None, message: str | None) -> None:
            if percent is not None:
                say(f"{percent:.1f}%" + (f" - {speed}" if speed else ""))
            elif message:
                say(message)

        try:
            ytdlp.download(url, dest, quality, cookies, ffmpeg, on_progress)
        except ytdlp.YoutubeError as exc:
            raise RuntimeError(str(exc)) from exc

    return RemoteSource(key=json.dumps([url, quality, cookies]), fetch=fetch)
