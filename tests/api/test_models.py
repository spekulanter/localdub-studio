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
    assert ids == ["whisper", "supertonic", "translation", "diarization", "separation", "cloning"]
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
