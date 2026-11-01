"""The macOS-specific logic, tested from any system by pretending to be a Mac."""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import types
import zipfile
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf

from localdub import desktop
from localdub.core import platform as osplatform
from localdub.core.asr import mlx_whisper_provider
from localdub.core.asr.mlx_whisper_provider import MlxWhisperProvider
from localdub.core.media import ffmpeg, ffmpeg_tools
from localdub.core.modelmgr import hardware
from localdub.core.modelmgr.catalog import CatalogError, load_catalog, parse_catalog

# ----- the catalogue on each system ------------------------------------------------------------


def ids(catalog, role):
    return [e.id for e in catalog.of_role(role)]


def test_each_system_sees_only_its_own_speech_models():
    win, mac = load_catalog("win32"), load_catalog("darwin")
    assert ids(win, "asr") == [
        "whisper-large-v3", "whisper-large-v3-turbo", "whisper-small-en", "parakeet-tdt-0.6b-v3",
    ]  # fmt: skip
    assert ids(mac, "asr") == [
        "whisper-large-v3-mlx", "whisper-large-v3-turbo-mlx", "parakeet-tdt-0.6b-v3",
    ]  # fmt: skip
    assert win.default_of("asr").id == "whisper-large-v3"  # type: ignore[union-attr]
    assert mac.default_of("asr").id == "whisper-large-v3-mlx"  # type: ignore[union-attr]


def test_ffmpeg_is_something_to_download_only_on_a_mac():
    assert load_catalog("win32").of_role("ffmpeg") == []
    ff = load_catalog("darwin").default_of("ffmpeg")
    assert ff is not None and ff.source == {"type": "ffmpeg"}
    assert load_catalog("darwin").role("ffmpeg").required


def test_mac_models_are_pinned_to_a_full_revision():
    for e in load_catalog("darwin").of_role("asr"):
        if e.source["type"] == "mlx-whisper":
            assert len(e.source["revision"]) == 40 and set(e.source["revision"]) <= set("0123456789abcdef")
            assert e.source["files"] and "config.json" in e.source["files"]


def test_the_packages_entry_is_smaller_on_a_mac_because_pytorch_is_included():
    win = load_catalog("win32").entry("packages")
    mac = load_catalog("darwin").entry("packages")
    assert win is not None and mac is not None
    assert win.size_bytes > 1_000_000_000 > mac.size_bytes
    assert "NVIDIA" in win.license_name and "NVIDIA" not in mac.license_name
    assert mac.translations["sk"]["summary"] != win.translations.get("sk", {}).get("summary")


def test_an_entry_for_an_unknown_system_is_a_catalogue_error():
    raw = {
        "catalog_version": "x",
        "roles": [],
        "entries": [{"id": "a", "role": "r", "platforms": ["amiga"]}],
    }
    with pytest.raises(CatalogError, match="unknown platform"):
        parse_catalog(raw, "win32")


# ----- hardware --------------------------------------------------------------------------------


def test_apple_silicon_memory_is_shared_with_the_gpu():
    gpu = hardware.apple_gpu("Apple M4", 16 * 1024**3)
    assert gpu is not None and gpu.unified and gpu.driver == "Metal"
    assert 10 < gpu.vram_gb < 11  # about two thirds of 16 GB
    big = hardware.apple_gpu("Apple M3 Max", 64 * 1024**3)
    assert big is not None and big.vram_gb == 48
    assert hardware.apple_gpu("Intel(R) Core(TM) i7", 16 * 1024**3) is None
    assert hardware.apple_gpu(None, 16 * 1024**3) is None


def test_gpu_and_memory_are_read_with_sysctl_on_a_mac(monkeypatch):
    answers = {"hw.memsize": str(24 * 1024**3), "machdep.cpu.brand_string": "Apple M4"}
    monkeypatch.setattr(hardware.sys, "platform", "darwin")
    monkeypatch.setattr(hardware.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(hardware, "_sysctl", answers.get)
    monkeypatch.setattr(hardware, "_gpu_cache", None)
    gpu = hardware.detect_gpu()
    assert gpu is not None and gpu.name == "Apple M4 (GPU)" and gpu.unified
    assert hardware.detect_ram_gb() == 24.0
    monkeypatch.setattr(hardware, "_gpu_cache", None)


def test_the_fit_message_talks_about_the_mac_not_a_graphics_card():
    gpu = hardware.apple_gpu("Apple M4", 16 * 1024**3)
    hw = hardware.Hardware(gpu, 16.0, 10, 10**12, 10**12)
    req = load_catalog("darwin").entry("whisper-large-v3-mlx").requirements  # type: ignore[union-attr]
    ok = hardware.fits(req, hw)
    assert ok["level"] == "ok" and "Mac" in ok["text"] and "graphics card" not in ok["text"]
    assert "Macu" in hardware.fits(req, hw, "sk")["text"]
    small = hardware.Hardware(hardware.apple_gpu("Apple M1", 8 * 1024**3), 8.0, 8, 1, 1)
    partial = hardware.fits(req, small)
    assert partial["level"] == "partial" and "Mac memory" in partial["text"]


# ----- FFmpeg ----------------------------------------------------------------------------------


def make_zips(tmp_path: Path, monkeypatch, *, wrong: bool = False):
    blobs = {}
    files = {}
    for name in ("ffmpeg", "ffprobe"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(name, b"#!/bin/sh\necho fake " + name.encode())
        blobs[name] = buf.getvalue()
        files[name] = (f"{name}.zip", "0" * 64 if wrong else hashlib.sha256(blobs[name]).hexdigest())
    monkeypatch.setattr(ffmpeg_tools, "FILES", files)
    monkeypatch.setenv(ffmpeg_tools.TOOLS_ENV, str(tmp_path / "tools"))

    def handler(request: httpx.Request) -> httpx.Response:
        for name, (zip_name, _) in files.items():
            if str(request.url).endswith("/" + zip_name):
                return httpx.Response(200, content=blobs[name])
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ffmpeg_is_downloaded_verified_and_made_executable(tmp_path, monkeypatch):
    client = make_zips(tmp_path, monkeypatch)
    started: list[str] = []
    events: list[str] = []
    ffmpeg_tools.install(
        lambda d, t, m: events.append(m), client=client, check=lambda n, p: started.append(n)
    )
    tools = tmp_path / "tools"
    assert sorted(p.name for p in tools.iterdir()) == ["ffmpeg", "ffprobe"]  # no leftovers
    assert started == ["ffmpeg", "ffprobe"] and events[-1] == "Done"
    if sys.platform != "win32":
        assert ffmpeg_tools.managed_installed()
    assert ffmpeg_tools.remove() and not (tools / "ffmpeg").exists()


def test_a_wrong_checksum_installs_nothing(tmp_path, monkeypatch):
    client = make_zips(tmp_path, monkeypatch, wrong=True)
    with pytest.raises(ffmpeg_tools.FfmpegToolsError, match="checksum mismatch"):
        ffmpeg_tools.install(lambda *a: None, client=client, check=lambda n, p: None)
    assert list((tmp_path / "tools").iterdir()) == []


def test_the_pinned_ffmpeg_checksums_look_like_sha256():
    for zip_name, digest in ffmpeg_tools.FILES.values():
        assert zip_name.endswith(".zip") and len(digest) == 64 and int(digest, 16) >= 0
    assert ffmpeg_tools.BASE_URL.startswith("https://") and "1789931890_9.0.2" in ffmpeg_tools.BASE_URL


def test_a_finder_launched_app_finds_homebrews_ffmpeg(monkeypatch, tmp_path):
    seen: list[str | None] = []

    def which(name, path=None):
        seen.append(path)
        return "/opt/homebrew/bin/" + name if path and "/opt/homebrew/bin" in path else None

    monkeypatch.setattr(ffmpeg.sys, "platform", "darwin")
    monkeypatch.setenv(ffmpeg_tools.TOOLS_ENV, str(tmp_path / "tools"))
    monkeypatch.setattr(ffmpeg.shutil, "which", which)
    assert ffmpeg.find_tool("ffmpeg") == Path("/opt/homebrew/bin/ffmpeg")
    assert seen[0] is not None and seen[0].startswith(str(tmp_path / "tools"))  # ours comes first


# ----- the MLX speech recognition provider -------------------------------------------------------


def fake_mlx(monkeypatch, segments, language="en"):
    calls = {}
    mx = types.ModuleType("mlx.core")
    mx.cpu = "cpu-device"  # type: ignore[attr-defined]
    mx.default_device = lambda: "gpu"  # type: ignore[attr-defined]
    mx.set_default_device = lambda d: calls.setdefault("device", d)  # type: ignore[attr-defined]
    mx.clear_cache = lambda: calls.setdefault("cleared", True)  # type: ignore[attr-defined]
    mlx = types.ModuleType("mlx")
    mlx.core = mx  # type: ignore[attr-defined]
    mw = types.ModuleType("mlx_whisper")

    def transcribe(audio, **kw):
        calls["audio"], calls["kw"] = audio, kw
        return {"language": language, "segments": segments, "text": ""}

    mw.transcribe = transcribe  # type: ignore[attr-defined]
    holder = types.ModuleType("mlx_whisper.transcribe")

    class ModelHolder:
        model = "loaded"
        model_path = "somewhere"

    holder.ModelHolder = ModelHolder  # type: ignore[attr-defined]
    for name, mod in (("mlx", mlx), ("mlx.core", mx), ("mlx_whisper", mw), ("mlx_whisper.transcribe", holder)):
        monkeypatch.setitem(sys.modules, name, mod)
    return calls, ModelHolder


def wav(tmp_path: Path, seconds: float = 2.0, sr: int = 16000) -> Path:
    path = tmp_path / "a.wav"
    sf.write(str(path), np.zeros(int(sr * seconds), np.float32), sr)
    return path


def test_mlx_words_become_the_apps_words(tmp_path, monkeypatch):
    segs = [{"words": [
        {"word": " Hello", "start": 0.1, "end": 0.5, "probability": 0.9},
        {"word": " world.", "start": 0.6, "end": 1.0},
    ]}]  # fmt: skip
    calls, holder = fake_mlx(monkeypatch, segs)
    p = MlxWhisperProvider("org/repo", "abc", "large-v3-mlx", tmp_path)
    monkeypatch.setattr(p, "_local_snapshot", lambda: "/models/snap")
    res = p.transcribe(wav(tmp_path), "en")
    assert [w.text for w in res.words] == [" Hello", " world."]
    assert res.words[0].probability == 0.9 and res.words[1].probability == 1.0
    assert res.language == "en" and res.duration == 2.0 and res.language_probability is None
    assert res.engine == "mlx-whisper:large-v3-mlx:gpu"
    kw = calls["kw"]
    assert kw["path_or_hf_repo"] == "/models/snap" and kw["language"] == "en"
    assert kw["word_timestamps"] is True and kw["condition_on_previous_text"] is False
    assert calls["audio"].dtype == np.float32 and calls["audio"].ndim == 1
    p.close()
    assert holder.model is None and calls["cleared"] is True


def test_mlx_can_be_forced_onto_the_processor_and_detects_the_language(tmp_path, monkeypatch):
    calls, _ = fake_mlx(monkeypatch, [], language="de")
    p = MlxWhisperProvider("org/repo", None, "x", tmp_path, device="cpu")
    monkeypatch.setattr(p, "_local_snapshot", lambda: "/m")
    res = p.transcribe(wav(tmp_path), None)
    assert calls["device"] == "cpu-device" and calls["kw"]["language"] is None
    assert res.language == "de" and res.words == []


def test_mlx_refuses_audio_that_is_not_16_khz(tmp_path, monkeypatch):
    fake_mlx(monkeypatch, [])
    p = MlxWhisperProvider("org/repo", None, "x", tmp_path)
    monkeypatch.setattr(p, "_local_snapshot", lambda: "/m")
    with pytest.raises(ValueError, match="16 kHz"):
        p.transcribe(wav(tmp_path, sr=44100), "en")


def test_a_model_that_is_not_downloaded_says_where_to_get_it(tmp_path, monkeypatch):
    fake_mlx(monkeypatch, [])
    p = MlxWhisperProvider("org/not-here", "0" * 40, "x", tmp_path)
    with pytest.raises(FileNotFoundError, match="AI models page"):
        p.transcribe(wav(tmp_path), "en")


def test_the_provider_module_imports_without_mlx_installed():
    assert mlx_whisper_provider.MlxWhisperProvider.__name__ == "MlxWhisperProvider"


# ----- processes and the window ------------------------------------------------------------------


def test_children_are_found_from_a_ps_listing(monkeypatch):
    listing = "  1   0\n 10   1\n 11  10\n 12  11\n 13   1\n bad line\n"
    monkeypatch.setattr(
        osplatform.subprocess, "run",
        lambda *a, **k: types.SimpleNamespace(stdout=listing, returncode=0),
    )
    assert sorted(osplatform._children(10)) == [11, 12]
    assert osplatform._children(99) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_kill_tree_stops_a_grandchild_too(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time;"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        f"open(r'{pidfile}', 'w').write(str(p.pid));"
        "time.sleep(60)"
    )
    child = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    import time

    for _ in range(100):
        if pidfile.exists() and pidfile.read_text():
            break
        time.sleep(0.1)
    grandchild = int(pidfile.read_text())
    osplatform.kill_tree(child.pid)
    child.wait(timeout=10)
    for _ in range(50):
        if not osplatform.pid_alive(grandchild):
            break
        time.sleep(0.1)
    assert not osplatform.pid_alive(grandchild)


def test_keep_awake_does_nothing_off_a_mac():
    if sys.platform != "darwin":
        assert osplatform.keep_awake() is False


def test_dialogs_on_a_mac_go_through_osascript(monkeypatch):
    seen = {}
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setattr(
        desktop.subprocess, "run", lambda cmd, **kw: seen.setdefault("cmd", cmd)
    )
    desktop.message_box("It said: \"no\"", "Title")
    cmd = seen["cmd"]
    assert cmd[0] == "osascript" and cmd[-2:] == ["It said: \"no\"", "Title"]


def test_the_models_folder_opens_in_finder(monkeypatch, tmp_path):
    from localdub.config import Settings
    from localdub.core.modelmgr import manager as mgr_mod
    from localdub.core.modelmgr.manager import ModelManager

    settings = Settings(models_dir=tmp_path / "models", data_dir=tmp_path / "data")
    mgr = ModelManager(settings, lambda: False)
    seen = {}
    monkeypatch.setattr(mgr_mod.sys, "platform", "darwin")
    monkeypatch.setattr(mgr_mod.subprocess, "Popen", lambda cmd, **kw: seen.setdefault("cmd", cmd))
    assert mgr.open_folder(None) == str(tmp_path / "models")
    assert seen["cmd"] == ["open", str(tmp_path / "models")]


# ----- the lock file covers both systems -----------------------------------------------------------


def test_export_lines_for_the_other_system_are_ignored(monkeypatch):
    from localdub import extras

    text = (
        "numpy==2.5.0 ; (platform_machine == 'arm64' and sys_platform == 'darwin') or sys_platform == 'win32' \\\n"
        "    --hash=sha256:aa\n"
        "mlx==0.32.4 ; platform_machine == 'arm64' and sys_platform == 'darwin' \\\n"
        "    --hash=sha256:bb\n"
        "torch==2.9.1+cu128 ; sys_platform == 'win32' \\\n"
        "    --hash=sha256:cc\n"
        "torch==2.9.1 ; platform_machine == 'arm64' and sys_platform == 'darwin' \\\n"
        "    --hash=sha256:dd\n"
        "plain==1.0 \\\n"
        "    --hash=sha256:ee\n"
    )
    monkeypatch.setattr(extras, "MARKER_ENV", {"sys_platform": "win32", "platform_machine": "AMD64"})
    assert extras.parse_pins(text) == {"numpy": "2.5.0", "torch": "2.9.1+cu128", "plain": "1.0"}
    monkeypatch.setattr(extras, "MARKER_ENV", {"sys_platform": "darwin", "platform_machine": "arm64"})
    assert extras.parse_pins(text) == {
        "numpy": "2.5.0", "mlx": "0.32.4", "torch": "2.9.1", "plain": "1.0",
    }  # fmt: skip


# ----- the models page on a Mac -----------------------------------------------------------------


def test_the_models_page_on_a_mac_lists_ffmpeg_and_the_mlx_models(monkeypatch, tmp_path):
    from localdub.config import Settings
    from localdub.core.modelmgr import handlers
    from localdub.core.modelmgr import manager as mgr_mod
    from localdub.core.modelmgr.manager import ModelManager

    mac = load_catalog("darwin")
    monkeypatch.setattr(mgr_mod, "load_catalog", lambda: mac)
    monkeypatch.setattr(
        handlers, "find_tool", lambda name, configured=None: (_ for _ in ()).throw(ffmpeg.MediaError("no"))
    )
    settings = Settings(models_dir=tmp_path / "models", data_dir=tmp_path / "data", asr_id="whisper-large-v3-mlx")
    mgr = ModelManager(settings, lambda: False)
    snap = mgr.snapshot()
    rows = {m["id"]: m for m in snap["models"]}
    assert {"whisper-large-v3-mlx", "whisper-large-v3-turbo-mlx", "ffmpeg"} <= set(rows)
    assert "whisper-large-v3" not in rows
    assert rows["ffmpeg"]["required"] and not rows["ffmpeg"]["installed"]
    assert "ffmpeg" in snap["required_missing"] and "whisper-large-v3-mlx" in snap["required_missing"]
    assert "FFmpeg" in mgr.missing_for(None, None)
    choice = mgr.choices("asr")
    assert [c["id"] for c in choice][0] == "whisper-large-v3-mlx"


def test_resolve_picks_the_mlx_engine(monkeypatch):
    from localdub.config import Settings
    from localdub.core.modelmgr import resolve

    monkeypatch.setattr(resolve, "load_catalog", lambda: load_catalog("darwin"))
    choice = resolve.resolve_asr(Settings(), "whisper-large-v3-turbo-mlx")
    assert choice.engine == "mlx" and choice.name == "large-v3-turbo-mlx"
    assert choice.repo == "mlx-community/whisper-large-v3-turbo" and len(choice.revision or "") == 40
