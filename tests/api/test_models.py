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


def test_a_pytorch_model_is_fetched_in_a_child_process_and_failures_are_explained(monkeypatch):
    import subprocess
    import sys

    seen: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="boom\nModuleNotFoundError: torch\n"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match=r"(?s)exit code 1.*ModuleNotFoundError: torch"):
        H.fetch_in_subprocess("separation")
    assert seen["cmd"] == [sys.executable, "-m", "localdub.core.model_fetch", "separation"]


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
