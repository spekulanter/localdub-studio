import type { Job, OriginalAudio, Project, Stage } from "../api";

export function formatTime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export const STAGE_LABELS: Record<Stage, string> = {
  download: "Downloading from YouTube",
  probe: "Inspecting video",
  extract: "Extracting audio",
  asr: "Recognising speech",
  diarize: "Identifying speakers",
  translate: "Translating to Slovak",
  tts: "Generating Slovak voice",
  separate: "Separating dialogue from music",
  convert: "Matching the original voice",
  assemble: "Mixing audio",
  export: "Writing MP4 and subtitles",
};

export function stageLabel(stage: Job["stage"]): string {
  return stage === "" ? "Starting" : STAGE_LABELS[stage];
}

export function statusLabel(job: Job | null): string {
  if (!job) return "Not started";
  switch (job.status) {
    case "queued":
      return "Waiting in queue";
    case "running":
      return stageLabel(job.stage);
    case "done":
      return "Finished";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
  }
}

export function isActive(job: Job | null): boolean {
  return job?.status === "queued" || job?.status === "running";
}

/**
 * Earliest pipeline stage that must run again after changing project settings, or null if
 * nothing that affects the output changed.
 */
type Tunable = Pick<Project, "voice" | "llm_model" | "original_audio" | "keep_original_track" | "diarize" | "num_speakers" | "clone_voice">;

export function restartStage(before: Tunable, after: Tunable): Stage | null {
  if (before.diarize !== after.diarize || (after.diarize && before.num_speakers !== after.num_speakers)) return "diarize";
  if (before.llm_model !== after.llm_model) return "translate";
  if (before.voice !== after.voice) return "tts";
  if (before.clone_voice !== after.clone_voice && before.voice === after.voice) {
    if (before.original_audio === after.original_audio || after.original_audio !== "background") return "convert";
  }
  if (before.original_audio !== after.original_audio) {
    // Entering or leaving "background" needs (or discards) the Demucs split.
    return before.original_audio === "background" || after.original_audio === "background" ? "separate" : "assemble";
  }
  if (before.keep_original_track !== after.keep_original_track) return "export";
  return null;
}

export const ORIGINAL_AUDIO_LABELS: Record<OriginalAudio, string> = {
  duck: "Keep quietly under the dub",
  mute: "Mute completely (dub only)",
  background: "Remove the speech, keep music and effects",
};
