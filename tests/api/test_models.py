from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from localdub.api.app import create_app
from localdub.config import Settings
from localdub.core.modelmgr import handlers as H
from localdub.core.models import RemoteModel, ensure_model, is_readable


@pytest.fixture
def strict_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        ollama_url="http://127.0.0.1:9",  # nothing listens: Ollama "not running"
        require_models_before_jobs=True,
    )


@pytest.fixture
def client(strict_settings: Settings):
    with TestClient(create_app(strict_settings, start_queue=False)) as c:
        yield c


def test_ensure_model_writes_into_target_dir_and_repairs_unreadable_file(
    tmp_path: Path, monkeypatch
):
    import hashlib

    payload = b"onnx-bytes" * 1000
    model = RemoteModel(
        name="t",
        url="http://test/x.onnx",
        sha256=hashlib.sha256(payload).hexdigest(),
        dest="d/x.onnx",
    )

    import httpx

    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=payload))
    client = httpx.Client(transport=transport)
    seen: list[tuple[int, int]] = []
    path = ensure_model(model, tmp_path, client=client, progress=lambda a, b: seen.append((a, b)))
    assert path.read_bytes() == payload and seen and seen[-1][0] == len(payload)
    assert sorted(p.name for p in path.parent.iterdir()) == [
        "x.onnx"
    ]  # no temp folders left behind

    # A file the user cannot read (written by an elevated installer) is replaced, not trusted.
    path.write_bytes(b"locked")
    real = is_readable
    state = {"first": True}

    def flaky(p: Path) -> bool:
        if state["first"]:
            state["first"] = False
            return False
        return real(p)

    monkeypatch.setattr("localdub.core.models.is_readable", flaky)
    assert ensure_model(model, tmp_path, client=client).read_bytes() == payload


def test_checksum_mismatch_installs_nothing(tmp_path: Path):
    import httpx

    from localdub.core.models import ModelDownloadError

    model = RemoteModel(name="t", url="http://test/x", sha256="0" * 64, dest="d/x.onnx")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"abc"))
    )
    with pytest.raises(ModelDownloadError, match="checksum mismatch"):
        ensure_model(model, tmp_path, client=client)
    assert list((tmp_path / "d").iterdir()) == []


class FakeProc:
    def __init__(self, returncode: int, out: str = "", hang: bool = False):
        import io

        self.stdout = io.StringIO(out)
        self._rc, self._hang, self.returncode = returncode, hang, None
        self.terminated = False

    def poll(self):
        if self._hang and not self.terminated:
            return None
        self.returncode = -15 if self.terminated else self._rc
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def wait(self, timeout=None):
        return self.returncode


def test_a_pytorch_model_is_fetched_in_a_child_process_and_failures_are_explained(monkeypatch):
    import subprocess
    import sys

    seen: dict[str, list[str]] = {}

    def fake_popen(cmd, **kwargs):
        seen["cmd"] = cmd
        return FakeProc(1, "boom\nModuleNotFoundError: torch\n")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with pytest.raises(H.ModelError, match=r"(?s)exit code 1.*ModuleNotFoundError: torch"):
        H.fetch_in_subprocess("separation")
    assert seen["cmd"] == [sys.executable, "-m", "localdub.core.model_fetch", "separation"]


def test_cancelling_stops_the_child_process(monkeypatch):
    import subprocess

    proc = FakeProc(0, hang=True)
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: proc)
    with pytest.raises(H.Cancelled):
        H.fetch_in_subprocess("supertonic", lambda: True)
    assert proc.terminated


def test_model_fetch_module_rejects_unknown_ids(capsys):
    import runpy

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("localdub.core.model_fetch", run_name="__main__", alter_sys=True)
    assert "usage: model_fetch" in str(exc.value)


@pytest.fixture
def nothing_installed(monkeypatch):
    """No model is installed, and nothing is downloaded for real."""
    monkeypatch.setattr(H.Handler, "installed", lambda self, e, ctx: False)
    monkeypatch.setattr("localdub.extras.packages_available", lambda: False)


def wait_idle(client: TestClient) -> dict:
    deadline = time.time() + 10
    data = client.get("/api/models").json()
    while time.time() < deadline and data["busy"]:
        time.sleep(0.05)
        data = client.get("/api/models").json()
    return data


def test_models_listed_with_roles_hardware_and_required_missing(
    client: TestClient, nothing_installed
):
    data = client.get("/api/models").json()
    ids = [m["id"] for m in data["models"]]
    assert {"whisper-large-v3", "parakeet-tdt-0.6b-v3", "translategemma-4b", "translategemma-12b",
            "supertonic", "youtube", "packages"} <= set(ids)  # fmt: skip
    assert set(data["required_missing"]) == {"whisper-large-v3", "translategemma-4b", "supertonic"}
    assert [r["id"] for r in data["roles"]][:3] == ["asr", "translation", "tts"]
    assert "cpu_threads" in data["hardware"] and data["catalog_version"]
    row = next(m for m in data["models"] if m["id"] == "translategemma-12b")
    assert row["choose_if"] and row["requirements"]["disk_gb"] > 8 and row["license"]["name"]
    assert data["busy"] is False


def test_jobs_are_refused_until_required_models_exist(
    client: TestClient, sample_mp4: Path, nothing_installed
):
    with sample_mp4.open("rb") as fh:
        r = client.post("/api/projects", files={"file": (sample_mp4.name, fh, "video/mp4")})
    assert r.status_code == 409 and "Models are missing" in r.json()["detail"]
    assert client.get("/api/projects").json() == []  # nothing half-created
    with sample_mp4.open("rb") as fh:
        ok = client.post(
            "/api/projects",
            files={"file": (sample_mp4.name, fh, "video/mp4")},
            data={"start": "false"},
        )
    assert ok.status_code == 201 and ok.json()["asr_id"] == "whisper-large-v3"
    assert client.post(f"/api/projects/{ok.json()['id']}/jobs").status_code == 409


def test_an_unknown_speech_model_is_rejected(client: TestClient, sample_mp4: Path):
    with sample_mp4.open("rb") as fh:
        r = client.post(
            "/api/projects",
            files={"file": (sample_mp4.name, fh, "video/mp4")},
            data={"start": "false", "asr_id": "translategemma-4b"},
        )
    assert r.status_code == 422


def test_download_validation(client: TestClient):
    assert client.post("/api/models/download", json={"ids": ["nope"]}).status_code == 422


def test_download_runs_in_background_and_reports_progress_and_errors(
    client: TestClient, monkeypatch, nothing_installed
):
    calls: list[str] = []

    def fake(self, e, ctx, progress):
        calls.append(e.id)
        progress(50, 100, "half")
        if e.id == "supertonic":
            raise RuntimeError("disk full")

    monkeypatch.setattr(H.Handler, "download", fake, raising=False)
    for cls in (H.WhisperHandler, H.SupertonicHandler):
        monkeypatch.setattr(cls, "download", fake)
    r = client.post("/api/models/download", json={"ids": ["whisper-large-v3", "supertonic"]})
    assert r.status_code == 202 and r.json()["started"] == ["whisper-large-v3", "supertonic"]
    states = {m["id"]: m["download"] for m in wait_idle(client)["models"]}
    assert calls == ["whisper-large-v3", "supertonic"]
    assert (
        states["supertonic"]["status"] == "error" and "disk full" in states["supertonic"]["error"]
    )
    # "downloaded" but still not usable is reported, not swallowed
    assert states["whisper-large-v3"]["status"] == "error"
    assert "not usable" in states["whisper-large-v3"]["error"]


def test_packages_are_installed_first_and_gate_the_models_that_need_them(
    client: TestClient, monkeypatch, nothing_installed
):
    order: list[str] = []
    for cls in (H.PackagesHandler, H.DemucsHandler):
        monkeypatch.setattr(cls, "download", lambda self, e, ctx, progress: order.append(e.id))
    # a model that needs PyTorch cannot be requested alone while the packages are missing ...
    assert client.post("/api/models/download", json={"ids": ["separation"]}).status_code == 409
    # ... but together with them it is fine, and the packages always go first
    r = client.post("/api/models/download", json={"ids": ["separation", "packages"]})
    assert r.status_code == 202 and r.json()["started"] == ["packages", "separation"]
    rows = {m["id"]: m for m in wait_idle(client)["models"]}
    assert order == ["packages", "separation"]
    assert rows["separation"]["available"] is False  # still locked: the (stubbed) check says no


def test_packages_cannot_be_installed_while_a_job_runs(client: TestClient, nothing_installed):
    db = client.app.state.db  # type: ignore[attr-defined]
    pid = db.create_project(
        name="p", original_name="p.mp4", input_rel="input/p.mp4", duration=1.0,
        source_lang="en", voice="F1", llm_model="m",
    )  # fmt: skip
    db.create_job(pid)
    r = client.post("/api/models/download", json={"ids": ["packages"]})
    assert r.status_code == 409 and "running dubbing job" in r.json()["detail"]
    assert client.delete("/api/models/supertonic").status_code in (200, 409)
    assert client.post("/api/models/whisper-large-v3/repair").status_code == 409


def test_no_job_can_start_while_the_packages_are_being_installed(
    client: TestClient, sample_mp4, nothing_installed
):
    mgr = client.app.state.models  # type: ignore[attr-defined]
    mgr._downloads["packages"] = {"status": "running"}
    with sample_mp4.open("rb") as fh:
        r = client.post("/api/projects", files={"file": (sample_mp4.name, fh, "video/mp4")})
    assert r.status_code == 409 and "being installed" in r.json()["detail"]
    mgr._downloads["packages"] = {"status": "done"}


def test_a_running_download_can_be_cancelled_and_its_partial_files_are_removed(
    client: TestClient, monkeypatch, nothing_installed
):
    started = []
    cleaned = []

    def slow(self, e, ctx, progress):
        started.append(e.id)
        for i in range(400):
            progress(i, 400, "Downloading")  # raises Cancelled once the user cancels
            time.sleep(0.02)

    monkeypatch.setattr(H.WhisperHandler, "download", slow)
    monkeypatch.setattr(
        H.WhisperHandler, "cleanup_partial", lambda self, e, ctx: cleaned.append(e.id)
    )
    assert (
        client.post("/api/models/download", json={"ids": ["whisper-large-v3"]}).status_code == 202
    )
    deadline = time.time() + 5
    while not started and time.time() < deadline:
        time.sleep(0.02)
    assert client.post("/api/models/whisper-large-v3/cancel").json() == {"cancelled": True}
    rows = {m["id"]: m for m in wait_idle(client)["models"]}
    assert rows["whisper-large-v3"]["download"]["status"] == "cancelled"
    assert cleaned == ["whisper-large-v3"]
    # nothing to cancel any more, and it can be started again
    assert client.post("/api/models/whisper-large-v3/cancel").json() == {"cancelled": False}
    assert (
        client.post("/api/models/download", json={"ids": ["whisper-large-v3"]}).status_code == 202
    )
    client.post("/api/models/whisper-large-v3/cancel")
    wait_idle(client)


def test_a_queued_download_is_cancelled_without_ever_starting(
    client: TestClient, monkeypatch, nothing_installed
):
    ran = []

    def fake(self, e, ctx, progress):
        ran.append(e.id)
        for i in range(200):
            progress(i, 200, "")
            time.sleep(0.02)

    for cls in (H.WhisperHandler, H.SupertonicHandler):
        monkeypatch.setattr(cls, "download", fake)
    client.post("/api/models/download", json={"ids": ["whisper-large-v3", "supertonic"]})
    assert client.post("/api/models/supertonic/cancel").json() == {"cancelled": True}
    client.post("/api/models/whisper-large-v3/cancel")
    rows = {m["id"]: m for m in wait_idle(client)["models"]}
    assert rows["supertonic"]["download"]["status"] == "cancelled"
    assert "supertonic" not in ran


def test_unpacking_cannot_be_cancelled(client: TestClient, monkeypatch, nothing_installed):
    release = []

    def install(self, e, ctx, progress):
        progress(5, 10, "Unpacking and installing (a few minutes)...")
        while not release:
            time.sleep(0.02)

    monkeypatch.setattr(H.PackagesHandler, "download", install)
    client.post("/api/models/download", json={"ids": ["packages"]})
    deadline = time.time() + 5
    row = {}
    while time.time() < deadline:
        row = next(m for m in client.get("/api/models").json()["models"] if m["id"] == "packages")
        if row["download"] and row["download"].get("cancellable") is False:
            break
        time.sleep(0.02)
    assert row["download"]["cancellable"] is False
    assert client.post("/api/models/packages/cancel").status_code == 409
    release.append(1)
    wait_idle(client)


def test_the_models_page_and_pickers_can_be_asked_for_in_slovak(
    client: TestClient, nothing_installed
):
    sk = client.get("/api/models?lang=sk").json()
    assert next(r for r in sk["roles"] if r["id"] == "asr")["title"] == "Rozpoznávanie reči"
    row = next(m for m in sk["models"] if m["id"] == "translategemma-12b")
    assert "Väčší súrodenec" in row["summary"] and row["choose_if"][0].startswith("Máte kartu")
    en = client.get("/api/models").json()
    assert next(m for m in en["models"] if m["id"] == "translategemma-12b")["summary"].startswith(
        "The larger"
    )
    opts = client.get("/api/options?lang=sk").json()
    assert any(
        c["id"] == "parakeet-tdt-0.6b-v3" and "NVIDIA" in c["title"] for c in opts["asr_choices"]
    )


def test_a_model_that_does_not_know_the_language_is_refused(client: TestClient, sample_mp4: Path):
    def create(asr_id: str, lang: str):
        with sample_mp4.open("rb") as fh:
            return client.post(
                "/api/projects",
                files={"file": (sample_mp4.name, fh, "video/mp4")},
                data={"start": "false", "asr_id": asr_id, "source_lang": lang},
            )

    assert create("whisper-small-en", "de").status_code == 422
    assert create("parakeet-tdt-0.6b-v3", "ja").status_code == 422
    assert create("parakeet-tdt-0.6b-v3", "pl").status_code == 201
    assert create("whisper-large-v3", "ja").status_code == 201
    opts = client.get("/api/options").json()
    assert {"de", "it", "es", "ja", "zh", "ru", "uk", "pl", "hu", "en", "auto"} == set(
        opts["source_languages"]
    )
    langs = {c["id"]: c["source_langs"] for c in opts["asr_choices"]}
    assert langs["whisper-large-v3"] is None and langs["whisper-small-en"] == ["en"]
