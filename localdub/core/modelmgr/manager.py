"""The model manager: one place that knows every model, where it is, and what may be done to it."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from localdub import extras
from localdub.config import Settings
from localdub.core.modelmgr import hardware
from localdub.core.modelmgr.catalog import (
    Catalog,
    Entry,
    custom_id,
    custom_ollama_entry,
    load_catalog,
    valid_ollama_tag,
)
from localdub.core.modelmgr.handlers import (
    HANDLERS,
    Ctx,
    Handler,
    ModelError,
    NotDeletable,
    dir_size,
    ollama_find,
    ollama_manifest,
)
from localdub.core.modelmgr.state import ModelState
from localdub.core.youtube import tools as youtube_tools

log = logging.getLogger(__name__)
ACTIVE = ("queued", "running")


class ModelManager:
    def __init__(self, settings: Settings, jobs_active: Callable[[], bool] = lambda: False) -> None:
        self.settings = settings
        self.catalog: Catalog = load_catalog()
        self.state = ModelState(settings.data_dir / "models-state.json")
        self.jobs_active = jobs_active
        self._lock = threading.RLock()
        self._downloads: dict[str, dict[str, Any]] = {}
        self._queue: list[tuple[str, str]] = []  # (entry id, action)
        self._thread: threading.Thread | None = None

    # ----- lookup ----------------------------------------------------------------------------
    def entries(self) -> list[Entry]:
        custom = [
            custom_ollama_entry(str(c["tag"]), int(c.get("size_bytes") or 1))
            for c in self.state.custom_ollama()
            if valid_ollama_tag(str(c.get("tag", "")))
        ]
        known = {e.source.get("tag") for e in self.catalog.entries if e.source["type"] == "ollama"}
        return [*self.catalog.entries, *[c for c in custom if c.source["tag"] not in known]]

    def get(self, entry_id: str) -> Entry:
        found = next((e for e in self.entries() if e.id == entry_id), None)
        if found is None:
            raise ModelError(f"Unknown model '{entry_id}'.")
        return found

    def handler(self, e: Entry) -> Handler:
        return HANDLERS[e.source["type"]]

    def ctx(self) -> Ctx:
        return Ctx(self.settings)

    # ----- selection -------------------------------------------------------------------------
    def selected_entry(self, role: str, ctx: Ctx | None = None) -> Entry | None:
        """The chosen model of a role: the user's pick, else the default, else any installed one."""
        ctx = ctx or self.ctx()
        entries = [e for e in self.entries() if e.role == role]
        picked = self.state.selected(role)
        order = [
            *([e for e in entries if e.id == picked] if picked else []),
            *[e for e in entries if e.default],
            *entries,
        ]
        for e in order:
            if self.handler(e).installed(e, ctx):
                return e
        return None

    def default_entry(self, role: str, ctx: Ctx | None = None) -> Entry | None:
        """What a new dub should use: the selection, or the default even if not yet downloaded."""
        return self.selected_entry(role, ctx) or self.catalog.default_of(role)

    def select(self, entry_id: str) -> None:
        e = self.get(entry_id)
        if not self.catalog.role(e.role).selectable:
            raise ModelError(f"There is nothing to choose for '{self.catalog.role(e.role).title}'.")
        if not self.handler(e).installed(e, self.ctx()):
            raise ModelError("Download this model first, then it can be used.")
        self.state.set_selected(e.role, e.id)

    # ----- readiness for a dub ---------------------------------------------------------------
    def missing_for(self, asr_id: str | None, llm_tag: str | None) -> list[str]:
        """Human-readable list of what a dub with these choices still needs (empty = ready)."""
        ctx = self.ctx()
        out: list[str] = []
        asr = self.get(asr_id) if asr_id else self.default_entry("asr", ctx)
        if asr is not None and not self.handler(asr).installed(asr, ctx):
            out.append(f"Speech recognition: {asr.title}")
        tag = llm_tag
        if tag is None:
            d = self.default_entry("translation", ctx)
            tag = str(d.source["tag"]) if d is not None else None
        tags = ctx.ollama_tags()
        if tags is None:
            out.append("Translation: Ollama is not running")
        elif tag and ollama_find(tags, str(tag)) is None:
            out.append(f"Translation model: {tag}")
        tts = self.catalog.default_of("tts")
        if tts is not None and not self.handler(tts).installed(tts, ctx):
            out.append(f"Slovak voice: {tts.title}")
        return out

    def required_missing(self, ctx: Ctx | None = None) -> list[str]:
        """Default entries of required roles that have no installed model at all."""
        ctx = ctx or self.ctx()
        missing = []
        for role in self.catalog.roles:
            if role.required and self.selected_entry(role.id, ctx) is None:
                d = self.catalog.default_of(role.id)
                if d is not None:
                    missing.append(d.id)
        return missing

    # ----- the view the page needs -----------------------------------------------------------
    def snapshot(self, *, sizes: bool = False) -> dict[str, Any]:
        ctx = self.ctx()
        hw = hardware.detect(self.settings.models_dir)
        packages_ok = extras.packages_available()
        downloads = self.download_state()
        selected = {
            r.id: self.selected_entry(r.id, ctx) for r in self.catalog.roles if r.selectable
        }
        titles = {e.id: e.title for e in self.entries()}
        rows = []
        for e in self.entries():
            h = self.handler(e)
            installed = h.installed(e, ctx)
            locs = h.locations(e, ctx) if installed else []
            rec = self.state.record(e.id)
            sel = selected.get(e.role)
            rows.append(
                {
                    "id": e.id,
                    "role": e.role,
                    "title": e.title,
                    "summary": e.summary,
                    "choose_if": list(e.choose_if),
                    "avoid_if": list(e.avoid_if),
                    "requirements": {
                        "vram_gb": e.requirements.vram_gb,
                        "disk_gb": e.requirements.disk_gb,
                        "runs_on": e.requirements.runs_on,
                        "note": e.requirements.note,
                        "needs_packages": e.requirements.needs_packages,
                    },
                    "size_bytes": e.size_bytes,
                    "license": {"name": e.license_name, "url": e.license_url},
                    "status": e.status,
                    "measured": e.measured,
                    "languages": e.languages,
                    "pinned": e.pinned,
                    "custom": e.custom,
                    "default": e.default,
                    "replaced_by": e.replaced_by,
                    "replaced_by_title": titles.get(e.replaced_by or ""),
                    "required": self.catalog.role(e.role).required,
                    "group": e.role,
                    "installed": installed,
                    "available": packages_ok or not e.requirements.needs_packages,
                    "selected": sel is not None and sel.id == e.id,
                    "fits": hardware.fits(e.requirements, hw),
                    "download": downloads.get(e.id),
                    "locations": [str(p) for p in locs],
                    "store_note": h.note(e, ctx) if installed else None,
                    "size_on_disk": (h.disk_bytes(e, ctx) if sizes and installed else None),
                    "update": {
                        "supported": e.check_updates,
                        "available": bool(rec.get("update_available")),
                        "checked_at": rec.get("checked_at"),
                        "error": rec.get("check_error"),
                    },
                    "can_delete": installed,
                    "can_open_folder": bool(locs),
                }
            )
        models_dir = self.settings.models_dir
        return {
            "catalog_version": self.catalog.version,
            "roles": [
                {
                    "id": r.id,
                    "title": r.title,
                    "description": r.description,
                    "required": r.required,
                    "selectable": r.selectable,
                    "selected_id": chosen.id if (chosen := selected.get(r.id)) else None,
                }
                for r in self.catalog.roles
            ],
            "models": rows,
            "required_missing": self.required_missing(ctx),
            "busy": any(v["status"] in ACTIVE for v in downloads.values()),
            "hardware": {
                "gpu": (
                    {
                        "name": hw.gpu.name,
                        "vram_gb": round(hw.gpu.vram_gb, 1),
                        "vram_free_gb": round(hw.gpu.vram_free_mb / 1024, 1),
                        "driver": hw.gpu.driver,
                    }
                    if hw.gpu
                    else None
                ),
                "ram_gb": hw.ram_gb,
                "cpu_threads": hw.cpu_threads,
                "disk_free_bytes": hw.disk_free_bytes,
                "disk_total_bytes": hw.disk_total_bytes,
            },
            "paths": {
                "models": str(models_dir),
                "data": str(self.settings.data_dir),
                "optional_packages": str(extras.extras_dir()),
                "youtube_tools": str(youtube_tools.tools_dir()),
            },
            "models_bytes": dir_size(models_dir) if sizes else None,
        }

    # ----- downloads (one at a time, in the background) --------------------------------------
    def download_state(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._downloads.items()}

    def installing(self, entry_id: str) -> bool:
        with self._lock:
            return self._downloads.get(entry_id, {}).get("status") in ACTIVE

    def busy(self) -> bool:
        with self._lock:
            return any(v["status"] in ACTIVE for v in self._downloads.values())

    def start(self, ids: list[str], action: str = "download") -> list[str]:
        """Queue downloads/updates/re-downloads. Returns the ids that were actually queued."""
        queued = []
        with self._lock:
            for i in ids:
                e = self.get(i)
                if self.installing(i):
                    continue
                self._downloads[i] = {
                    "status": "queued", "done": 0, "total": e.size_bytes, "message": "Waiting",
                    "error": None, "show_bytes": True, "action": action,
                }  # fmt: skip
                self._queue.append((i, action))
                queued.append(i)
            if queued and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(
                    target=self._run, name="model-downloads", daemon=True
                )
                self._thread.start()
        return queued

    def _set(self, entry_id: str, **fields: Any) -> None:
        with self._lock:
            self._downloads[entry_id].update(fields)

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                entry_id, action = self._queue.pop(0)
            e = self.get(entry_id)
            self._set(
                entry_id, status="running", message="Starting...", error=None, started=time.time(),
                show_bytes=e.source["type"] != "packages",
            )  # fmt: skip

            def progress(
                done: int, total: int, message: str, eid: str = entry_id, size: int = e.size_bytes
            ) -> None:
                fields: dict[str, Any] = {"done": done, "total": total or size}
                if message:
                    fields["message"] = message
                self._set(eid, **fields)

            try:
                self._perform(e, action, progress)
                self._set(entry_id, status="done", message="Installed")
            except Exception as exc:  # noqa: BLE001 - shown to the user
                log.exception("%s of %s failed", action, entry_id)
                self._set(
                    entry_id, status="error", error=f"{type(exc).__name__}: {exc}", message="Failed"
                )

    def _perform(self, e: Entry, action: str, progress: Callable[[int, int, str], None]) -> None:
        h = self.handler(e)
        ctx = self.ctx()
        self.settings.models_dir.mkdir(parents=True, exist_ok=True)
        if action == "redownload":
            progress(0, e.size_bytes, "Removing the old files...")
            h.delete(e, ctx)
        progress(0, e.size_bytes, "Starting...")
        (h.update if action == "update" else h.download)(e, ctx, progress)
        ctx = self.ctx()  # fresh Ollama list etc.
        if not h.installed(e, ctx):
            raise ModelError(f"{e.title} was downloaded but is not usable; see the log")
        self.state.update_record(
            e.id, installed_at=time.time(), installed_revision=h.local_revision(e, ctx),
            update_available=False, check_error=None,
        )  # fmt: skip
        if e.source["type"] != "packages":
            progress(e.size_bytes, e.size_bytes, "Done")

    # ----- deleting --------------------------------------------------------------------------
    def delete(self, entry_id: str) -> dict[str, Any]:
        e = self.get(entry_id)
        if self.jobs_active():
            raise ModelError("Wait for the running dubbing job to finish before deleting models.")
        if self.installing(entry_id):
            raise ModelError("This model is being downloaded right now.")
        ctx = self.ctx()
        h = self.handler(e)
        if not h.installed(e, ctx):
            if e.custom:
                self.remove_custom(entry_id, delete_files=False)
            return {"deleted": False, "warnings": []}
        was_last = (
            self.catalog.role(e.role).required
            and sum(
                1 for x in self.entries() if x.role == e.role and self.handler(x).installed(x, ctx)
            )
            == 1
        )
        h.delete(e, ctx)
        self.state.drop_record(e.id)
        if e.custom:
            self.state.remove_custom(str(e.source["tag"]))
        warnings = []
        if was_last:
            warnings.append(
                f"No {self.catalog.role(e.role).title.lower()} model is installed now; "
                "dubbing needs one. Download it again from this page."
            )
        return {"deleted": True, "warnings": warnings}

    # ----- custom Ollama models --------------------------------------------------------------
    def add_custom_ollama(self, tag: str) -> Entry:
        tag = tag.strip()
        if not valid_ollama_tag(tag):
            raise ModelError("Enter a model name from ollama.com, for example gemma3:12b.")
        for e in self.entries():
            if e.source["type"] == "ollama" and str(e.source["tag"]).removesuffix(
                ":latest"
            ) == tag.removesuffix(":latest"):
                return e
        _digest, size = ollama_manifest(tag)  # raises a readable error if it does not exist
        self.state.add_custom(tag, size)
        return self.get(custom_id(tag))

    def remove_custom(self, entry_id: str, *, delete_files: bool) -> None:
        e = self.get(entry_id)
        if not e.custom:
            raise NotDeletable("Only models you added yourself can be removed from the list.")
        if delete_files:
            self.delete(entry_id)
        else:
            self.state.remove_custom(str(e.source["tag"]))

    # ----- updates (only when asked; nothing is checked in the background) ---------------------
    def check_updates(self) -> dict[str, Any]:
        ctx = self.ctx()
        checked, updates, errors = 0, [], {}
        for e in self.entries():
            h = self.handler(e)
            if not e.check_updates or not h.installed(e, ctx):
                continue
            checked += 1
            try:
                local, remote = h.local_revision(e, ctx), h.remote_revision(e, ctx)
            except ModelError as exc:
                errors[e.id] = str(exc)
                self.state.update_record(e.id, checked_at=time.time(), check_error=str(exc))
                continue
            available = bool(local and remote and local != remote)
            self.state.update_record(
                e.id,
                checked_at=time.time(),
                remote_revision=remote,
                update_available=available,
                check_error=None,
            )
            if available:
                updates.append(e.id)
        return {"checked": checked, "updates": updates, "errors": errors}

    # ----- where is it ------------------------------------------------------------------------
    def open_folder(self, entry_id: str | None) -> str:
        """Open Explorer on an entry's folder (or the models folder)."""
        ctx = self.ctx()
        if entry_id:
            e = self.get(entry_id)
            locs = self.handler(e).locations(e, ctx)
            target = locs[0] if locs else None
            if target is None:
                raise ModelError("This model has no folder of its own (Ollama manages it).")
        else:
            target = self.settings.models_dir
        target.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            raise ModelError("Opening folders is only supported on Windows.")
        os.startfile(str(target))  # type: ignore[attr-defined,unused-ignore]  # noqa: S606
        return str(target)
