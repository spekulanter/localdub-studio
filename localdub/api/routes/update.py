"""Looking for a newer release, downloading it and handing over to its installer."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from localdub.api.common import AppContext, InstallBody
from localdub.core import updates

log = logging.getLogger(__name__)
CHECK_EVERY_S = 6 * 3600


class UpdateService:
    """What is known about a newer version, and the progress of its download (thread-safe)."""

    def __init__(self, data_dir: Path) -> None:
        self._lock = threading.Lock()
        self._folder = data_dir / "updates"
        self._checked = 0.0
        self._update: updates.Update | None = None
        self._error: str | None = None
        self._download: dict[str, Any] = {"status": "idle", "done": 0, "total": 0, "error": None}
        self._file: Path | None = None

    def view(self) -> dict[str, Any]:
        with self._lock:
            u = self._update
            return {
                "current": updates.current_version(),
                "available": u is not None,
                "version": u.version if u else None,
                "notes": u.notes if u else None,
                "page": u.page if u else None,
                "asset": u.asset if u else None,
                "size": u.size if u else None,
                "error": self._error,
                "download": dict(self._download),
            }

    def _due(self, refresh: bool) -> bool:
        with self._lock:
            busy = self._download["status"] in ("running", "ready")
            return not busy and (refresh or time.time() - self._checked > CHECK_EVERY_S)

    def refresh(self, force: bool) -> None:
        """Ask GitHub, at most every 6 hours unless forced. Blocking (network)."""
        if not self._due(force):
            return
        try:
            found, error = updates.check(), None
        except updates.UpdateError as exc:
            found, error = None, str(exc)
        with self._lock:
            self._update, self._error, self._checked = found, error, time.time()

    def start_download(self) -> bool:
        """Begin downloading in the background. False if there is nothing to download."""
        with self._lock:
            u = self._update
            if u is None:
                return False
            if self._download["status"] == "running":
                return True
            self._download = {"status": "running", "done": 0, "total": u.size, "error": None}
        threading.Thread(target=self._work, args=(u,), name="update-download", daemon=True).start()
        return True

    def _work(self, u: updates.Update) -> None:
        def progress(done: int, total: int) -> None:
            with self._lock:
                self._download.update(done=done, total=total or u.size)

        try:
            path = updates.download(u, self._folder, progress)
            with self._lock:
                self._file = path
                self._download["status"] = "ready"
        except updates.UpdateError as exc:
            with self._lock:
                self._download.update(status="error", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - shown to the user, never silent
            log.exception("Update download failed")
            with self._lock:
                self._download.update(status="error", error=f"{type(exc).__name__}: {exc}")

    def ready_file(self) -> Path | None:
        with self._lock:
            path = self._file
            ok = self._download["status"] == "ready" and path is not None and path.is_file()
        return path if ok else None


def build(ctx: AppContext, service: UpdateService | None = None) -> APIRouter:
    router = APIRouter()
    svc = service or UpdateService(ctx.settings.data_dir)

    @router.get("/api/update")
    async def get_update(refresh: bool = False) -> dict[str, Any]:
        """Is there a newer normal release? Looked up at most every 6 hours (or when asked)."""
        await asyncio.to_thread(svc.refresh, refresh)
        return svc.view()

    @router.post("/api/update/download", status_code=202)
    def start_update_download() -> dict[str, Any]:
        if not svc.start_download():
            raise HTTPException(409, "There is no newer version to download.")
        return svc.view()

    @router.post("/api/update/install")
    def install_update(body: InstallBody, request: Request) -> dict[str, bool]:
        """Start the downloaded installer, then close the program so it can replace it."""
        path = svc.ready_file()
        if path is None:
            raise HTTPException(409, "The update has not been downloaded yet.")
        if ctx.db.any_active() and not body.force:
            raise HTTPException(
                409,
                "A dubbing job is running or waiting. It is paused and continues after the update.",
            )
        try:
            updates.launch_installer(path)
        except updates.UpdateError as exc:
            raise HTTPException(409, str(exc)) from exc
        state = request.app.state

        def leave() -> None:
            if state.quit is not None:
                state.quit()
            else:
                os._exit(0)  # a server without a window (the browser fallback)

        threading.Timer(1.5, leave).start()  # let this answer reach the page first
        return {"closing": True}

    return router
