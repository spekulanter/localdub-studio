import type { Health, Options, OriginalAudio } from "../api";
import { ORIGINAL_AUDIO_LABELS } from "../lib/format";

export interface Settings {
  source_lang: string;
  voice: string;
  llm_model: string;
  original_audio: OriginalAudio;
  keep_original_track: boolean;
  diarize: boolean;
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
}

const field = "w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";

export function OptionFields({ options, health, value, onChange, lockSource, disabled }: Props) {
  const set = <K extends keyof Settings>(key: K, v: Settings[K]) => onChange({ ...value, [key]: v });
  const llmChoices = Array.from(new Set([value.llm_model, ...(health?.ollama.models ?? [])]));
  return (
    <fieldset disabled={disabled} className="grid gap-4 sm:grid-cols-2">
      <label className="text-sm">
        <span className="mb-1 block font-medium">Spoken language in the video</span>
        <select className={field} value={value.source_lang} disabled={lockSource} onChange={(e) => set("source_lang", e.target.value)}>
          {Object.entries(options.source_languages).map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        <span className="mb-1 block font-medium">Slovak voice</span>
        <select className={field} value={value.voice} onChange={(e) => set("voice", e.target.value)}>
          {options.voices.map((v) => (
            <option key={v} value={v}>
              {v} ({v.startsWith("F") ? "female" : "male"})
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        <span className="mb-1 block font-medium">Translation model (Ollama)</span>
        <select className={field} value={value.llm_model} onChange={(e) => set("llm_model", e.target.value)}>
          {llmChoices.map((m) => (
            <option key={m} value={m}>
              {m}
              {health && !health.ollama.models.includes(m) ? " (not installed)" : ""}
            </option>
          ))}
        </select>
      </label>
      <div className="text-sm">
        <span className="mb-1 block font-medium">Original voice</span>
        {(Object.keys(ORIGINAL_AUDIO_LABELS) as OriginalAudio[]).map((k) => (
          <label key={k} className="flex items-center gap-2 py-0.5">
            <input type="radio" name="original_audio" checked={value.original_audio === k} onChange={() => set("original_audio", k)} />
            {ORIGINAL_AUDIO_LABELS[k]}
          </label>
        ))}
        <label className="mt-1 flex items-center gap-2 py-0.5">
          <input type="checkbox" checked={value.keep_original_track} onChange={(e) => set("keep_original_track", e.target.checked)} />
          Also keep the untouched original as a 2nd audio track
        </label>
        {value.original_audio === "mute" && (
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Muting also removes music and sound effects from the dubbed track.
          </p>
        )}
      </div>
      <div className="text-sm sm:col-span-2">
        <label className="flex items-center gap-2 py-0.5">
          <input type="checkbox" checked={value.diarize} onChange={(e) => set("diarize", e.target.checked)} />
          Detect different speakers and give each its own voice <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-900 dark:bg-amber-950 dark:text-amber-200">experimental</span>
        </label>
        {value.diarize && (
          <div className="ml-6 mt-1 space-y-1">
            <label className="flex items-center gap-2">
              Number of speakers (leave empty to detect)
              <input
                type="number"
                min={1}
                max={10}
                className="w-20 rounded-md border border-slate-300 bg-white px-2 py-1 dark:border-slate-700 dark:bg-slate-900"
                value={value.num_speakers ?? ""}
                onChange={(e) => set("num_speakers", e.target.value === "" ? null : Number(e.target.value))}
              />
            </label>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Runs on the CPU. The first use downloads two small model files (about 46 MB) from GitHub. Giving the
              exact speaker count is much more reliable than automatic detection.
            </p>
          </div>
        )}
      </div>
    </fieldset>
  );
}
