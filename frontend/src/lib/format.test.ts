import { describe, expect, it } from "vitest";
import type { Job } from "../api";
import { formatTime, isActive, restartStage, statusLabel } from "./format";

const base = { voice: "F1", llm_model: "m", original_audio: "duck", keep_original_track: true, diarize: false, clone_voice: false, num_speakers: null } as const;

describe("formatTime", () => {
  it("formats m:ss", () => {
    expect(formatTime(0)).toBe("0:00");
    expect(formatTime(65.9)).toBe("1:05");
    expect(formatTime(-3)).toBe("0:00");
  });
});

describe("restartStage", () => {
  it("returns the earliest affected stage", () => {
    expect(restartStage(base, base)).toBeNull();
    expect(restartStage(base, { ...base, original_audio: "mute" })).toBe("assemble");
    expect(restartStage(base, { ...base, original_audio: "background" })).toBe("separate");
    expect(restartStage({ ...base, original_audio: "background" }, { ...base, original_audio: "mute" })).toBe("separate");
    expect(restartStage(base, { ...base, keep_original_track: false })).toBe("export");
    expect(restartStage(base, { ...base, voice: "M1", original_audio: "mute" })).toBe("tts");
    expect(restartStage(base, { ...base, llm_model: "x", voice: "M1" })).toBe("translate");
    expect(restartStage(base, { ...base, diarize: true, llm_model: "x" })).toBe("diarize");
    expect(restartStage({ ...base, diarize: true }, { ...base, diarize: true, num_speakers: 3 })).toBe("diarize");
    expect(restartStage(base, { ...base, num_speakers: 3 })).toBeNull(); // ignored while diarization is off
  });
});

describe("job helpers", () => {
  const job = (status: Job["status"], stage: Job["stage"] = ""): Job => ({
    id: 1, project_id: 1, status, stage, message: "", progress: 0, error: null, from_stage: null,
    attempts: 1, created_at: 0, started_at: null, finished_at: null,
  });
  it("labels states", () => {
    expect(statusLabel(null)).toBe("Not started");
    expect(statusLabel(job("running", "tts"))).toBe("Generating Slovak voice");
    expect(statusLabel(job("failed"))).toBe("Failed");
  });
  it("detects active jobs", () => {
    expect(isActive(job("queued"))).toBe(true);
    expect(isActive(job("done"))).toBe(false);
    expect(isActive(null)).toBe(false);
  });
});

describe("voice cloning restart", () => {
  const b = { voice: "F1", llm_model: "m", original_audio: "duck", keep_original_track: true, diarize: false, clone_voice: false, num_speakers: null } as const;
  it("only needs the convert step", () => {
    expect(restartStage(b, { ...b, clone_voice: true })).toBe("convert");
    expect(restartStage({ ...b, clone_voice: true }, b)).toBe("convert");
    expect(restartStage(b, { ...b, clone_voice: true, voice: "M1" })).toBe("tts");
  });
});
