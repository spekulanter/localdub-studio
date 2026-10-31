import type { Health, Options, OriginalAudio } from "../api";
import { ORIGINAL_AUDIO_LABELS } from "../lib/format";
import { useRef, useState } from "react";
import { api } from "../api";
import { useT } from "../i18n";
import { InstallNotice } from "./InstallNotice";

/** Plays a short Slovak sample of the chosen voice, so the voice can be picked by ear. */
function VoiceSample({ voice }: { voice: string }) {
  const t = useT();
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [error, setError] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  async function play() {
    if (state === "playing") {
      audio.current?.pause();
      setState("idle");
      return;
    }
    setError(null);
    setState("loading");
    try {
      const res = await fetch(api.voiceSampleUrl(voice));
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? res.statusText);
      }
      const url = URL.createObjectURL(new Blob([await res.arrayBuffer()], { type: "audio/wav" }));
      const el = new Audio(url);
      audio.current = el;
      el.onended = () => {
        setState("idle");
        URL.revokeObjectURL(url);
      };
      await el.play();
      setState("playing");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setState("idle");
    }
  }

  return (
    <>
      <button type="button" onClick={() => void play()} disabled={state === "loading"} className="btn-secondary btn-sm shrink-0">
        {state === "loading" ? t("Preparing…") : state === "playing" ? t("Stop") : t("▶ Listen")}
      </button>
      {error && (
        <p className="basis-full text-xs text-bad" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

export interface Settings {
  source_lang: string;
  voice: string;
  llm_model: string;
  asr_id: string;
  original_audio: OriginalAudio;
  keep_original_track: boolean;
  diarize: boolean;
  clone_voice: boolean;
  clone_consent: boolean;
  num_speakers: number | null;
}

interface Props {
  options: Options;
  health: Health | null;
  value: Settings;
  onChange: (next: Settings) => void;
  /** The source language is fixed once a project exists. */
  lockSource?: boolean;
  disabled?: boolean;
  /** Called after the optional packages were installed from inside the app. */
  onPackagesInstalled?: () => void;
}

const field = "field";

export function OptionFields({ options, health, value, onChange, lockSource, disabled, onPackagesInstalled }: Props) {
  const t = useT();
  const packagesInstalled = onPackagesInstalled ?? (() => undefined);
  const pytorchIntro = (size: string) => t("This needs an extra download of about {size} (PyTorch).", { size });
  const set = <K extends keyof Settings>(key: K, v: Settings[K]) => onChange({ ...value, [key]: v });
  const asrChoices = options.asr_choices ?? [];
  const knows = (c: { source_langs: string[] | null }, lang: string) =>
    c.source_langs === null || (lang !== "auto" && c.source_langs.includes(lang));
  const chooseLanguage = (lang: string) => {
    const current = asrChoices.find((c) => c.id === value.asr_id);
    // a recognition model that does not know the new language is swapped for the default one
    const asr = current && !knows(current, lang) ? options.default_asr : value.asr_id;
    onChange({ ...value, source_lang: lang, asr_id: asr });
  };
  const known = new Map((options.translation_choices ?? []).map((c) => [c.tag ?? c.id, c]));
  const installedInOllama = new Set(health?.ollama.models ?? []);
  const llmChoices = Array.from(new Set([value.llm_model, ...known.keys(), ...installedInOllama]));
  const llmLabel = (m: string) => {
    const c = known.get(m);
    const ready = installedInOllama.has(m) || installedInOllama.has(`${m}:latest`);
    const status = c && c.status !== "available" && c.status !== "custom" ? ` [${t(c.status.replace("_", " "))}]` : "";
    return `${c ? c.title : m}${status}${health && !ready ? ` (${t("not downloaded")})` : ""}`;
  };
  return (
    <fieldset disabled={disabled} className="grid gap-4 sm:grid-cols-2">
      <label className="text-sm">
        <span className="mb-1 block font-medium">{t("Spoken language in the video")}</span>
        <select className={field} value={value.source_lang} disabled={lockSource} onChange={(e) => chooseLanguage(e.target.value)}>
          {Object.entries(options.source_languages).map(([code, name]) => (
            <option key={code} value={code}>
              {t(name)}
            </option>
          ))}
        </select>
      </label>
      <div className="text-sm">
        <label htmlFor="slovak-voice" className="mb-1 block font-medium">
          {t("Slovak voice")}
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <select id="slovak-voice" className={`${field} min-w-0 flex-1`} value={value.voice} onChange={(e) => set("voice", e.target.value)}>
            {options.voices.map((v) => (
              <option key={v} value={v}>
                {v} ({v.startsWith("F") ? t("female") : t("male")})
              </option>
            ))}
          </select>
          <VoiceSample voice={value.voice} />
        </div>
        <span className="mt-1 block text-xs text-muted">{t("Press Listen to hear the selected voice.")}</span>
      </div>
      <label className="text-sm">
        <span className="mb-1 block font-medium">{t("Speech recognition")}</span>
        <select className={field} value={value.asr_id} onChange={(e) => set("asr_id", e.target.value)}>
          {(asrChoices.some((c) => c.id === value.asr_id) ? asrChoices : [...asrChoices, { id: value.asr_id, title: value.asr_id, status: "available" as const, summary: "", tag: null, source_langs: null, installed: false }]).map((c) => (
            <option key={c.id} value={c.id} disabled={!knows(c, value.source_lang)}>
              {c.title}
              {c.status === "experimental" ? ` [${t("experimental")}]` : ""}
              {knows(c, value.source_lang) ? (c.installed ? "" : ` (${t("not downloaded")})`) : ` (${t("does not know this language")})`}
            </option>
          ))}
        </select>
        <span className="mt-1 block text-xs text-muted">{t("Choose and download models on the AI models page.")}</span>
      </label>
      <label className="text-sm">
        <span className="mb-1 block font-medium">{t("Translation model (Ollama)")}</span>
        <select className={field} value={value.llm_model} onChange={(e) => set("llm_model", e.target.value)}>
          {llmChoices.map((m) => (
            <option key={m} value={m}>
              {llmLabel(m)}
            </option>
          ))}
        </select>
      </label>
      <div className="text-sm">
        <span className="mb-1 block font-medium">{t("Original voice")}</span>
        {(Object.keys(ORIGINAL_AUDIO_LABELS) as OriginalAudio[]).map((k) => (
          <label key={k} className="flex items-center gap-2 py-0.5">
            <input
              type="radio"
              name="original_audio"
              checked={value.original_audio === k}
              disabled={k === "background" && !options.separation_available && value.original_audio !== k}
              onChange={() => set("original_audio", k)}
            />
            {t(ORIGINAL_AUDIO_LABELS[k])}
            {k === "background" && (
              <span className="chip chip-warn">{t("experimental")}</span>
            )}
          </label>
        ))}
        {!options.separation_available && <InstallNotice ids={["packages", "separation"]} intro={pytorchIntro} onInstalled={packagesInstalled} />}
        {value.original_audio === "background" && options.separation_available && (
          <p className="text-xs text-muted">
            {t("Uses the GPU for about half the video length and downloads an 80 MB model on first use. Singing and speech mixed into music may not separate cleanly.")}
          </p>
        )}
        <label className="mt-1 flex items-center gap-2 py-0.5">
          <input type="checkbox" checked={value.keep_original_track} onChange={(e) => set("keep_original_track", e.target.checked)} />
          {t("Also keep the untouched original as a 2nd audio track")}
        </label>
        {value.original_audio === "mute" && (
          <p className="mt-1 text-xs text-muted">
            {t("Muting also removes music and sound effects from the dubbed track.")}
          </p>
        )}
      </div>
      <div className="sm:col-span-2 border-t border-line pt-4">
        <p className="eyebrow">{t("Experimental")}</p>
      </div>
      <div className="text-sm sm:col-span-2">
        <label className="flex items-center gap-2 py-0.5">
          <input type="checkbox" checked={value.diarize} onChange={(e) => set("diarize", e.target.checked)} />
          {t("Detect different speakers and give each its own voice")} <span className="chip chip-warn">{t("experimental")}</span>
        </label>
        {value.diarize && (
          <div className="ml-6 mt-1 space-y-1">
            <label className="flex items-center gap-2">
              {t("Number of speakers (leave empty to detect)")}
              <input
                type="number"
                min={1}
                max={10}
                className="btn-secondary btn-sm w-20"
                value={value.num_speakers ?? ""}
                onChange={(e) => set("num_speakers", e.target.value === "" ? null : Number(e.target.value))}
              />
            </label>
            <p className="text-xs text-muted">
              {t("Runs on the CPU. The first use downloads two small model files (about 46 MB) from GitHub. Giving the exact speaker count is much more reliable than automatic detection.")}
            </p>
          </div>
        )}
      </div>
      <div className="text-sm sm:col-span-2">
        <label className="flex items-center gap-2 py-0.5">
          <input
            type="checkbox"
            checked={value.clone_voice}
            disabled={!options.separation_available && !value.clone_voice}
            onChange={(e) => onChange({ ...value, clone_voice: e.target.checked, clone_consent: e.target.checked ? value.clone_consent : false })}
          />
          {t("Make the Slovak voice sound like the original speaker")}{" "}
          <span className="chip chip-warn">{t("experimental")}</span>
        </label>
        {value.clone_voice && (
          <div className="ml-6 mt-1 space-y-1">
            <label className="flex items-start gap-2">
              <input type="checkbox" className="mt-1" checked={value.clone_consent} onChange={(e) => set("clone_consent", e.target.checked)} />
              <span>{t("I have the right to imitate the voices in this video (they are my own, or I have the speakers' permission).")}</span>
            </label>
            <p className="text-xs text-muted">
              {t("Runs locally on your GPU. It shifts the timbre of the generated voice towards the speaker; it is not a perfect copy. The finished file is marked as AI-generated.")}
            </p>
          </div>
        )}
        {!options.separation_available && (
          <div className="ml-6">
            <InstallNotice ids={["packages", "cloning"]} intro={pytorchIntro} onInstalled={packagesInstalled} />
          </div>
        )}
      </div>
    </fieldset>
  );
}
