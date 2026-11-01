"""FastAPI application: projects, jobs, progress events, segments and downloads.

The server only listens on localhost by default; all media stays on this machine. The routes live in
`localdub/api/routes/`, one module per topic; this file only puts them together.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from localdub.api.common import (  # noqa: F401 - re-exported: other modules and tests import them here
    ALLOWED_SUFFIXES,
    SOURCE_LANGS,
    AppContext,
    ProjectOut,
    safe_filename,
    separation_available,
)
from localdub.api.routes import jobs, meta, models, projects, results, segments, update
from localdub.config import Settings

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, start_queue: bool = True) -> FastAPI:
    ctx = AppContext(settings or Settings())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if start_queue:
            await asyncio.to_thread(ctx.jobs.start)
        yield
        if start_queue:
            await asyncio.to_thread(ctx.jobs.stop)
        if ctx.preview_tts is not None:
            ctx.preview_tts.close()

    app = FastAPI(title="LocalDub Studio", version="0.1.0", lifespan=lifespan)
    # what the window, the command line and the tests reach into
    app.state.ctx = ctx
    app.state.db, app.state.jobs, app.state.settings = ctx.db, ctx.jobs, ctx.settings
    app.state.models = ctx.mgr
    app.state.quit = None  # the window sets this so an update can close the program properly

    # The order matters where paths overlap: `/api/projects/from-youtube` is in `projects`.
    for module in (meta, update, models, projects, jobs, segments, results):
        app.include_router(module.build(ctx))

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app
