import { useRef, useState } from "react";
import { api, type Health, type Options, type Project } from "../api";
import { OptionFields, type Settings } from "./OptionFields";

interface Props {
  options: Options;
  health: Health | null;
  onCreated: (p: Project) => void;
}

const ACCEPT = ".mp4,.m4v,.mov,.mkv,video/mp4";

export function NewProject({ options, health, onCreated }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [settings, setSettings] = useState<Settings>({
    source_lang: "en",
    voice: options.default_voice,
    llm_model: options.default_llm,
    original_audio: "duck",
    keep_original_track: true,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const tooBig = file !== null && file.size > options.max_upload_mb * 1024 * 1024;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || tooBig) return;
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.set("file", file);
    form.set("source_lang", settings.source_lang);
    form.set("voice", settings.voice);
    form.set("llm_model", settings.llm_model);
    form.set("original_audio", settings.original_audio);
    form.set("keep_original_track", String(settings.keep_original_track));
    try {
      onCreated(await api.createProject(form));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5 rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
      <h2 className="text-lg font-semibold">New dub</h2>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files[0];
          if (f) setFile(f);
        }}
        className={`flex flex-col items-center gap-2 rounded-lg border-2 border-dashed p-8 text-center ${
          dragging ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950" : "border-slate-300 dark:border-slate-700"
        }`}
      >
        {file ? (
          <p className="text-sm">
            <strong>{file.name}</strong> · {(file.size / 1e6).toFixed(1)} MB
          </p>
        ) : (
          <p className="text-sm text-slate-500">Drop an MP4 here, or</p>
        )}
        <button type="button" className="rounded-md bg-slate-100 px-3 py-1.5 text-sm font-medium hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700" onClick={() => input.current?.click()}>
          {file ? "Choose another file" : "Choose a video"}
        </button>
        <input ref={input} type="file" accept={ACCEPT} className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label="Video file" />
        {tooBig && <p className="text-sm text-red-600">This file is larger than {options.max_upload_mb} MB.</p>}
      </div>

      <OptionFields options={options} health={health} value={settings} onChange={setSettings} disabled={busy} />

      {error && (
        <p className="rounded-md bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200" role="alert">
          {error}
        </p>
      )}
      <div className="flex items-center gap-3">
        <button type="submit" disabled={!file || tooBig || busy} className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          {busy ? "Uploading…" : "Upload and start dubbing"}
        </button>
        <span className="text-xs text-slate-500">The video is copied into this app's local data folder and never leaves your computer.</span>
      </div>
    </form>
  );
}
