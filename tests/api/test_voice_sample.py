from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from localdub.api.app import create_app
from localdub.api.routes import segments as segments_module
from localdub.config import Settings
from localdub.core.modelmgr import handlers as H


class FakeTts:
    sample_rate = 22050
    calls = 0

    def unsupported_chars(self, text):
        return set()

    def synthesize(self, text, voice, lang, speed):
        FakeTts.calls += 1
        return np.zeros(2205, dtype=np.float32)

    def close(self):
        pass


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        segments_module, "default_providers", lambda s: type("P", (), {"tts": lambda self: FakeTts()})()
    )
    s = Settings(
        data_dir=tmp_path / "d", models_dir=tmp_path / "m", ollama_url="http://127.0.0.1:9"
    )
    with TestClient(create_app(s, start_queue=False)) as c:
        yield c


def test_a_voice_sample_is_made_once_per_voice(client, monkeypatch):
    monkeypatch.setattr(H.SupertonicHandler, "installed", lambda self, e, ctx: True)
    FakeTts.calls = 0
    r = client.get("/api/voices/F2/sample")
    assert (
        r.status_code == 200
        and r.headers["content-type"] == "audio/wav"
        and r.content[:4] == b"RIFF"
    )
    client.get("/api/voices/F2/sample")
    assert FakeTts.calls == 1
    assert client.get("/api/voices/nope/sample").status_code == 404


def test_samples_need_the_voice_model(client, monkeypatch):
    monkeypatch.setattr(H.SupertonicHandler, "installed", lambda self, e, ctx: False)
    r = client.get("/api/voices/F1/sample")
    assert r.status_code == 409 and "Slovak voice" in r.json()["detail"]
