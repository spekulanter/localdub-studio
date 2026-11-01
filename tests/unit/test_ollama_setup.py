from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

from localdub.config import Settings
from localdub.core.modelmgr import handlers
from localdub.core.modelmgr.catalog import load_catalog
from localdub.core.modelmgr.handlers import ModelError
from localdub.core.translation import ollama_setup


def zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Ollama.app/Contents/Info.plist", "x")
    return buf.getvalue()


def client(blob: bytes, *, wrong: bool = False) -> httpx.Client:
    digest = "0" * 64 if wrong else hashlib.sha256(blob).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/sha256sum.txt"):
            return httpx.Response(200, text=f"{digest}  ./Ollama-darwin.zip\n{'1' * 64}  ./other.tgz\n")
        if url.endswith("/Ollama-darwin.zip"):
            return httpx.Response(200, content=blob, headers={"content-length": str(len(blob))})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def tools_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALDUB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(ollama_setup, "user_dir", lambda name: tmp_path / name)
    return tmp_path


def fake_extract(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)


def test_the_mac_download_is_checked_then_unpacked(tools_dir):
    events: list[str] = []
    app = ollama_setup.install_mac(
        lambda d, t, m: events.append(m),
        client=client(zip_bytes()),
        extract=fake_extract,
        target=tools_dir / "Applications",
    )
    assert app == tools_dir / "Applications" / "Ollama.app" and app.is_dir()
    assert events[0] == "Reading the checksum..." and "Installing..." in events
    assert not (tools_dir / "tools" / ".ollama-download").exists()  # nothing left behind


def test_a_wrong_checksum_unpacks_nothing(tools_dir):
    with pytest.raises(ollama_setup.OllamaSetupError, match="checksum mismatch"):
        ollama_setup.install_mac(
            lambda *a: None, client=client(zip_bytes(), wrong=True), extract=fake_extract,
            target=tools_dir / "Applications",
        )  # fmt: skip
    assert not (tools_dir / "Applications").exists()


def test_network_trouble_is_explained(tools_dir):
    def boom(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(ollama_setup.OllamaSetupError, match="internet connection"):
        ollama_setup.install_mac(
            lambda *a: None, client=httpx.Client(transport=httpx.MockTransport(boom)),
            extract=fake_extract, target=tools_dir / "Applications",
        )  # fmt: skip


def test_windows_uses_winget_with_the_ollama_package(monkeypatch):
    seen = {}
    monkeypatch.setattr(ollama_setup.shutil, "which", lambda name, path=None: "C:/winget.exe")
    monkeypatch.setattr(
        ollama_setup.subprocess, "run",
        lambda cmd, **kw: seen.setdefault("cmd", cmd) and type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )
    ollama_setup.install_windows(lambda *a: None)
    cmd = seen["cmd"]
    assert cmd[0] == "C:/winget.exe" and cmd[1:5] == ["install", "--id", "Ollama.Ollama", "-e"]
    assert "--accept-package-agreements" in cmd


def test_without_winget_the_user_is_told_where_to_get_ollama(monkeypatch):
    monkeypatch.setattr(ollama_setup.shutil, "which", lambda name, path=None: None)
    with pytest.raises(ollama_setup.OllamaSetupError, match="ollama.com/download"):
        ollama_setup.install_windows(lambda *a: None)


def test_ollama_is_found_where_each_system_puts_it(monkeypatch, tmp_path):
    app = tmp_path / "Ollama.app"
    app.mkdir()
    monkeypatch.setattr(ollama_setup, "mac_app_candidates", lambda: [tmp_path / "none.app", app])
    assert ollama_setup.find_mac_app() == app
    monkeypatch.setattr(ollama_setup.shutil, "which", lambda name, path=None: None)
    assert ollama_setup.find_cli() is None
    monkeypatch.setattr(ollama_setup, "mac_app_candidates", lambda: [])
    assert ollama_setup.find_mac_app() is None


def test_a_mac_starts_the_menu_bar_app(monkeypatch, tmp_path):
    app = tmp_path / "Ollama.app"
    app.mkdir()
    seen = {}
    monkeypatch.setattr(ollama_setup.sys, "platform", "darwin")
    monkeypatch.setattr(ollama_setup, "mac_app_candidates", lambda: [app])
    monkeypatch.setattr(ollama_setup.subprocess, "Popen", lambda cmd, **kw: seen.setdefault("cmd", cmd))
    ollama_setup.start()
    assert seen["cmd"] == ["open", "-a", str(app)]


def test_ensure_running_starts_once_and_waits(monkeypatch):
    answers = iter([False, False, True])
    started = []
    monkeypatch.setattr(ollama_setup, "is_running", lambda url, timeout=2.0: next(answers))
    monkeypatch.setattr(ollama_setup, "start", lambda: started.append(1))
    monkeypatch.setattr(ollama_setup.time, "sleep", lambda s: None)
    assert ollama_setup.ensure_running("http://x", wait_s=30) is True and started == [1]


def test_ensure_running_gives_up_with_false(monkeypatch):
    monkeypatch.setattr(ollama_setup, "is_running", lambda url, timeout=2.0: False)
    monkeypatch.setattr(ollama_setup, "start", lambda: None)
    monkeypatch.setattr(ollama_setup.time, "sleep", lambda s: None)
    ticks = iter(range(0, 1000, 20))
    monkeypatch.setattr(ollama_setup.time, "monotonic", lambda: next(ticks))
    assert ollama_setup.ensure_running("http://x", wait_s=30) is False


# ----- the handler: a translation model download fixes what is missing first --------------------


class FakeCtx:
    def __init__(self, tags):
        self.settings = Settings()
        self._tags = tags
        self._ollama_loaded = True

    def ollama_tags(self):
        return self._tags


def test_ensure_ollama_installs_then_starts_when_it_is_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(ollama_setup, "is_present", lambda: False)
    monkeypatch.setattr(ollama_setup, "install", lambda progress: calls.append("install"))
    monkeypatch.setattr(ollama_setup, "ensure_running", lambda url: calls.append("start") or True)
    handlers.ensure_ollama(FakeCtx(None), lambda *a: None)
    assert calls == ["install", "start"]


def test_ensure_ollama_only_starts_an_installed_one(monkeypatch):
    calls = []
    monkeypatch.setattr(ollama_setup, "is_present", lambda: True)
    monkeypatch.setattr(ollama_setup, "install", lambda progress: calls.append("install"))
    monkeypatch.setattr(ollama_setup, "ensure_running", lambda url: calls.append("start") or True)
    handlers.ensure_ollama(FakeCtx(None), lambda *a: None)
    assert calls == ["start"]


def test_ensure_ollama_reports_an_ollama_that_does_not_answer(monkeypatch):
    monkeypatch.setattr(ollama_setup, "is_present", lambda: True)
    monkeypatch.setattr(ollama_setup, "ensure_running", lambda url: False)
    with pytest.raises(ModelError, match="did not answer"):
        handlers.ensure_ollama(FakeCtx(None), lambda *a: None)


def test_every_system_lists_ollama_before_the_translation_model():
    for platform in ("win32", "darwin"):
        cat = load_catalog(platform)
        order = [r.id for r in cat.roles]
        assert order.index("ollama") < order.index("translation")
        assert cat.default_of("ollama").source == {"type": "ollama-app"}  # type: ignore[union-attr]
    assert load_catalog("darwin").default_of("ollama").size_bytes < 300_000_000  # type: ignore[union-attr]


def test_a_missing_ollama_is_one_of_the_things_a_dub_still_needs(monkeypatch, tmp_path):
    from localdub.core.modelmgr.manager import ModelManager

    monkeypatch.setattr(ollama_setup, "is_present", lambda: False)
    mgr = ModelManager(Settings(models_dir=tmp_path / "m", data_dir=tmp_path / "d"), lambda: False)
    monkeypatch.setattr(handlers.Ctx, "ollama_tags", lambda self: None)
    missing = mgr.missing_for(None, None)
    assert any(m.startswith("Ollama (the program") for m in missing)
    assert "Translation: Ollama is not running" not in missing  # one clear message, not two
    assert "ollama-app" in mgr.required_missing()


@pytest.mark.skipif(sys.platform == "darwin", reason="uses the Windows paths")
def test_the_windows_program_folder_is_under_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert ollama_setup.windows_program() == tmp_path / "Programs" / "Ollama"
