from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from localdub.api.app import create_app
from localdub.config import Settings
from localdub.core.timeline.models import DialogueSegment


def seg(i: int, start: float, end: float, en: str, sk: str) -> dict:
    return DialogueSegment(
        id=i, start=start, end=end, source_text=en, translated_text=sk
    ).model_dump(mode="json")


SEGS = [
    seg(1, 0.0, 1.5, "Hello there.", "Ahoj."),
    seg(2, 2.0, 3.5, "How are you?", "Ako sa máš?"),
    seg(3, 4.0, 5.5, "Fine, thanks.", "Dobre, vďaka."),
]


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings, start_queue=False)) as c:
        yield c


@pytest.fixture
def project(client: TestClient, sample_mp4: Path, settings: Settings) -> dict:
    with sample_mp4.open("rb") as fh:
        p = client.post(
            "/api/projects",
            files={"file": (sample_mp4.name, fh, "video/mp4")},
            data={"start": "false"},
        ).json()
    client.app.state.db.update_project(p["id"], duration=10.0)  # type: ignore[attr-defined]
    wd = settings.data_dir / "projects" / str(p["id"]) / "work"
    wd.mkdir(parents=True)
    p["wd"] = wd
    return p


def write_stage(wd: Path, name: str, segs: list[dict]) -> None:
    (wd / name).write_text(json.dumps({"segments": segs}), encoding="utf-8")


def url(p: dict, tail: str = "") -> str:
    return f"/api/projects/{p['id']}/segments{tail}"


def test_cannot_edit_before_translation(client: TestClient, project: dict):
    assert client.patch(url(project, "/1"), json={"translated_text": "x"}).status_code == 409
    write_stage(project["wd"], "asr.json", [dict(s, translated_text="") for s in SEGS])
    assert client.patch(url(project, "/1"), json={"translated_text": "x"}).status_code == 409


def test_edit_text_voice_and_review_are_overlaid(client: TestClient, project: dict):
    write_stage(project["wd"], "translation.json", SEGS)
    r = client.patch(
        url(project, "/2"), json={"translated_text": " Ako sa dnes máte? ", "voice_id": "M3"}
    )
    assert r.status_code == 200, r.text
    row = r.json()
    assert (
        row["translated_text"] == "Ako sa dnes máte?"
        and row["voice_id"] == "M3"
        and row["edited"] is True
    )
    assert (
        client.patch(url(project, "/2"), json={"review_status": "approved"}).json()["review_status"]
        == "approved"
    )
    # the earlier edit is kept when another field is patched
    got = client.get(url(project)).json()
    assert got["stage"] == "translation"
    assert got["segments"][1]["translated_text"] == "Ako sa dnes máte?"
    assert got["segments"][0]["edited"] is False
    # null clears just that field's edit
    cleared = client.patch(url(project, "/2"), json={"translated_text": None}).json()
    assert cleared["translated_text"] == "Ako sa máš?" and cleared["voice_id"] == "M3"


def test_validation(client: TestClient, project: dict):
    write_stage(project["wd"], "translation.json", SEGS)
    assert client.patch(url(project, "/1"), json={"voice_id": "ZZ"}).status_code == 422
    assert client.patch(url(project, "/1"), json={"translated_text": "x" * 601}).status_code == 422
    assert client.patch(url(project, "/9"), json={"translated_text": "x"}).status_code == 404
    assert client.patch(url(project, "/1"), json={"review_status": "bogus"}).status_code == 422


def test_timing_edit_rules_and_revert(client: TestClient, project: dict):
    write_stage(project["wd"], "translation.json", SEGS)
    ok = client.patch(url(project, "/2"), json={"start": 1.8, "end": 3.9})
    assert ok.status_code == 200 and (ok.json()["start"], ok.json()["end"]) == (1.8, 3.9)
    assert (
        client.patch(url(project, "/2"), json={"start": 1.0}).status_code == 422
    )  # overlaps segment 1
    assert (
        client.patch(url(project, "/2"), json={"end": 4.2}).status_code == 422
    )  # overlaps segment 3
    assert client.patch(url(project, "/2"), json={"end": 1.9}).status_code == 422  # too short
    assert client.patch(url(project, "/3"), json={"end": 99}).status_code == 422  # beyond the video
    back = client.patch(url(project, "/2"), json={"start": None, "end": None}).json()
    assert (back["start"], back["end"]) == (2.0, 3.5)


def test_revert_endpoint_removes_all_edits_of_a_segment(client: TestClient, project: dict):
    write_stage(project["wd"], "translation.json", SEGS)
    client.patch(url(project, "/3"), json={"translated_text": "Super", "voice_id": "F2"})
    assert client.delete(url(project, "/3/edit")).status_code == 204
    row = client.get(url(project)).json()["segments"][2]
    assert row["translated_text"] == "Dobre, vďaka." and row["edited"] is False


def test_edits_pending_until_rendered(client: TestClient, project: dict):
    wd = project["wd"]
    write_stage(wd, "translation.json", SEGS)
    write_stage(wd, "tts.json", SEGS)
    old = (wd / "tts.json").stat().st_mtime - 10
    os.utime(wd / "tts.json", (old, old))
    assert client.get(url(project)).json()["edits_pending"] is False
    assert (
        client.patch(url(project, "/1"), json={"translated_text": "Čau"}).json()["edits_pending"]
        is True
    )
    now = (wd / "edits.json").stat().st_mtime + 5
    os.utime(wd / "tts.json", (now, now))
    assert client.get(url(project)).json()["edits_pending"] is False


def test_stale_edit_is_flagged_not_applied(client: TestClient, project: dict):
    write_stage(project["wd"], "translation.json", SEGS)
    client.patch(url(project, "/1"), json={"translated_text": "Čau"})
    changed = [dict(SEGS[0], source_text="Totally different sentence")] + SEGS[1:]
    write_stage(project["wd"], "translation.json", changed)
    row = client.get(url(project)).json()["segments"][0]
    assert (
        row["stale_edit"] is True and row["translated_text"] == "Ahoj." and row["edited"] is False
    )


def test_speaker_voices(client: TestClient, project: dict):
    write_stage(project["wd"], "translation.json", [dict(SEGS[0], speaker_id="S2"), *SEGS[1:]])
    assert (
        client.put(
            f"/api/projects/{project['id']}/speakers", json={"voices": {"S2": "bad"}}
        ).status_code
        == 422
    )
    got = client.put(
        f"/api/projects/{project['id']}/speakers", json={"voices": {"S2": "M4"}}
    ).json()
    assert got["speaker_voices"] == {"S2": "M4"}
    assert got["segments"][0]["voice_id"] == "M4" and got["segments"][1]["voice_id"] is None


def test_editing_blocked_while_job_active(client: TestClient, project: dict):
    write_stage(project["wd"], "translation.json", SEGS)
    client.post(f"/api/projects/{project['id']}/jobs")
    assert client.patch(url(project, "/1"), json={"translated_text": "x"}).status_code == 409


def test_segment_audio(client: TestClient, project: dict):
    wd = project["wd"]
    assert client.get(url(project, "/1/audio")).status_code == 404
    (wd / "tts" / "clips").mkdir(parents=True)
    sf.write(wd / "tts" / "clips" / "seg_0001.wav", np.zeros(4800, np.float32), 48000)
    write_stage(wd, "tts.json", [dict(SEGS[0], audio_path="tts/clips/seg_0001.wav"), *SEGS[1:]])
    r = client.get(url(project, "/1/audio"))
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert client.get(url(project, "/2/audio")).status_code == 404
    assert client.get(url(project)).json()["segments"][0]["has_audio"] is True


class StubTTS:
    sample_rate = 44100

    def __init__(self) -> None:
        self.texts: list[tuple[str, str, float]] = []

    def unsupported_chars(self, text: str) -> list[str]:
        return ["€"] if "€" in text else []

    def synthesize(self, text: str, *, voice: str, lang: str, speed: float = 1.0):
        self.texts.append((text, voice, speed))
        return np.zeros(int(0.05 * len(text) / speed * self.sample_rate), np.float32)

    def close(self) -> None:
        pass


def test_preview_uses_unsaved_text_and_voice_and_speeds_up_to_fit(
    client: TestClient, project: dict
):
    write_stage(project["wd"], "translation.json", SEGS)
    stub = StubTTS()
    client.app.state.preview_tts = stub  # type: ignore[attr-defined]
    r = client.post(
        url(project, "/1/preview"),
        json={"text": "Ahoj, ako sa dnes máš €? " + "veľmi dlhá veta " * 6, "voice": "M2"},
    )
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert stub.texts[0][1] == "M2"
    assert "€" not in stub.texts[0][0]
    assert float(r.headers["X-Window"]) > 0 and float(r.headers["X-Audio-Duration"]) > 0
    assert len(stub.texts) == 2 and stub.texts[1][2] > stub.texts[0][2]  # too long: retried faster
    assert client.post(url(project, "/1/preview"), json={"text": "   "}).status_code == 422
    assert client.post(url(project, "/1/preview"), json={"voice": "ZZ"}).status_code == 422
    assert client.post(url(project, "/7/preview"), json={}).status_code == 404
