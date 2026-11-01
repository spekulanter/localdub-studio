"""The finished video, the subtitles and the source video."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from localdub.api.common import AppContext, safe_filename

SRT = "application/x-subrip"
MEDIA_TYPES = {"video": "video/mp4", "srt": SRT, "srt_en": SRT}
SUFFIXES = {"video": ".sk.mp4", "srt": ".sk.srt", "srt_en": ".en.srt"}


def build(ctx: AppContext) -> APIRouter:
    router = APIRouter()

    @router.get("/api/projects/{pid}/files/{kind}")
    def download(
        pid: int, kind: Literal["video", "srt", "srt_en"], inline: bool = False
    ) -> FileResponse:
        project = ctx.require_project(pid)
        path = ctx.output_paths(project)[kind]
        if not path.is_file():
            raise HTTPException(404, "Not generated yet")
        # named after the video (the YouTube title, or the project name), not "source"
        clean = project["name"].replace("/", "-").replace("\\", "-")
        title = safe_filename(clean, fallback="video")
        return FileResponse(
            path,
            media_type=MEDIA_TYPES[kind],
            filename=f"{title}{SUFFIXES[kind]}",
            content_disposition_type="inline" if inline else "attachment",
        )

    @router.get("/api/projects/{pid}/source")
    def source_video(pid: int) -> FileResponse:
        project = ctx.require_project(pid)
        path = ctx.project_dir(pid) / project["input_rel"]
        if not path.is_file():
            raise HTTPException(404, "The video is not there yet (it may still be downloading)")
        return FileResponse(path, filename=path.name, content_disposition_type="inline")

    return router
