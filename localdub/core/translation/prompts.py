"""Prompt construction for context-aware, duration-aware dubbing translation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

LANG_NAMES = {"en": "English", "sk": "Slovak", "cs": "Czech", "de": "German"}

TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {"translation": {"type": "string"}},
    "required": ["translation"],
}


class PromptProfile(StrEnum):
    #: Instruction-following chat model: context, character budget, JSON output.
    GENERIC = "generic"
    #: TranslateGemma: trained on a fixed single-text prompt; plain text output.
    TRANSLATEGEMMA = "translategemma"


def profile_for_model(model: str) -> PromptProfile:
    if model.lower().startswith("translategemma"):
        return PromptProfile.TRANSLATEGEMMA
    return PromptProfile.GENERIC


def char_budget(duration_s: float, chars_per_second: float) -> int:
    return max(8, math.floor(duration_s * chars_per_second))


@dataclass(frozen=True)
class ContextLine:
    source: str
    translation: str | None = None


def lang_name(code: str) -> str:
    return LANG_NAMES.get(code, code)


def generic_messages(
    text: str,
    *,
    source_lang: str,
    target_lang: str,
    duration_s: float,
    budget: int,
    before: list[ContextLine],
    after: list[ContextLine],
) -> list[dict[str, str]]:
    src, tgt = lang_name(source_lang), lang_name(target_lang)
    system = (
        f"You are a professional film dubbing translator from {src} to {tgt}. "
        f"Translate only the CURRENT line into natural, spoken {tgt} that a native speaker "
        "would say in a dubbed film. Preserve meaning, tone, register and names. "
        "Use the context lines only to resolve pronouns, grammatical gender and consistency; "
        "never translate or repeat them. "
        "The translation is spoken aloud in a fixed time window, so it must not exceed the "
        "character limit; rephrase or condense if needed while keeping the meaning. "
        'Reply as JSON: {"translation": "..."}'
    )
    parts: list[str] = []
    if before:
        parts.append("Previous lines (context):")
        for c in before:
            parts.append(
                f"- {src}: {c.source}" + (f" | {tgt}: {c.translation}" if c.translation else "")
            )
    parts.append(f"CURRENT line ({duration_s:.1f} s, max {budget} characters):\n{text}")
    if after:
        parts.append("Following lines (context only):")
        parts.extend(f"- {src}: {c.source}" for c in after)
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(parts)}]


def shorten_messages(
    previous: list[dict[str, str]], translation: str, budget: int
) -> list[dict[str, str]]:
    return [
        *previous,
        {"role": "assistant", "content": f'{{"translation": "{translation}"}}'},
        {
            "role": "user",
            "content": (
                f"That is {len(translation)} characters; the limit is {budget}. "
                "Give a shorter, natural version with the same meaning."
            ),
        },
    ]


def translategemma_messages(
    text: str, *, source_lang: str, target_lang: str
) -> list[dict[str, str]]:
    src, tgt = lang_name(source_lang), lang_name(target_lang)
    prompt = (
        f"You are a professional {src} ({source_lang}) to {tgt} ({target_lang}) translator. "
        f"Your goal is to accurately convey the meaning and nuances of the original {src} text "
        f"while adhering to {tgt} grammar, vocabulary, and cultural sensitivities.\n"
        f"Produce only the {tgt} translation, without any additional explanations or commentary. "
        f"Please translate the following {src} text into {tgt}:\n\n\n{text}"
    )
    return [{"role": "user", "content": prompt}]


def clean_translation(text: str) -> str:
    t = text.strip()
    for prefix in ("Slovak:", "SK:", "Translation:", "Preklad:"):
        if t.lower().startswith(prefix.lower()):
            t = t[len(prefix) :].strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'“”„":
        t = t[1:-1].strip()
    return " ".join(t.split())
