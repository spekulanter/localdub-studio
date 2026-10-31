from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from localdub.api.app import create_app, safe_filename
from localdub.config import Settings


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings, start_queue=False)) as c:
        yield c


def upload(client: TestClient, path: Path, **form: str):
    with path.open("rb") as fh:
        return client.post("/api/projects", files={"file": (path.name, fh, "video/mp4")}, data=form)


def test_safe_filename_keeps_unicode_and_strips_paths():
    assert safe_filename("../../evil/Ahoj：svet ✓ <1>.mp4") == "Ahoj：svet ✓ _1_.mp4"
    assert safe_filename("C:\\Users\\x\\clip.mp4") == "clip.mp4"
    assert safe_filename("   ...  ") == "video.mp4"
    assert len(safe_filename("a" * 300 + ".mp4")) <= 120


def test_ping_never_waits_for_ollama(client: TestClient, monkeypatch):
    import time

    client.app.state.settings.ollama_url = "http://10.255.255.1:11434"  # unroutable: would hang
    t0 = time.monotonic()
    assert client.get("/api/ping").json() == {"ok": True}
    assert time.monotonic() - t0 < 1.0


def test_options_and_health(client: TestClient):
    opts = client.get("/api/options").json()
    assert "F1" in opts["voices"] and opts["target_language"] == "sk"
    health = client.get("/api/health").json()
    assert health["ok"] is True and "reachable" in health["ollama"]


def test_upload_creates_project_and_queues_job(
    client: TestClient, sample_mp4: Path, settings: Settings
):
    r = upload(client, sample_mp4, voice="M2", original_audio="mute", keep_original_track="false")
    assert r.status_code == 201, r.text
    p = r.json()
    assert (
        p["voice"] == "M2" and p["original_audio"] == "mute" and p["keep_original_track"] is False
    )
    assert 1.5 < p["duration"] < 2.6
    assert p["latest_job"]["status"] == "queued" and p["has_output"] is False
    saved = settings.data_dir / "projects" / str(p["id"]) / "input" / sample_mp4.name
    assert saved.is_file()
    assert client.get(f"/api/projects/{p['id']}/source").status_code == 200


def test_upload_without_start_does_not_queue(client: TestClient, sample_mp4: Path):
    p = upload(client, sample_mp4, start="false").json()
    assert p["latest_job"] is None


@pytest.mark.parametrize(
    ("filename", "content", "form", "status"),
    [
        ("notes.txt", b"hello", {}, 415),
        ("fake.mp4", b"this is not a video", {}, 422),
        ("ok.mp4", b"x", {"voice": "ZZ"}, 422),
        ("ok.mp4", b"x", {"source_lang": "xx"}, 422),
    ],
)
def test_upload_rejections_leave_nothing_behind(
    client: TestClient,
    settings: Settings,
    filename: str,
    content: bytes,
    form: dict[str, str],
    status: int,
):
    r = client.post("/api/projects", files={"file": (filename, content)}, data=form)
    assert r.status_code == status, r.text
    assert client.get("/api/projects").json() == []
    projects = settings.data_dir / "projects"
    assert not projects.exists() or not any(projects.iterdir())


def test_upload_too_large(client: TestClient, settings: Settings):
    big = b"\0" * (settings.max_upload_mb * 1024 * 1024 + 10)
    r = client.post("/api/projects", files={"file": ("big.mp4", big)})
    assert r.status_code == 413
    assert client.get("/api/projects").json() == []


def test_patch_blocked_while_job_active_and_allowed_after_cancel(
    client: TestClient, sample_mp4: Path
):
    p = upload(client, sample_mp4).json()
    assert client.patch(f"/api/projects/{p['id']}", json={"voice": "F3"}).status_code == 409
    assert client.post(f"/api/projects/{p['id']}/jobs").status_code == 409
    job_id = p["latest_job"]["id"]
    assert client.post(f"/api/jobs/{job_id}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 409
    r = client.patch(f"/api/projects/{p['id']}", json={"voice": "F3", "original_audio": "mute"})
    assert r.status_code == 200 and r.json()["voice"] == "F3"
    assert client.patch(f"/api/projects/{p['id']}", json={"voice": "nope"}).status_code == 422


def test_segments_use_most_advanced_file(client: TestClient, sample_mp4: Path, settings: Settings):
    p = upload(client, sample_mp4, start="false").json()
    empty = client.get(f"/api/projects/{p['id']}/segments").json()
    assert empty["stage"] is None and empty["segments"] == [] and empty["edits_pending"] is False
    wd = settings.data_dir / "projects" / str(p["id"]) / "work"
    wd.mkdir(parents=True)
    seg = {
        "id": 1,
        "start": 0.0,
        "end": 1.0,
        "source_text": "Hi",
        "translated_text": "Ahoj",
        "fit_status": "ok",
        "words": [],
    }
    (wd / "asr.json").write_text(json.dumps({"segments": [{**seg, "translated_text": ""}]}))
    assert client.get(f"/api/projects/{p['id']}/segments").json()["stage"] == "asr"
    (wd / "translation.json").write_text(json.dumps({"segments": [seg]}))
    got = client.get(f"/api/projects/{p['id']}/segments").json()
    assert got["stage"] == "translation"
    first = got["segments"][0]
    assert {k: first[k] for k in ("id", "start", "end", "source_text", "translated_text")} == {
        k: seg[k] for k in ("id", "start", "end", "source_text", "translated_text")
    }
    assert first["fit_status"] is None  # timing is only meaningful once speech exists


def test_downloads_only_serve_known_outputs(
    client: TestClient, sample_mp4: Path, settings: Settings
):
    p = upload(client, sample_mp4, start="false").json()
    assert client.get(f"/api/projects/{p['id']}/files/video").status_code == 404
    assert client.get(f"/api/projects/{p['id']}/files/../../etc").status_code in (404, 422)
    assert client.get(f"/api/projects/{p['id']}/files/secret").status_code == 422
    wd = settings.data_dir / "projects" / str(p["id"]) / "work"
    wd.mkdir(parents=True)
    (wd / f"{sample_mp4.stem}.sk.srt").write_text("1\n", encoding="utf-8")
    r = client.get(f"/api/projects/{p['id']}/files/srt")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]


def test_delete_project_removes_files(client: TestClient, sample_mp4: Path, settings: Settings):
    p = upload(client, sample_mp4).json()
    assert client.delete(f"/api/projects/{p['id']}").status_code == 204
    assert client.get(f"/api/projects/{p['id']}").status_code == 404
    assert not (settings.data_dir / "projects" / str(p["id"])).exists()


def test_events_stream_ends_at_terminal_status(client: TestClient, sample_mp4: Path):
    p = upload(client, sample_mp4).json()
    job_id = p["latest_job"]["id"]
    client.app.state.db.update_job(job_id, status="running", progress=0.5)  # type: ignore[attr-defined]
    client.app.state.db.finish_job(job_id, "failed", "boom")  # type: ignore[attr-defined]
    with client.stream("GET", f"/api/jobs/{job_id}/events") as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    assert events[-1]["status"] == "failed" and events[-1]["error"] == "boom"
    assert "pid" not in events[-1]


def test_unknown_ids_are_404(client: TestClient):
    assert client.get("/api/projects/99").status_code == 404
    assert client.get("/api/jobs/99").status_code == 404
    assert client.post("/api/jobs/99/cancel").status_code == 404
    assert client.get("/api/jobs/99/events").status_code == 404


def test_voice_cloning_requires_explicit_consent(client: TestClient, sample_mp4: Path):
    r = upload(client, sample_mp4, clone_voice="true")
    assert r.status_code == 422 and "confirmation" in r.json()["detail"]
    assert client.get("/api/projects").json() == []
    ok = upload(client, sample_mp4, clone_voice="true", clone_consent="true", start="false")
    assert ok.status_code == 201 and ok.json()["clone_voice"] is True
    pid = ok.json()["id"]
    assert (
        client.patch(f"/api/projects/{pid}", json={"clone_voice": False}).json()["clone_voice"]
        is False
    )
    assert client.patch(f"/api/projects/{pid}", json={"clone_voice": True}).status_code == 422
    done = client.patch(f"/api/projects/{pid}", json={"clone_voice": True, "clone_consent": True})
    assert done.status_code == 200 and done.json()["clone_voice"] is True


def test_upload_limit_can_be_changed_and_survives_restart(client, settings):
    default = client.get("/api/options").json()["default_max_upload_mb"]
    assert client.put("/api/settings", json={"max_upload_mb": 5}).status_code == 422
    r = client.put("/api/settings", json={"max_upload_mb": 20000})
    assert r.status_code == 200
    opts = client.get("/api/options").json()
    assert opts["max_upload_mb"] == 20000 and opts["default_max_upload_mb"] == default
    assert (settings.data_dir / "user-settings.json").exists()
    assert client.put("/api/settings", json={"max_upload_mb": None}).json()["max_upload_mb"] == default
    assert client.get("/api/options").json()["max_upload_mb"] == default
