from __future__ import annotations

import sys
from pathlib import Path

import pytest

from localdub.config import Settings
from localdub.core.media.ffmpeg import FFmpeg


@pytest.fixture(scope="session")
def sample_mp4(tmp_path_factory: pytest.TempPathFactory) -> Path:
    p = tmp_path_factory.mktemp("media") / "malý klip ✓.mp4"
    FFmpeg().run(
        [
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", "-t", "2",
            str(p),
        ]
    )  # fmt: skip
    return p


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", max_upload_mb=5)


FAKE_WORKER = """
import sys, time
from pathlib import Path
from localdub.api.db import Database
data_dir, job_id, mode = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
db = Database(data_dir / "localdub.sqlite")
db.update_job(job_id, pid=__import__("os").getpid(), stage="asr", progress=0.3)
if mode == "ok":
    db.update_job(job_id, stage="export", progress=1.0)
    db.finish_job(job_id, "done")
elif mode == "fail":
    db.finish_job(job_id, "failed", "boom")
elif mode == "crash":
    sys.exit(7)
elif mode == "hang":
    time.sleep(60)
"""


@pytest.fixture
def fake_worker(tmp_path: Path):
    script = tmp_path / "fake_worker.py"
    script.write_text(FAKE_WORKER, encoding="utf-8")

    def make(settings: Settings, mode: str):
        return lambda job_id: [
            sys.executable,
            str(script),
            str(settings.data_dir),
            str(job_id),
            mode,
        ]

    return make
