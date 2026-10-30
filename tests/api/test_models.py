from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from localdub.api.app import create_app
from localdub.config import Settings
from localdub.core import model_catalog
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


def test_models_listed_with_status_and_required_missing(client: TestClient):
    data = client.get("/api/models").json()
    ids = [m["id"] for m in data["models"]]
    assert ids == [
        "whisper", "supertonic", "translation", "diarization", "packages", "separation", "cloning",
    ]  # fmt: skip
    assert set(data["required_missing"]) == {"whisper", "supertonic", "translation"}
    # (separation lives in the shared Hugging Face cache, so it depends on the machine)
    assert [m["installed"] for m in data["models"] if m["group"] in ("core", "diarization")] == [
        False
    ] * 4
    assert data["busy"] is False


def test_jobs_are_refused_until_required_models_exist(client: TestClient, sample_mp4: Path):
    with sample_mp4.open("rb") as fh:
        r = client.post("/api/projects", files={"file": (sample_mp4.name, fh, "video/mp4")})
    assert r.status_code == 409 and "Required models are missing" in r.json()["detail"]
    assert client.get("/api/projects").json() == []  # nothing half-created
    with sample_mp4.open("rb") as fh:
        ok = client.post(
            "/api/projects",
            files={"file": (sample_mp4.name, fh, "video/mp4")},
            data={"start": "false"},
        )
    assert ok.status_code == 201
    assert client.post(f"/api/projects/{ok.json()['id']}/jobs").status_code == 409


def test_download_validation(client: TestClient):
    assert client.post("/api/models/download", json={"ids": ["nope"]}).status_code == 422


def test_download_runs_in_background_and_reports_progress_and_errors(
    client: TestClient, monkeypatch, strict_settings: Settings
):
    calls: list[str] = []

    def fake_download(spec, settings, progress):
        calls.append(spec.id)
        progress(50, 100, "half")
        if spec.id == "supertonic":
            raise RuntimeError("disk full")
        progress(100, 100, "Done")

    monkeypatch.setattr(model_catalog, "download", fake_download)
    r = client.post("/api/models/download", json={"ids": ["whisper", "supertonic"]})
    assert r.status_code == 202 and r.json()["started"] == ["whisper", "supertonic"]
    deadline = time.time() + 10
    while time.time() < deadline and client.get("/api/models").json()["busy"]:
        time.sleep(0.05)
    states = {m["id"]: m["download"] for m in client.get("/api/models").json()["models"]}
    assert calls == ["whisper", "supertonic"]
    assert states["whisper"]["status"] == "done"
    assert (
        states["supertonic"]["status"] == "error" and "disk full" in states["supertonic"]["error"]
    )


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


def test_ollama_names_match_with_or_without_latest_tag():
    from localdub.core.model_catalog import has_ollama_model

    assert has_ollama_model(["all-minilm:latest", "qwen3:8b"], "all-minilm")
    assert has_ollama_model(["translategemma:4b"], "translategemma:4b")
    assert not has_ollama_model(["translategemma:12b"], "translategemma:4b")
    assert not has_ollama_model([], "x")


def test_packages_are_installed_first_and_gate_the_models_that_need_them(
    client: TestClient, monkeypatch
):
    monkeypatch.setattr(model_catalog, "optional_packages_available", lambda: False)
    monkeypatch.setattr(model_catalog, "is_installed", lambda spec, settings: False)
    order: list[str] = []
    monkeypatch.setattr(model_catalog, "download", lambda spec, s, progress: order.append(spec.id))
    # a model that needs PyTorch cannot be requested alone while the packages are missing ...
    assert client.post("/api/models/download", json={"ids": ["separation"]}).status_code == 409
    # ... but together with them it is fine, and the packages always go first
    r = client.post("/api/models/download", json={"ids": ["separation", "packages"]})
    assert r.status_code == 202 and r.json()["started"] == ["packages", "separation"]
    deadline = time.time() + 10
    while time.time() < deadline and client.get("/api/models").json()["busy"]:
        time.sleep(0.05)
    assert order == ["packages", "separation"]
    rows = {m["id"]: m for m in client.get("/api/models").json()["models"]}
    assert rows["separation"]["available"] is False  # still locked: the (stubbed) check says no


def test_packages_cannot_be_installed_while_a_job_runs(client: TestClient, monkeypatch, sample_mp4):
    monkeypatch.setattr(model_catalog, "optional_packages_available", lambda: False)
    monkeypatch.setattr(model_catalog, "is_installed", lambda spec, settings: False)
    db = client.app.state.db  # type: ignore[attr-defined]
    pid = db.create_project(
        name="p", original_name="p.mp4", input_rel="input/p.mp4", duration=1.0,
        source_lang="en", voice="F1", llm_model="m",
    )  # fmt: skip
    db.create_job(pid)
    r = client.post("/api/models/download", json={"ids": ["packages"]})
    assert r.status_code == 409 and "running dubbing job" in r.json()["detail"]


def test_downloading_the_packages_runs_the_in_app_installer(monkeypatch, strict_settings: Settings):
    from localdub import extras

    calls: list[str] = []

    def fake_install(progress):
        calls.append("install")
        progress(5, 10, "Downloading torch")

    monkeypatch.setattr(extras, "install", fake_install)
    monkeypatch.setattr(extras, "packages_available", lambda: True)
    seen: list[tuple[int, int, str]] = []
    model_catalog.download(
        model_catalog.BY_ID["packages"], strict_settings, lambda d, t, m: seen.append((d, t, m))
    )
    assert calls == ["install"] and (5, 10, "Downloading torch") in seen
    assert all(m != "Done" for _, _, m in seen)  # the installer reports its own final state


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
        model_catalog._fetch_in_subprocess("separation")
    assert seen["cmd"] == [sys.executable, "-m", "localdub.core.model_fetch", "separation"]


def test_model_fetch_module_rejects_unknown_ids(capsys):
    import runpy

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("localdub.core.model_fetch", run_name="__main__", alter_sys=True)
    assert "usage: model_fetch" in str(exc.value)
