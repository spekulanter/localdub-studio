"""The AI models page: what exists, downloads, updates, selection and deleting."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException

from localdub import extras
from localdub.api.common import AppContext
from localdub.core.modelmgr.handlers import ModelError, NotDeletable


def build(ctx: AppContext) -> APIRouter:
    router = APIRouter()
    mgr, db = ctx.mgr, ctx.db

    def model_failure(exc: Exception) -> HTTPException:
        code = 409 if isinstance(exc, NotDeletable | ModelError) else 500
        return HTTPException(code, str(exc))

    @router.get("/api/models")
    async def list_models(sizes: bool = False, lang: str = "en") -> dict[str, Any]:
        return await asyncio.to_thread(lambda: mgr.snapshot(sizes=sizes, lang=lang))

    @router.post("/api/models/download", status_code=202)
    async def download_models(body: dict[str, list[str]] | None = None) -> dict[str, Any]:
        ids = (body or {}).get("ids") or mgr.required_missing()
        try:
            entries = [mgr.get(i) for i in dict.fromkeys(ids)]
        except ModelError as exc:
            raise HTTPException(422, str(exc)) from exc
        ids = sorted((e.id for e in entries), key=lambda i: i != "packages")  # packages first
        packages = extras.packages_available()
        if any(e.requirements.needs_packages for e in entries) and not (
            packages or "packages" in ids
        ):
            raise HTTPException(
                409, "These models need the optional packages: install them first (or together)."
            )
        todo = [i for i in ids if not await asyncio.to_thread(ctx.model_installed, i)]
        if "packages" in todo and db.any_active():
            raise HTTPException(
                409, "Wait for the running dubbing job to finish before installing packages."
            )
        return {"started": mgr.start(todo)}

    @router.post("/api/models/check-updates")
    async def check_model_updates() -> dict[str, Any]:
        return await asyncio.to_thread(mgr.check_updates)

    @router.post("/api/models/custom-ollama", status_code=201)
    async def add_custom_model(body: dict[str, str]) -> dict[str, Any]:
        try:
            entry = await asyncio.to_thread(mgr.add_custom_ollama, body.get("tag", ""))
        except ModelError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": entry.id}

    @router.post("/api/models/open-folder")
    async def open_models_folder(body: dict[str, str] | None = None) -> dict[str, str]:
        try:
            return {"opened": await asyncio.to_thread(mgr.open_folder, (body or {}).get("id"))}
        except ModelError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/models/storage")
    async def models_storage() -> dict[str, Any]:
        snap = await asyncio.to_thread(mgr.snapshot, sizes=True)
        return {"paths": snap["paths"], "models_bytes": snap["models_bytes"],
                "hardware": snap["hardware"]}  # fmt: skip

    @router.post("/api/models/{entry_id}/cancel")
    async def cancel_model_download(entry_id: str) -> dict[str, bool]:
        try:
            mgr.get(entry_id)
            return {"cancelled": await asyncio.to_thread(mgr.cancel, entry_id)}
        except ModelError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/models/{entry_id}/select")
    async def select_model(entry_id: str) -> dict[str, bool]:
        try:
            await asyncio.to_thread(mgr.select, entry_id)
        except ModelError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"ok": True}

    @router.post("/api/models/{entry_id}/{action}", status_code=202)
    async def model_action(entry_id: str, action: Literal["update", "repair"]) -> dict[str, Any]:
        try:
            mgr.get(entry_id)
        except ModelError as exc:
            raise HTTPException(404, str(exc)) from exc
        if db.any_active():
            raise HTTPException(409, "Wait for the running dubbing job to finish first.")
        kind = "update" if action == "update" else "redownload"
        return {"started": mgr.start([entry_id], kind)}

    @router.delete("/api/models/{entry_id}")
    async def delete_model(entry_id: str) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(mgr.delete, entry_id)
        except (ModelError, NotDeletable) as exc:
            raise model_failure(exc) from exc

    return router
