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

  it("tells speakers apart by default, and clones the voice by default only where it can work", () => {
    const first = initialSettings(options, {});
    expect(first.diarize).toBe(true);
    expect(first.clone_voice).toBe(false); // its packages are not installed in this setup
    const ready = initialSettings({ ...options, separation_available: true }, {});
    expect(ready.clone_voice).toBe(true);
    expect(ready.clone_consent).toBe(false); // a first-time user has to tick the permission themselves
    expect(initialSettings({ ...options, separation_available: true }, { clone_voice: false, diarize: false })).toMatchObject({ clone_voice: false, diarize: false });
  });

  it("does not keep the untouched original as a second track unless asked", () => {
    expect(initialSettings(options, {}).keep_original_track).toBe(false);
    expect(initialSettings(options, { keep_original_track: true }).keep_original_track).toBe(true);
  });

  it("keeps the permission to imitate voices once the user has ticked it, and only while cloning is on", () => {
    const on = { ...options, separation_available: true };
    expect(initialSettings(on, { clone_voice: true, clone_consent: true }).clone_consent).toBe(true);
    expect(initialSettings(on, { clone_voice: false, clone_consent: true }).clone_consent).toBe(false);
    expect(initialSettings(options, { clone_voice: true, clone_consent: true }).clone_consent).toBe(false); // no packages
  });

  it("remembers the last choices", () => {
    const s = initialSettings({ ...options, separation_available: true }, { voice: "F2", original_audio: "mute", source_lang: "de", diarize: true, num_speakers: 3, clone_voice: true });
    expect([s.voice, s.original_audio, s.source_lang, s.diarize, s.num_speakers]).toEqual(["F2", "mute", "de", true, 3]);
    expect(s.clone_voice).toBe(true);
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
