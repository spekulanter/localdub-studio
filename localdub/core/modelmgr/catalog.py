"""The model catalogue: a data file that says what exists, what it is good for and what it needs.

`catalog.json` ships with each program version, so new models arrive with updates; the user can also
add any Ollama model by name (see `manager.py`). Everything the Models page shows comes from here.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

LANGS = ("sk",)  # languages that may carry translated texts next to the English ones
STATUSES = ("recommended", "available", "experimental", "not_recommended", "custom")
RUNS_ON = ("gpu", "cpu", "gpu-or-cpu")
SOURCE_TYPES = (
    "whisper", "mlx-whisper", "ollama", "parakeet", "supertonic", "diarization", "demucs",
    "openvoice", "youtube", "packages", "ffmpeg", "ollama-app",
)  # fmt: skip
PLATFORMS = ("win32", "darwin")
PLATFORM = sys.platform  # the system whose entries are shown (tests change it)
_OLLAMA_TAG = re.compile(r"^(?:[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*(?::[A-Za-z0-9._-]+)?$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._:~-]*$")


class CatalogError(ValueError):
    """The catalogue file is malformed (a programming error caught by the tests)."""


@dataclass(frozen=True)
class Role:
    id: str
    title: str
    description: str
    required: bool
    selectable: bool
    translations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def text(self, lang: str) -> tuple[str, str]:
        tr = self.translations.get(lang, {})
        return tr.get("title", self.title), tr.get("description", self.description)


@dataclass(frozen=True)
class Requirements:
    vram_gb: float | None  # GPU memory that makes it comfortable; None = does not use the GPU
    disk_gb: float
    runs_on: str
    needs_packages: bool = False
    note: str = ""


@dataclass(frozen=True)
class Entry:
    id: str
    role: str
    title: str
    summary: str
    choose_if: tuple[str, ...]
    avoid_if: tuple[str, ...]
    requirements: Requirements
    size_bytes: int
    license_name: str
    license_url: str
    status: str
    source: dict[str, Any]
    default: bool = False
    measured: str | None = None
    languages: str | None = None
    pinned: str | None = None
    check_updates: bool = False
    replaced_by: str | None = None
    custom: bool = False
    source_langs: tuple[str, ...] | None = None  # None = every language
    platforms: tuple[str, ...] | None = None  # None = every supported operating system
    translations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def text(self, lang: str) -> dict[str, Any]:
        """The user-facing texts in `lang` (English where no translation exists)."""
        tr = self.translations.get(lang, {})
        return {
            "title": tr.get("title", self.title),
            "summary": tr.get("summary", self.summary),
            "choose_if": list(tr.get("choose_if", self.choose_if)),
            "avoid_if": list(tr.get("avoid_if", self.avoid_if)),
            "measured": tr.get("measured", self.measured),
            "pinned": tr.get("pinned", self.pinned),
            "note": tr.get("note", self.requirements.note),
        }


@dataclass(frozen=True)
class Catalog:
    version: str
    roles: tuple[Role, ...]
    entries: tuple[Entry, ...] = field(default_factory=tuple)

    def role(self, role_id: str) -> Role:
        return next(r for r in self.roles if r.id == role_id)

    def entry(self, entry_id: str) -> Entry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    def of_role(self, role_id: str) -> list[Entry]:
        return [e for e in self.entries if e.role == role_id]

    def default_of(self, role_id: str) -> Entry | None:
        entries = self.of_role(role_id)
        return next((e for e in entries if e.default), entries[0] if entries else None)


def _need(d: dict[str, Any], key: str, kind: Any, where: str) -> Any:
    if key not in d or not isinstance(d[key], kind) or isinstance(d[key], bool) != (kind is bool):
        raise CatalogError(f"{where}: '{key}' is missing or has the wrong type")
    return d[key]


def parse_entry(raw: dict[str, Any], *, custom: bool = False) -> Entry:
    where = f"entry {raw.get('id', '?')}"
    entry_id = _need(raw, "id", str, where)
    if not _ID.match(entry_id):
        raise CatalogError(f"{where}: bad id")
    status = _need(raw, "status", str, where)
    if status not in STATUSES:
        raise CatalogError(f"{where}: status '{status}' is not one of {STATUSES}")
    req = _need(raw, "requirements", dict, where)
    runs_on = _need(req, "runs_on", str, f"{where}.requirements")
    if runs_on not in RUNS_ON:
        raise CatalogError(f"{where}: runs_on '{runs_on}' is not one of {RUNS_ON}")
    vram = req.get("vram_gb")
    if vram is not None and not isinstance(vram, int | float):
        raise CatalogError(f"{where}: vram_gb must be a number or null")
    lic = _need(raw, "license", dict, where)
    source = _need(raw, "source", dict, where)
    if _need(source, "type", str, f"{where}.source") not in SOURCE_TYPES:
        raise CatalogError(f"{where}: unknown source type '{source['type']}'")
    size = _need(raw, "size_bytes", int, where)
    if size <= 0:
        raise CatalogError(f"{where}: size_bytes must be positive")
    return Entry(
        id=entry_id,
        role=_need(raw, "role", str, where),
        title=_need(raw, "title", str, where),
        summary=_need(raw, "summary", str, where),
        choose_if=tuple(_need(raw, "choose_if", list, where)),
        avoid_if=tuple(_need(raw, "avoid_if", list, where)),
        requirements=Requirements(
            vram_gb=float(vram) if vram is not None else None,
            disk_gb=float(_need(req, "disk_gb", int | float, f"{where}.requirements")),
            runs_on=runs_on,
            needs_packages=bool(req.get("needs_packages", False)),
            note=str(req.get("note", "")),
        ),
        size_bytes=size,
        license_name=_need(lic, "name", str, f"{where}.license"),
        license_url=_need(lic, "url", str, f"{where}.license"),
        status=status,
        source=source,
        default=bool(raw.get("default", False)),
        measured=raw.get("measured"),
        languages=raw.get("languages"),
        pinned=raw.get("pinned"),
        check_updates=bool(raw.get("check_updates", False)),
        replaced_by=raw.get("replaced_by"),
        custom=custom,
        source_langs=tuple(raw["source_langs"]) if raw.get("source_langs") else None,
        platforms=tuple(raw["platforms"]) if raw.get("platforms") else None,
        translations={
            k: dict(v)
            for k, v in (raw.get("translations") or {k: raw[k] for k in LANGS if k in raw}).items()
        },
    )


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """`over` laid on top of `base`; nested objects are merged, everything else is replaced."""
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def for_platform(raw_entry: dict[str, Any], platform: str) -> dict[str, Any] | None:
    """The entry as it applies on `platform` (None: it does not exist there).

    An entry may carry `"platforms": ["darwin"]` and, per operating system, an object named after it
    (`"darwin": {...}`) whose fields replace the general ones, for example a different size.
    """
    platforms = raw_entry.get("platforms")
    if platforms:
        unknown = [p for p in platforms if p not in PLATFORMS]
        if unknown:
            raise CatalogError(f"entry {raw_entry.get('id', '?')}: unknown platform {unknown}")
        if platform not in platforms:
            return None
    over = raw_entry.get(platform)
    merged = _merge(raw_entry, over) if isinstance(over, dict) else dict(raw_entry)
    for p in PLATFORMS:
        merged.pop(p, None)
    return merged


def parse_catalog(raw: dict[str, Any], platform: str | None = None) -> Catalog:
    platform = platform or PLATFORM
    version = _need(raw, "catalog_version", str, "catalog")
    roles = tuple(
        Role(
            id=_need(r, "id", str, "role"),
            title=_need(r, "title", str, "role"),
            description=_need(r, "description", str, "role"),
            required=bool(r.get("required", False)),
            selectable=bool(r.get("selectable", False)),
            translations={k: dict(r[k]) for k in LANGS if k in r},
        )
        for r in _need(raw, "roles", list, "catalog")
    )
    here = (for_platform(e, platform) for e in _need(raw, "entries", list, "catalog"))
    entries = tuple(parse_entry(e) for e in here if e is not None)
    ids = [e.id for e in entries]
    if len(set(ids)) != len(ids):
        raise CatalogError("catalog: duplicate entry ids")
    role_ids = {r.id for r in roles}
    for e in entries:
        if e.role not in role_ids:
            raise CatalogError(f"entry {e.id}: unknown role '{e.role}'")
        if e.replaced_by and e.replaced_by not in ids:
            raise CatalogError(f"entry {e.id}: replaced_by '{e.replaced_by}' does not exist")
    for r in roles:
        defaults = [e for e in entries if e.role == r.id and e.default]
        if len(defaults) > 1:
            raise CatalogError(f"role {r.id}: more than one default")
        if r.selectable and not defaults:
            raise CatalogError(f"role {r.id}: a selectable role needs a default entry")
    return Catalog(version=version, roles=roles, entries=entries)


def load_catalog(platform: str | None = None) -> Catalog:
    """The catalogue for this operating system (entries of other systems are left out)."""
    text = (resources.files("localdub.core.modelmgr") / "catalog.json").read_text(encoding="utf-8")
    return parse_catalog(json.loads(text), platform)


def valid_ollama_tag(tag: str) -> bool:
    """A plain Ollama registry name: `name`, `name:tag` or `namespace/name:tag` (no host or URL)."""
    return len(tag) <= 120 and bool(_OLLAMA_TAG.match(tag))


def custom_id(tag: str) -> str:
    return "ollama:" + tag.replace("/", "~")  # no slash: the id is used in URL paths


def custom_ollama_entry(tag: str, size_bytes: int) -> Entry:
    """An entry for a model the user added by name. LocalDub has not tested it."""
    return parse_entry(
        {
            "id": custom_id(tag),
            "role": "translation",
            "status": "custom",
            "title": tag,
            "summary": "A model you added by name. LocalDub has not tested it for Slovak dubbing.",
            "choose_if": ["You want to try a newer or different model than the ones listed."],
            "avoid_if": ["You need a known quality: only the listed models were measured."],
            "requirements": {
                "vram_gb": None,
                "disk_gb": round(size_bytes / 1e9, 1),
                "runs_on": "gpu-or-cpu",
            },
            "size_bytes": max(int(size_bytes), 1),
            "license": {
                "name": "See the model page on ollama.com",
                "url": f"https://ollama.com/library/{tag.split(':')[0]}",
            },
            "measured": None,
            "check_updates": True,
            "source": {"type": "ollama", "tag": tag},
        },
        custom=True,
    )
