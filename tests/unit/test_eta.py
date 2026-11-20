"""Remaining-time estimate: priors from the audio length, a stage's own pace, learned speeds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from localdub.config import Settings
from localdub.core import progress
from localdub.core.eta import DEFAULTS, Estimator, Rates, fraction_of, rate_key
from localdub.worker import job_plan

PLAN = ["probe", "extract", "asr", "translate", "tts", "assemble", "export"]


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make(audio_s: float = 600.0, rates: Rates | None = None) -> tuple[Estimator, Clock]:
    clock = Clock()
    return Estimator(PLAN, audio_s, rates or Rates(None), clock=clock), clock


def prior(stage: str, audio_s: float = 600.0) -> float:
    overhead, rate = DEFAULTS[stage]
    return overhead + rate * audio_s


def test_progress_messages_are_read():
    assert fraction_of("37%") == 0.37 and fraction_of("37.5% - 2MiB/s") == 0.375
    assert fraction_of("3/10") == 0.2  # item 3 has started: 2 are done
    assert fraction_of("running") is None and fraction_of("Merging...") is None


def test_before_anything_runs_the_estimate_is_the_sum_of_the_stages():
    est, _ = make()
    assert est.remaining() == pytest.approx(sum(prior(s) for s in PLAN))
    assert est.progress() == 0.0


def test_a_stage_with_its_own_pace_overrides_the_prior():
    est, clock = make()
    est.update("asr", "running")  # probe and extract were skipped (still valid)
    clock.t += 30  # loading the model; no progress yet
    est.update("asr", "0%")
    clock.t += 60
    est.update("asr", "20%")  # 20 % in 60 s: this computer needs 4 more minutes for the rest
    later = sum(prior(s) for s in ("translate", "tts", "assemble", "export"))
    assert est.remaining() == pytest.approx(240 + later)
    assert prior("asr") < 60  # the prior alone would have said "under a minute": much too fast


def test_a_speed_learned_here_is_trusted_longer_than_the_laptops():
    def left_after_20_percent(rates: Rates) -> float:
        est, clock = make(rates=rates)
        est.update("asr", "running")
        est.update("asr", "0%")
        clock.t += 60
        est.update("asr", "20%")
        return est.remaining() - sum(prior(s) for s in ("translate", "tts", "assemble", "export"))

    learned = Rates(None)
    learned.learned["asr"] = DEFAULTS["asr"][1]  # learned here, same number as the laptop's
    assert left_after_20_percent(Rates(None)) == pytest.approx(240)  # the stage's own pace only
    blended = left_after_20_percent(learned)  # still part expectation (0.8 * 43.4 s), part pace
    assert prior("asr") * 0.8 < blended < 240


def test_the_bar_follows_the_expected_time_of_each_stage():
    est, _ = make()
    est.update("translate", "running")
    est.update("translate", "50%")
    weights = {s: prior(s) for s in PLAN}
    done = sum(weights[s] for s in ("probe", "extract", "asr")) + weights["translate"] / 2
    assert est.progress() == pytest.approx(done / sum(weights.values()))
    est.update("translate", "done")
    est.update("tts", "running")
    assert est.progress() > done / sum(weights.values())


def test_a_slow_stage_without_progress_does_not_go_below_zero():
    est, clock = make()
    est.update("export", "running")
    clock.t += 10 * prior("export")
    assert est.remaining() == 0.0


def test_learned_speeds_replace_the_laptop_numbers_and_survive_a_restart(tmp_path: Path):
    path = tmp_path / "timings.json"
    rates = Rates(path)
    keys = {"asr": rate_key("asr", asr_id="whisper-large-v3")}
    est = Estimator(PLAN, 600.0, rates, keys=keys, clock=(clock := Clock()))
    est.update("asr", "running")
    clock.t += 8 + 600  # a computer without NVIDIA: as long as the audio
    est.update("asr", "done")
    est.learn()

    again = Rates(path)
    assert again.learned["asr:whisper-large-v3"] == pytest.approx(1.0)
    assert again.expected("asr", "asr:whisper-large-v3", 60) == pytest.approx(8 + 60)
    assert again.expected("asr", "asr:parakeet-tdt-0.6b-v3", 60) == pytest.approx(prior("asr", 60))
    again.learn("asr", "asr:whisper-large-v3", 8 + 1200, 600)  # later runs move it halfway
    assert again.learned["asr:whisper-large-v3"] == pytest.approx(1.5)


def test_short_clips_and_unreadable_files_teach_nothing(tmp_path: Path):
    rates = Rates(tmp_path / "timings.json")
    rates.learn("tts", "tts", 30, 20)  # 20 s of audio: mostly model loading
    assert rates.learned == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert Rates(bad).learned == {}
    bad.write_text(json.dumps({"rates": {"tts": -1, "asr": "x", "export": 0.02}}), encoding="utf-8")
    assert Rates(bad).learned == {"export": 0.02}


def test_models_learn_their_own_speed():
    assert rate_key("translate", llm_model="translategemma:12b") == "translate:translategemma:12b"
    assert rate_key("asr", asr_id="whisper-large-v3") == "asr:whisper-large-v3"
    assert rate_key("tts") == "tts"


def test_idle_stages_are_left_out_of_the_plan():
    s = Settings()
    s.diarization_enabled, s.voice_cloning_enabled, s.original_audio = False, False, "duck"
    assert job_plan(s, has_download=False) == [
        "probe", "extract", "asr", "translate", "tts", "assemble", "export"
    ]  # fmt: skip
    s.diarization_enabled, s.voice_cloning_enabled, s.original_audio = True, True, "background"
    assert job_plan(s, has_download=True)[0] == "download"
    assert {"diarize", "separate", "convert"} <= set(job_plan(s, has_download=True))


def test_models_report_progress_only_inside_a_stage():
    seen: list[str] = []
    progress.report(1, 2)  # outside: nothing happens
    with progress.reporting(progress.percent_reporter(seen.append)):
        for done in range(0, 1001):
            progress.report(done, 1000)  # a word at a time
        progress.report(5, 0)  # no total: ignored
    progress.report(1, 2)
    assert seen[0] == "0%" and seen[-1] == "100%" and len(seen) == 101  # once per whole percent
