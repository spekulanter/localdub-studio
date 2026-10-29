"""Translation through a local Ollama server."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from localdub.core.timeline.models import DialogueSegment
from localdub.core.translation.prompts import (
    TRANSLATION_SCHEMA,
    ContextLine,
    PromptProfile,
    char_budget,
    clean_translation,
    generic_messages,
    profile_for_model,
    shorten_messages,
    translategemma_messages,
)

log = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: float = 300.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout)

    @property
    def is_local(self) -> bool:
        return urlparse(self.base_url).hostname in {"127.0.0.1", "localhost", "::1"}

    def list_models(self) -> list[str]:
        try:
            r = self._http.get("/api/tags")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Cannot reach Ollama at {self.base_url} ({exc}). Is Ollama installed and running?"
            ) from exc
        return sorted(m["name"] for m in r.json().get("models", []))

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        format: dict[str, Any] | None = None,
        think: bool | None = None,
        options: dict[str, Any] | None = None,
        keep_alive: str | int = "5m",
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": keep_alive,
            "options": options or {},
        }
        if format is not None:
            body["format"] = format
        if think is not None:
            body["think"] = think
        try:
            r = self._http.post("/api/chat", json=body)
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc
        if r.status_code != 200:
            raise OllamaError(f"Ollama returned {r.status_code}: {r.text[:500]}")
        content: str = r.json()["message"]["content"]
        return content

    def unload(self, model: str) -> None:
        """Ask Ollama to evict the model from VRAM immediately."""
        try:
            self._http.post("/api/generate", json={"model": model, "keep_alive": 0})
        except httpx.HTTPError as exc:
            log.warning("Could not unload %s: %s", model, exc)

    def close(self) -> None:
        self._http.close()


class OllamaTranslator:
    local_only = True

    def __init__(
        self,
        client: OllamaClient,
        model: str,
        *,
        chars_per_second: float = 14.0,
        context_before: int = 2,
        context_after: int = 1,
        temperature: float = 0.2,
        budget_tolerance: float = 1.15,
    ) -> None:
        if not client.is_local:
            log.warning(
                "Ollama URL %s is not local; media text leaves this machine", client.base_url
            )
        self.client = client
        self.model = model
        self.profile = profile_for_model(model)
        self.chars_per_second = chars_per_second
        self.context_before = context_before
        self.context_after = context_after
        self.temperature = temperature
        self.budget_tolerance = budget_tolerance
        self._think: bool | None = False if "qwen3" in model.lower() else None

    def check_available(self) -> None:
        models = self.client.list_models()
        if self.model not in models:
            raise OllamaError(
                f"Model '{self.model}' is not installed in Ollama. Installed: {models or 'none'}. "
                f"Run: ollama pull {self.model}"
            )

    def _chat(self, messages: list[dict[str, str]], json_mode: bool) -> str:
        raw = self.client.chat(
            self.model,
            messages,
            format=TRANSLATION_SCHEMA if json_mode else None,
            think=self._think,
            options={"temperature": self.temperature, "num_ctx": 4096},
        )
        if not json_mode:
            return clean_translation(raw)
        try:
            return clean_translation(str(json.loads(raw)["translation"]))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise OllamaError(f"Model returned invalid JSON: {raw[:300]}") from exc

    def translate_one(
        self,
        text: str,
        *,
        source_lang: str,
        target_lang: str,
        duration_s: float,
        before: list[ContextLine],
        after: list[ContextLine],
    ) -> str:
        if self.profile is PromptProfile.TRANSLATEGEMMA:
            msgs = translategemma_messages(text, source_lang=source_lang, target_lang=target_lang)
            return self._chat(msgs, json_mode=False)

        budget = char_budget(duration_s, self.chars_per_second)
        msgs = generic_messages(
            text,
            source_lang=source_lang,
            target_lang=target_lang,
            duration_s=duration_s,
            budget=budget,
            before=before,
            after=after,
        )
        out = self._chat(msgs, json_mode=True)
        if len(out) > budget * self.budget_tolerance:
            shorter = self._chat(shorten_messages(msgs, out, budget), json_mode=True)
            if shorter and len(shorter) < len(out):
                log.debug("Shortened segment %d -> %d chars", len(out), len(shorter))
                out = shorter
        return out

    def translate_segments(
        self, segments: list[DialogueSegment], source_lang: str, target_lang: str
    ) -> list[str]:
        self.check_available()
        results: list[str] = []
        t0 = time.perf_counter()
        for i, seg in enumerate(segments):
            before = [
                ContextLine(s.source_text, results[j])
                for j, s in enumerate(segments)
                if i - self.context_before <= j < i
            ]
            after = [
                ContextLine(s.source_text) for s in segments[i + 1 : i + 1 + self.context_after]
            ]
            out = self.translate_one(
                seg.source_text,
                source_lang=source_lang,
                target_lang=target_lang,
                duration_s=seg.duration,
                before=before,
                after=after,
            )
            if not out:
                raise OllamaError(f"Empty translation for segment {seg.id}: {seg.source_text!r}")
            log.info("[%d/%d] %s -> %s", i + 1, len(segments), seg.source_text, out)
            results.append(out)
        log.info("Translated %d segments in %.1fs", len(segments), time.perf_counter() - t0)
        return results

    def close(self) -> None:
        self.client.unload(self.model)
        self.client.close()
