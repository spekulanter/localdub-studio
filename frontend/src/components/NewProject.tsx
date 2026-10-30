import { useRef, useState } from "react";
import { api, type Health, type Options, type Project, type YoutubeChoice } from "../api";
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

const ACCEPT = ".mp4,.m4v,.mov,.mkv,video/mp4";

export function NewProject({ options, health, onCreated, modelsMissing = false, onOptionsChanged }: Props) {
  const [source, setSource] = useState<"file" | "youtube">("file");
  const [youtube, setYoutube] = useState<YoutubeChoice | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<string | null>(null);
  const [settings, setSettings] = useState<Settings>({
    source_lang: "en",
    voice: options.default_voice,
    llm_model: options.default_llm,
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
    if (!youtube) return;
    setBusy(true);
    setError(null);
    try {
      onCreated(
        await api.createFromYoutube({
          url: youtube.url,
          quality: youtube.quality,
          cookies_browser: youtube.cookies_browser,
          source_lang: settings.source_lang,
          voice: settings.voice,
          llm_model: settings.llm_model,
          original_audio: settings.original_audio,
          keep_original_track: settings.keep_original_track,
          diarize: settings.diarize,
          num_speakers: settings.diarize ? settings.num_speakers : null,
          clone_voice: settings.clone_voice,
          clone_consent: settings.clone_consent,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
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
      setProgress(files.length > 1 ? `Uploading ${i + 1} of ${files.length}: ${file.name}` : null);
      const form = new FormData();
      form.set("file", file);
      form.set("source_lang", settings.source_lang);
      form.set("voice", settings.voice);
      form.set("llm_model", settings.llm_model);
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
      if (failures.length > 0) window.alert(`Some files were not added:\n${failures.join("\n")}`);
      onCreated(first);
    } else {
      setError(failures.join("\n"));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5 rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
      <h2 className="text-lg font-semibold">New dub</h2>
      <div role="tablist" aria-label="Where is the video?" className="inline-flex overflow-hidden rounded-md border border-slate-300 text-sm dark:border-slate-700">
        {(["file", "youtube"] as const).map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={source === k}
            disabled={busy}
            onClick={() => setSource(k)}
            className={`px-4 py-1.5 ${source === k ? "bg-indigo-600 text-white" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}
          >
            {k === "file" ? "Video file" : "YouTube link"}
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
        className={`flex flex-col items-center gap-2 rounded-lg border-2 border-dashed p-8 text-center ${
          dragging ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950" : "border-slate-300 dark:border-slate-700"
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
                <p className="font-medium">{files.length} videos — they are dubbed one after another</p>
                <ul className="mt-1 max-h-28 overflow-auto text-xs text-slate-500">
                  {files.map((f) => (
                    <li key={f.name + f.size}>{f.name}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        ) : (
          <p className="text-sm text-slate-500">Drop one or more MP4 files here, or</p>
        )}
        <button type="button" className="rounded-md bg-slate-100 px-3 py-1.5 text-sm font-medium hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700" onClick={() => input.current?.click()}>
          {files.length > 0 ? "Choose other files" : "Choose videos"}
        </button>
        <input ref={input} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => setFiles(Array.from(e.target.files ?? []))} aria-label="Video file" />
        {tooBig.length > 0 && <p className="text-sm text-red-600">{tooBig.map((f) => f.name).join(", ")} is larger than {options.max_upload_mb} MB.</p>}
      </div>

      <OptionFields options={options} health={health} value={settings} onChange={setSettings} disabled={busy} onPackagesInstalled={onOptionsChanged} />

      {error && (
        <p className="rounded-md bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200" role="alert">
          {error}
        </p>
      )}
      <div className="flex items-center gap-3">
        <button type="submit" disabled={modelsMissing || (source === "file" ? files.length === 0 || tooBig.length > 0 : youtube === null) || busy || (settings.clone_voice && !settings.clone_consent)} className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          {source === "youtube"
            ? busy
              ? "Starting…"
              : "Download and start dubbing"
            : busy
              ? (progress ?? "Uploading…")
              : files.length > 1
                ? `Upload and dub ${files.length} videos`
                : "Upload and start dubbing"}
        </button>
        {modelsMissing && (
          <span className="text-xs text-amber-700 dark:text-amber-300">Download the AI models first (see the notice above).</span>
        )}
        <span className="text-xs text-slate-500">
          {source === "youtube"
            ? "The video is downloaded into this app's local data folder; dubbing happens on your computer."
            : "The video is copied into this app's local data folder and never leaves your computer."}
        </span>
      </div>
    </form>
  );
}
