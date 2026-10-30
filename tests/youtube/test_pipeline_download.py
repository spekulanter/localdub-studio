from __future__ import annotations

import json
from pathlib import Path

import pytest

from localdub.config import Settings
from localdub.pipeline import STAGES, Pipeline, PipelineError, Providers, RemoteSource
from localdub.worker import progress_fraction
from tests.integration.test_pipeline_media import FakeASR, FakeTranslator, FakeTTS


def make_video(dest: Path) -> None:
    from localdub.core.media.ffmpeg import FFmpeg

    dest.parent.mkdir(parents=True, exist_ok=True)
    FFmpeg().run(
        ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-f", "lavfi", "-i",
         "sine=frequency=440:sample_rate=48000", "-pix_fmt", "yuv420p", "-c:v", "libx264",
         "-c:a", "aac", "-t", "10", str(dest)],
    )  # fmt: skip


@pytest.fixture
def providers():
    return Providers(asr=FakeASR, translator=FakeTranslator, tts=FakeTTS)


@pytest.fixture
def settings(tmp_path):
    return Settings(work_dir=tmp_path / "work", models_dir=tmp_path / "models")


def test_download_is_the_first_stage():
    assert STAGES[0] == "download" and STAGES[1] == "probe"


def test_a_project_from_a_link_downloads_first_then_dubs(tmp_path, settings, providers):
    calls: list[str] = []

    def fetch(dest: Path, say) -> None:
        calls.append(dest.name)
        say("10.0%")
        make_video(dest)
        say("100.0%")

    seen: list[tuple[str, str]] = []
    pipe = Pipeline(
        tmp_path / "project" / "input" / "source.mp4", tmp_path / "project" / "work", settings,
        providers=providers, on_progress=lambda s, m: seen.append((s, m)),
        remote=RemoteSource(key="k1", fetch=fetch),
    )  # fmt: skip
    result = pipe.run()
    assert result["download"] == "ran" and result["export"] == "ran"
    assert calls == ["source.mp4"] and pipe.output_video.is_file()
    assert [m for s, m in seen if s == "download"] == ["running", "10.0%", "100.0%", "done"]
    # a second run neither downloads nor reprocesses anything
    again = pipe.run()
    assert set(again.values()) == {"skipped"} and calls == ["source.mp4"]


def test_a_finished_download_is_not_repeated_after_a_failure_later_on(
    tmp_path, settings, providers
):
    calls: list[int] = []

    def fetch(dest: Path, say) -> None:
        calls.append(1)
        make_video(dest)

    class Boom(FakeTranslator):
        def translate_segments(self, *a, **k):
            raise RuntimeError("translation failed")

    pipe = Pipeline(
        tmp_path / "p" / "input" / "source.mp4", tmp_path / "p" / "work", settings,
        providers=Providers(asr=FakeASR, translator=Boom, tts=FakeTTS),
        remote=RemoteSource(key="k", fetch=fetch),
    )  # fmt: skip
    with pytest.raises(PipelineError, match="translation failed"):
        pipe.run()
    pipe.providers = providers  # the user fixes the problem and retries
    assert pipe.run()["download"] == "skipped" and calls == [1]


def test_a_failed_download_is_reported_as_the_download_stage(tmp_path, settings, providers):
    def fetch(dest: Path, say) -> None:
        raise RuntimeError("This video is age-restricted")

    pipe = Pipeline(
        tmp_path / "p" / "input" / "source.mp4", tmp_path / "p" / "work", settings,
        providers=providers, remote=RemoteSource(key="k", fetch=fetch),
    )  # fmt: skip
    with pytest.raises(PipelineError) as exc:
        pipe.run()
    assert exc.value.stage == "download" and "age-restricted" in str(exc.value)


def test_a_fetcher_that_writes_nothing_is_an_error(tmp_path, settings, providers):
    pipe = Pipeline(
        tmp_path / "p" / "input" / "source.mp4", tmp_path / "p" / "work", settings,
        providers=providers, remote=RemoteSource(key="k", fetch=lambda dest, say: None),
    )  # fmt: skip
    with pytest.raises(PipelineError, match="file is missing"):
        pipe.run()


def test_uploaded_files_still_need_their_file_and_skip_the_download_stage(
    tmp_path, settings, providers
):
    pipe = Pipeline(tmp_path / "nope.mp4", tmp_path / "w", settings, providers=providers)
    with pytest.raises(PipelineError, match="Input video not found"):
        pipe.run()
    video = tmp_path / "v.mp4"
    make_video(video)
    result = Pipeline(video, tmp_path / "w2", settings, providers=providers).run()
    assert result["download"] == "ran"  # trivially: there is nothing to fetch


def test_progress_includes_the_download_only_for_links():
    plain = progress_fraction("probe", "running")
    linked = progress_fraction("probe", "running", has_download=True)
    assert plain == 0 and linked > 0.05  # the download takes its share first
    assert progress_fraction("download", "50.0% - 2MiB/s", has_download=True) == pytest.approx(
        progress_fraction("download", "done", has_download=True) / 2
    )
    values = [
        progress_fraction(s, st, has_download=True) for s in STAGES for st in ("running", "done")
    ]
    assert values == sorted(values) and values[-1] == pytest.approx(1.0)
    json.dumps(values)


def test_a_broken_leftover_file_is_downloaded_again(tmp_path, settings, providers):
    dest = tmp_path / "p" / "input" / "source.mp4"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"half a video")  # e.g. a download that was killed in the middle
    calls: list[int] = []

    def fetch(path: Path, say) -> None:
        calls.append(1)
        make_video(path)

    pipe = Pipeline(
        dest,
        tmp_path / "p" / "work",
        settings,
        providers=providers,
        remote=RemoteSource("k", fetch),
    )
    assert pipe.run()["export"] == "ran" and calls == [1]
    assert pipe.ff.probe(dest).duration > 5
