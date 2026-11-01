"""Liveness, health, options, the user's own settings and starting Ollama."""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

from fastapi import APIRouter, HTTPException

from localdub.api.common import SOURCE_LANGS, AppContext, SettingsPatch, separation_available
from localdub.core import usersettings
from localdub.core.translation import ollama_setup
from localdub.core.translation.ollama_provider import cached_tags, forget_tags
from localdub.core.tts.base import VOICES
from localdub.pipeline import STAGES


def build(ctx: AppContext) -> APIRouter:
    router = APIRouter()
    settings = ctx.settings

    @router.get("/api/ping")
    def ping() -> dict[str, bool]:
        """Cheap liveness check with no external dependencies (used by the window and launcher)."""
        return {"ok": True}

    @router.get("/api/health")
    def health() -> dict[str, Any]:
        tags, error = cached_tags(settings.ollama_url)
        models = sorted(m["name"] for m in tags or [])
        return {
            "ok": True,
            "ollama": {
                "reachable": error is None,
                "error": error,
                "models": models,
                "installed": error is None or ollama_setup.is_present(),
            },
        }

    @router.post("/api/ollama/start")
    async def start_ollama() -> dict[str, bool]:
        """Start Ollama (if it is installed) and wait until it answers."""
        if not ollama_setup.is_present():
            raise HTTPException(409, "Ollama is not installed. Install it on the AI models page.")
        try:
            ok = await asyncio.to_thread(ollama_setup.ensure_running, settings.ollama_url)
        except ollama_setup.OllamaSetupError as exc:
            raise HTTPException(409, str(exc)) from exc
        forget_tags()
        return {"reachable": ok}

    @router.get("/api/options")
    def options(lang: str = "en") -> dict[str, Any]:
        return {
            "voices": VOICES,
            "source_languages": SOURCE_LANGS,
            "target_language": "sk",
            "default_voice": settings.tts_voice,
            "default_llm": ctx.default_llm(),
            "default_asr": ctx.asr_choice(""),
            "asr_choices": ctx.mgr.choices("asr", lang),
            "translation_choices": ctx.mgr.choices("translation", lang),
            "stages": STAGES,
            "max_upload_mb": settings.max_upload_mb,
            "default_max_upload_mb": ctx.default_upload_mb,
            "free_disk_mb": shutil.disk_usage(settings.data_dir).free // (1024 * 1024),
            "separation_available": separation_available(),
        }

    @router.put("/api/settings")
    def put_settings(body: SettingsPatch) -> dict[str, Any]:
        """Change the upload limit; null puts the default back."""
        value = body.max_upload_mb
        if value is not None and not usersettings.valid_upload_mb(value):
            raise HTTPException(
                422,
                f"Limit must be between {usersettings.MIN_UPLOAD_MB} and "
                f"{usersettings.MAX_UPLOAD_MB} MB",
            )
        settings.max_upload_mb = ctx.default_upload_mb if value is None else value
        usersettings.save(ctx.user_settings_path, {} if value is None else {"max_upload_mb": value})
        return {
            "max_upload_mb": settings.max_upload_mb,
            "default_max_upload_mb": ctx.default_upload_mb,
        }

    return router
