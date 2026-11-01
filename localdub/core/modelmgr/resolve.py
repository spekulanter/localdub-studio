"""Turn the catalogue id stored on a dub ("whisper-large-v3") into what the pipeline needs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from localdub.config import Settings
from localdub.core.modelmgr.catalog import load_catalog


class UnknownModel(ValueError):
    pass


@dataclass(frozen=True)
class AsrChoice:
    entry_id: str
    engine: str  # "whisper" | "mlx" | "parakeet"
    name: str  # stable key used in the stage fingerprint: "large-v3", "parakeet-tdt-0.6b-v3-int8"
    repo: str | None  # Hugging Face repository (whisper)
    folder: Path | None  # model folder (parakeet)
    revision: str | None = None  # pinned Hugging Face revision (mlx)


def resolve_asr(settings: Settings, asr_id: str | None = None) -> AsrChoice:
    entry_id = asr_id or settings.asr_id
    entry = load_catalog().entry(entry_id)
    if entry is None or entry.role != "asr":
        raise UnknownModel(f"'{entry_id}' is not a known speech recognition model.")
    src = entry.source
    if src["type"] == "whisper":
        return AsrChoice(entry.id, "whisper", str(src["name"]), str(src["repo"]), None)
    if src["type"] == "mlx-whisper":
        return AsrChoice(
            entry.id, "mlx", str(src["name"]), str(src["repo"]), None, str(src["revision"])
        )
    if src["type"] == "parakeet":
        return AsrChoice(
            entry.id, "parakeet", str(src["dir"]), None, settings.models_dir / src["dir"]
        )
    raise UnknownModel(f"Speech recognition model '{entry_id}' has an unsupported source.")
