"""Benchmark installed Ollama translation models on a fixed EN-to-SK dialogue set."""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from localdub.config import Settings
from localdub.core.platform import disable_power_throttling
from localdub.core.timeline.models import DialogueSegment
from localdub.core.translation.ollama_provider import OllamaClient, OllamaTranslator
from localdub.core.translation.prompts import ContextLine, char_budget

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REPORT = _ROOT / "docs" / "translation_benchmark.md"


def _test_segments() -> list[DialogueSegment]:
    lines = [
        (0.00, 2.00, "Mira called before the show."),
        (2.05, 4.30, "She said she was nervous."),
        (4.35, 6.30, "Tell her to break a leg!"),
        (6.35, 7.50, "It's raining cats and dogs."),
        (7.55, 9.00, "I left my umbrella at home."),
        (9.05, 10.50, "No problem, Alex has a spare."),
        (10.55, 12.40, "The train leaves at 8:15."),
        (12.45, 14.20, "Are we still meeting at the station?"),
        (14.25, 15.20, "Absolutely."),
        (15.25, 17.20, "Don't let the cat out of the bag."),
        (17.25, 19.40, "I promise I won't say a word."),
        (
            19.45,
            26.45,
            "When the lights go out, follow the blue line through the garden and wait "
            "beside the old stone fountain until the music starts.",
        ),
    ]
    return [
        DialogueSegment(id=i, start=start, end=end, source_text=text)
        for i, (start, end, text) in enumerate(lines, start=1)
    ]


@dataclass
class ModelResult:
    model: str
    total_s: float = 0.0
    translations: list[str] = field(default_factory=list)
    segment_s: list[float] = field(default_factory=list)
    error: str = ""


def _run_model(model: str, settings: Settings, segments: list[DialogueSegment]) -> ModelResult:
    result = ModelResult(model=model)
    client = OllamaClient(settings.ollama_url)
    translator: OllamaTranslator | None = None
    started = time.perf_counter()
    try:
        translator = OllamaTranslator(
            client,
            model,
            chars_per_second=settings.chars_per_second,
            context_before=settings.translation_context_before,
            context_after=settings.translation_context_after,
        )
        original = translator.translate_one

        def timed_translate_one(
            text: str,
            *,
            source_lang: str,
            target_lang: str,
            duration_s: float,
            before: list[ContextLine],
            after: list[ContextLine],
        ) -> str:
            tick = time.perf_counter()
            try:
                translation = original(
                    text,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    duration_s=duration_s,
                    before=before,
                    after=after,
                )
            finally:
                result.segment_s.append(time.perf_counter() - tick)
            result.translations.append(translation)
            return translation

        # Preserve translate_segments' real context window and provider behavior.
        translator.translate_one = timed_translate_one  # type: ignore[method-assign]
        translator.translate_segments(segments, "en", "sk")
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.total_s = time.perf_counter() - started
        try:
            if translator is not None:
                translator.close()
            else:
                client.close()
        except Exception as exc:
            cleanup_error = f"close failed: {type(exc).__name__}: {exc}"
            result.error = f"{result.error}; {cleanup_error}" if result.error else cleanup_error
    return result


def _cell_text(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _render_report(
    results: list[ModelResult], segments: list[DialogueSegment], settings: Settings
) -> str:
    budgets = [char_budget(segment.duration, settings.chars_per_second) for segment in segments]
    lines = [
        "# EN→SK translation benchmark",
        "",
        f"Characters per second: {settings.chars_per_second}",
        "",
        "## Summary",
        "",
        "| Model | Total s | Avg s/segment | Over budget | Errors |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        over = sum(
            len(text) > budget for text, budget in zip(result.translations, budgets, strict=False)
        )
        avg = result.total_s / len(segments) if segments else 0.0
        lines.append(
            f"| {_cell_text(result.model)} | {result.total_s:.2f} | {avg:.2f} | "
            f"{over} | {_cell_text(result.error) if result.error else '—'} |"
        )

    lines.extend(["", "## Segment results", ""])
    columns = ["#", "Time", "EN source", "Budget"]
    columns.extend(f"{_cell_text(result.model)} (SK)" for result in results)
    columns.append("Human rating (1-5)")
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for index, (segment, budget) in enumerate(zip(segments, budgets, strict=True)):
        cells = [
            str(segment.id),
            f"{segment.start:.2f}–{segment.end:.2f}",
            _cell_text(segment.source_text),
            str(budget),
        ]
        for result in results:
            if index >= len(result.translations):
                cells.append("—")
                continue
            translation = result.translations[index]
            over = len(translation) > budget
            marker = f" **OVER ({len(translation)})**" if over else f" ({len(translation)})"
            cells.append(_cell_text(translation) + marker)
        cells.append("")
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("## Per-segment latency")
    lines.append("")
    lines.append("| Model | " + " | ".join(str(s.id) for s in segments) + " |")
    lines.append("| " + " | ".join("---" for _ in range(len(segments) + 1)) + " |")
    for result in results:
        timings = [f"{value:.2f}" for value in result.segment_s]
        timings.extend("—" for _ in range(len(segments) - len(timings)))
        lines.append(f"| {_cell_text(result.model)} | " + " | ".join(timings) + " |")
    return "\n".join(lines) + "\n"


def _parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", help="Ollama model names to benchmark")
    parser.add_argument("--url", default=settings.ollama_url, help="Ollama base URL")
    parser.add_argument("--out", type=Path, default=_DEFAULT_REPORT, help="Markdown report path")
    parsed = parser.parse_args(args)
    parsed.settings = settings
    return parsed


def main(args: Sequence[str] | None = None) -> int:
    disable_power_throttling()
    parsed = _parse_args(args)
    settings: Settings = parsed.settings
    settings.ollama_url = parsed.url
    if parsed.models:
        models = parsed.models
    else:
        client = OllamaClient(settings.ollama_url)
        try:
            installed = client.list_models()
        finally:
            client.close()
        models = [
            name for name in installed if name.lower().startswith(("translategemma", "qwen3"))
        ]

    segments = _test_segments()
    results = [_run_model(model, settings, segments) for model in models]
    report = _render_report(results, segments, settings)
    parsed.out.parent.mkdir(parents=True, exist_ok=True)
    parsed.out.write_text(report, encoding="utf-8")
    print(f"Wrote benchmark for {len(results)} model(s) to {parsed.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
