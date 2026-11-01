import { describe, expect, it } from "vitest";
import type { Options } from "../api";
import { initialSettings } from "./NewProject";

const options = {
  voices: ["F1", "F2", "M1", "M2"],
  source_languages: { en: "English", de: "German", auto: "Detect automatically" },
  default_voice: "F1",
  default_llm: "translategemma:4b",
  default_asr: "whisper-large-v3",
  asr_choices: [
    { id: "whisper-large-v3", title: "Whisper", status: "recommended", summary: "", tag: null, source_langs: null, installed: true },
    { id: "whisper-small-en", title: "small", status: "available", summary: "", tag: null, source_langs: ["en"], installed: true },
  ],
  separation_available: false,
} as unknown as Options;

describe("the defaults of a new dub", () => {
  it("starts with a male voice and no speech removal until its packages are there", () => {
    const s = initialSettings(options, {});
    expect(s.voice).toBe("M1");
    expect(s.original_audio).toBe("duck");
    expect(initialSettings({ ...options, separation_available: true }, {}).original_audio).toBe("background");
  });

  it("remembers the last choices but never the permission to clone a voice", () => {
    const s = initialSettings(options, { voice: "F2", original_audio: "mute", source_lang: "de", diarize: true, num_speakers: 3 });
    expect([s.voice, s.original_audio, s.source_lang, s.diarize, s.num_speakers]).toEqual(["F2", "mute", "de", true, 3]);
    expect(s.clone_voice).toBe(false);
    expect(s.clone_consent).toBe(false);
  });

  it("ignores remembered values that no longer exist", () => {
    const s = initialSettings(options, { voice: "X9", source_lang: "xx", asr_id: "gone", original_audio: "loud" as never });
    expect([s.voice, s.source_lang, s.asr_id, s.original_audio]).toEqual(["M1", "en", "whisper-large-v3", "duck"]);
  });

  it("falls back to the default speech model when the remembered one does not know the language", () => {
    expect(initialSettings(options, { source_lang: "de", asr_id: "whisper-small-en" }).asr_id).toBe("whisper-large-v3");
    expect(initialSettings(options, { source_lang: "en", asr_id: "whisper-small-en" }).asr_id).toBe("whisper-small-en");
  });
});
