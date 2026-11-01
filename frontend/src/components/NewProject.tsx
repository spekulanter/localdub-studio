import { useRef, useState } from "react";
import { api, type Health, type Options, type Project, type YoutubeChoice } from "../api";
import { useT } from "../i18n";
import { OptionFields, type Settings } from "./OptionFields";
import { YoutubeSource } from "./YoutubeSource";

interface Props {
  options: Options;
  health: Health | null;
  onCreated: (p: Project) => void;
  /** Required AI models are not downloaded yet. */
  modelsMissing?: boolean;
  /** Optional packages were installed: reload what the server can do. */
  onOptionsChanged?: () => void;
}

function UploadLimit({ options, onChanged }: { options: Options; onChanged?: () => void }) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [gb, setGb] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const show = (mb: number) => `${Math.round((mb / 1024) * 10) / 10} GB`;
  const save = (mb: number | null) => {
    setProblem(null);
    api
      .setUploadLimit(mb)
      .then(() => {
        setEditing(false);
        onChanged?.();
      })
      .catch((e: unknown) => setProblem(e instanceof Error ? e.message : String(e)));
  };
  return (
    <div className="text-xs text-muted">
      {t("Largest file: {size} (default {def}).", { size: show(options.max_upload_mb), def: show(options.default_max_upload_mb) })}{" "}
      {!editing && (
        <button type="button" className="underline" onClick={() => { setGb(String(Math.round((options.max_upload_mb / 1024) * 10) / 10)); setEditing(true); }}>
          {t("Change")}
        </button>
      )}
      {editing && (
        <span className="mt-1 flex flex-wrap items-center justify-center gap-2">
          <label className="flex items-center gap-1">
            {t("Limit in GB")}
            <input className="field w-24" type="number" min={0.1} step={0.5} value={gb} onChange={(e) => setGb(e.target.value)} />
          </label>
          <button type="button" className="btn-primary btn-sm" disabled={!(Number(gb) > 0)} onClick={() => save(Math.round(Number(gb) * 1024))}>
            {t("Save")}
          </button>
          <button type="button" className="btn-ghost btn-sm" onClick={() => save(null)}>
            {t("Back to default")}
          </button>
          <button type="button" className="btn-ghost btn-sm" onClick={() => setEditing(false)}>
            {t("Cancel")}
          </button>
          <span className="basis-full">{t("The video is copied into the app's data folder first; free space there: {size}.", { size: show(options.free_disk_mb) })}</span>
        </span>
      )}
      {problem && <span className="block text-bad">{problem}</span>}
    </div>
  );
}

const ACCEPT = ".mp4,.m4v,.mov,.mkv,video/mp4";

export function NewProject({ options, health, onCreated, modelsMissing = false, onOptionsChanged }: Props) {
  const t = useT();
  const [source, setSource] = useState<"file" | "youtube">("file");
  const [youtube, setYoutube] = useState<YoutubeChoice[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<string | null>(null);
  const [settings, setSettings] = useState<Settings>({
    source_lang: "en",
    voice: options.default_voice,
    llm_model: options.default_llm,
    asr_id: options.default_asr,
    original_audio: "duck",
    keep_original_track: true,
    diarize: false,
    clone_voice: false,
    clone_consent: false,
    num_speakers: null,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const limit = options.max_upload_mb * 1024 * 1024;
  const tooBig = files.filter((f) => f.size > limit);

  async function submitYoutube() {
    if (youtube.length === 0) return;
    setBusy(true);
    setError(null);
    const failures: string[] = [];
    let first: Project | null = null;
    for (const [i, choice] of youtube.entries()) {
      setProgress(youtube.length > 1 ? t("Adding {i} of {n}: {name}", { i: i + 1, n: youtube.length, name: choice.info.title }) : null);
      try {
        const created = await api.createFromYoutube({
          url: choice.url,
          quality: choice.quality,
          cookies_browser: choice.cookies_browser,
          source_lang: settings.source_lang,
          voice: settings.voice,
          llm_model: settings.llm_model,
          asr_id: settings.asr_id,
          original_audio: settings.original_audio,
          keep_original_track: settings.keep_original_track,
          diarize: settings.diarize,
          num_speakers: settings.diarize ? settings.num_speakers : null,
          clone_voice: settings.clone_voice,
          clone_consent: settings.clone_consent,
        });
        first ??= created;
      } catch (err) {
        failures.push(`${choice.info.title}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    setProgress(null);
    if (first) {
      if (failures.length > 0) window.alert(`${t("Some links were not added:")}\n${failures.join("\n")}`);
      onCreated(first);
    } else {
      setError(failures.join("\n"));
      setBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (source === "youtube") return submitYoutube();
    if (files.length === 0 || tooBig.length > 0) return;
    setBusy(true);
    setError(null);
    const failures: string[] = [];
    let first: Project | null = null;
    for (const [i, file] of files.entries()) {
      setProgress(files.length > 1 ? t("Uploading {i} of {n}: {name}", { i: i + 1, n: files.length, name: file.name }) : null);
      const form = new FormData();
      form.set("file", file);
      form.set("source_lang", settings.source_lang);
      form.set("voice", settings.voice);
      form.set("llm_model", settings.llm_model);
      form.set("asr_id", settings.asr_id);
      form.set("original_audio", settings.original_audio);
      form.set("keep_original_track", String(settings.keep_original_track));
      form.set("diarize", String(settings.diarize));
      form.set("clone_voice", String(settings.clone_voice));
      form.set("clone_consent", String(settings.clone_consent));
      if (settings.diarize && settings.num_speakers) form.set("num_speakers", String(settings.num_speakers));
      try {
        const created = await api.createProject(form);
        first ??= created;
      } catch (err) {
        failures.push(`${file.name}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    setProgress(null);
    if (first) {
      if (failures.length > 0) window.alert(`${t("Some files were not added:")}\n${failures.join("\n")}`);
      onCreated(first);
    } else {
      setError(failures.join("\n"));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card space-y-5">
      <div>
        <p className="eyebrow mb-1.5">{t("New dub")}</p>
        <h2 className="font-display text-[30px] font-semibold leading-tight">{t("Dub a video into Slovak")}</h2>
        <p className="mt-1 text-sm text-muted">{t("Three steps: choose the video, check the language and voice, press the button. Speech recognition, translation and the Slovak voice all run on this computer.")}</p>
      </div>
      <p className="eyebrow">{t("1 · The video")}</p>
      <div role="tablist" aria-label={t("Where is the video?")} className="seg">
        {(["file", "youtube"] as const).map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={source === k}
            disabled={busy}
            onClick={() => setSource(k)}
            className=""
          >
            {k === "file" ? t("Video file") : t("YouTube link")}
          </button>
        ))}
      </div>
      {source === "youtube" && <YoutubeSource onChoice={setYoutube} disabled={busy} />}
      <div
        hidden={source !== "file"}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length > 0) setFiles(Array.from(e.dataTransfer.files));
        }}
        className={`flex flex-col items-center gap-2 rounded-2xl border-2 border-dashed p-9 text-center transition-colors ${
          dragging ? "border-accent bg-accent-soft" : "border-line-strong bg-inset/50 hover:bg-inset"
        }`}
      >
        {files.length > 0 ? (
          <div className="text-sm">
            {files.length === 1 ? (
              <p>
                <strong>{files[0]?.name}</strong> · {((files[0]?.size ?? 0) / 1e6).toFixed(1)} MB
              </p>
            ) : (
              <>
                <p className="font-medium">{t("{n} videos — they are dubbed one after another", { n: files.length })}</p>
                <ul className="mt-1 max-h-28 overflow-auto text-xs text-muted">
                  {files.map((f) => (
                    <li key={f.name + f.size}>{f.name}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted">{t("Drop one or more MP4 files here, or")}</p>
        )}
        <button type="button" className="btn-secondary" onClick={() => input.current?.click()}>
          {files.length > 0 ? t("Choose other files") : t("Choose videos")}
        </button>
        <input ref={input} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => setFiles(Array.from(e.target.files ?? []))} aria-label={t("Video file")} />
        <UploadLimit options={options} onChanged={onOptionsChanged} />
        {tooBig.length > 0 && <p className="text-sm text-bad">{t("{names} is larger than {mb} MB.", { names: tooBig.map((f) => f.name).join(", "), mb: options.max_upload_mb })}</p>}
      </div>

      <p className="eyebrow">{t("2 · Language and voice")}</p>
      <OptionFields options={options} health={health} value={settings} onChange={setSettings} disabled={busy} onPackagesInstalled={onOptionsChanged} />
      <p className="eyebrow">{t("3 · Start")}</p>

      {error && (
        <p className="alert alert-bad" role="alert">
          {error}
        </p>
      )}
      <div className="flex items-center gap-3">
        <button type="submit" disabled={modelsMissing || (source === "file" ? files.length === 0 || tooBig.length > 0 : youtube.length === 0) || busy || (settings.clone_voice && !settings.clone_consent)} className="btn-primary">
          {source === "youtube"
            ? busy
              ? (progress ?? t("Starting…"))
              : youtube.length > 1
                ? t("Download and dub {n} videos", { n: youtube.length })
                : t("Download and start dubbing")
            : busy
              ? (progress ?? t("Uploading…"))
              : files.length > 1
                ? t("Upload and dub {n} videos", { n: files.length })
                : t("Upload and start dubbing")}
        </button>
        {modelsMissing && (
          <span className="text-xs text-warn">{t("Download the AI models first (see the notice above).")}</span>
        )}
        <span className="text-xs text-muted">
          {source === "youtube"
            ? t("The video is downloaded into this app's local data folder; dubbing happens on your computer.")
            : t("The video is copied into this app's local data folder and never leaves your computer.")}
        </span>
      </div>
    </form>
  );
}
