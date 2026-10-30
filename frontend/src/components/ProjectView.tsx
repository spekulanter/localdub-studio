import { useCallback, useEffect, useRef, useState } from "react";
import { api, watchJob, type Health, type Job, type Options, type Project, type SegmentsResponse } from "../api";
import { formatTime, isActive, restartStage } from "../lib/format";
import { OptionFields, type Settings } from "./OptionFields";
import { ProgressPanel } from "./ProgressPanel";
import { useVideoClock } from "../lib/useVideoClock";
import { DialogueEditor } from "./DialogueEditor";
import { Timeline } from "./Timeline";

interface Props {
  projectId: number;
  options: Options;
  health: Health | null;
  onChanged: () => void;
  onDeleted: () => void;
  onOptionsChanged?: () => void;
}

const toSettings = (p: Project): Settings => ({
  source_lang: p.source_lang,
  voice: p.voice,
  llm_model: p.llm_model,
  original_audio: p.original_audio,
  keep_original_track: p.keep_original_track,
  diarize: p.diarize,
  clone_voice: p.clone_voice,
  clone_consent: p.clone_voice,
  num_speakers: p.num_speakers,
});

export function ProjectView({ projectId, options, health, onChanged, onDeleted, onOptionsChanged }: Props) {
  const [project, setProject] = useState<Project | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [segments, setSegments] = useState<SegmentsResponse | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [view, setView] = useState<"dub" | "original">("dub");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lastStage = useRef<string>("");
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const clock = useVideoClock(video);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const p = await api.project(projectId);
      setProject(p);
      setJob(p.latest_job);
      setDraft(toSettings(p));
      setSegments(await api.segments(projectId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Follow the active job; reload everything when it ends.
  const activeId = isActive(job) ? job?.id : undefined;
  useEffect(() => {
    if (activeId === undefined) return;
    return watchJob(
      activeId,
      (j) => {
        setJob(j);
        if (j.stage !== lastStage.current) {
          lastStage.current = j.stage;
          api.segments(projectId).then(setSegments).catch(() => undefined);
        }
        if (j.status !== "queued" && j.status !== "running") {
          void load();
          onChanged();
        }
      },
      () => setError("Lost the connection to the server. Reload the page."),
    );
  }, [activeId, projectId, load, onChanged]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!project || !draft) {
    return error ? <p className="text-red-600" role="alert">{error}</p> : <p className="text-slate-500">Loading…</p>;
  }

  const active = isActive(job);
  const stage = restartStage(toSettings(project), draft);
  const done = project.has_output;
  const editable = !active && !busy && segments !== null && segments.stage !== null && segments.stage !== "asr";

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold">{project.name}</h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {project.source_url ? (
              <>
                <a href={project.source_url} target="_blank" rel="noreferrer noopener" className="underline">
                  YouTube
                </a>
                {" · "}
              </>
            ) : (
              <>{project.original_name} · </>
            )}
            {formatTime(project.duration)}
          </p>
        </div>
        <button
          onClick={() => {
            if (window.confirm("Delete this project and all of its files?")) {
              void act(async () => {
                await api.deleteProject(projectId);
                onDeleted();
              });
            }
          }}
          disabled={busy}
          className="rounded-md border border-red-300 px-3 py-1 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950"
        >
          Delete
        </button>
      </header>

      {error && (
        <p className="rounded-md bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950 dark:text-red-200" role="alert">
          {error}
        </p>
      )}

      {job ? (
        <ProgressPanel
          job={job}
          hasDownload={project.source_url !== null}
          busy={busy}
          onCancel={() => void act(() => api.cancelJob(job.id))}
          onRetry={() => void act(() => api.startJob(projectId))}
        />
      ) : (
        <button onClick={() => void act(() => api.startJob(projectId))} disabled={busy} className="rounded-md bg-indigo-600 px-4 py-2 text-sm text-white disabled:opacity-50">
          Start dubbing
        </button>
      )}

      <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="font-medium">Preview</h3>
          {done && (
            <div className="flex overflow-hidden rounded-md border border-slate-300 text-sm dark:border-slate-700" role="group" aria-label="Preview version">
              {(["dub", "original"] as const).map((v) => (
                <button key={v} onClick={() => setView(v)} aria-pressed={view === v} className={`px-3 py-1 ${view === v ? "bg-indigo-600 text-white" : ""}`}>
                  {v === "dub" ? "Slovak dub" : "Original"}
                </button>
              ))}
            </div>
          )}
        </div>
        {project.has_input || done ? (
          /* key forces a fresh element when the source changes */
          <video
            ref={setVideo}
            key={`${view}-${done}-${job?.finished_at ?? 0}-${project.has_input}`}
            controls
            preload="metadata"
            className="max-h-[28rem] w-full rounded-md bg-black"
            src={done && view === "dub" ? `${api.fileUrl(projectId, "video", true)}&t=${job?.finished_at ?? 0}` : api.sourceUrl(projectId)}
          />
        ) : (
          <div className="flex h-40 items-center justify-center rounded-md bg-slate-100 text-sm text-slate-500 dark:bg-slate-800 dark:text-slate-400" role="status">
            {active ? "The video is being downloaded from YouTube…" : "The video was not downloaded. Use Retry above to try again."}
          </div>
        )}
        {done && (
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            The dub is the first audio track. {project.keep_original_track ? "The original is the second track (switch tracks in a desktop player such as VLC)." : "The original audio track was not kept."}
          </p>
        )}
        {done && (
          <div className="mt-3 flex flex-wrap gap-2 text-sm">
            <a className="rounded-md bg-emerald-600 px-3 py-1.5 font-medium text-white" href={api.fileUrl(projectId, "video")}>
              Download MP4
            </a>
            <a className="rounded-md border border-slate-300 px-3 py-1.5 dark:border-slate-700" href={api.fileUrl(projectId, "srt")}>
              Slovak subtitles (.srt)
            </a>
            <a className="rounded-md border border-slate-300 px-3 py-1.5 dark:border-slate-700" href={api.fileUrl(projectId, "srt_en")}>
              English subtitles (.srt)
            </a>
          </div>
        )}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h3 className="mb-3 font-medium">Settings</h3>
        <OptionFields options={options} health={health} value={draft} onChange={setDraft} lockSource disabled={active || busy} onPackagesInstalled={onOptionsChanged} />
        {stage && !active && !(draft.clone_voice && !draft.clone_consent) && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  await api.patchProject(projectId, {
                    voice: draft.voice,
                    llm_model: draft.llm_model,
                    original_audio: draft.original_audio,
                    keep_original_track: draft.keep_original_track,
                    diarize: draft.diarize,
                    clone_voice: draft.clone_voice,
                    clone_consent: draft.clone_consent,
                    num_speakers: draft.num_speakers,
                  });
                  await api.startJob(projectId, stage);
                })
              }
              className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              Apply and re-render
            </button>
            <span className="text-xs text-slate-500">
              Re-runs from “{stage}” — earlier steps are reused.
            </span>
          </div>
        )}
      </section>

      {segments !== null && segments.segments.length > 0 && (
        <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h3 className="mb-3 font-medium">Timeline</h3>
          <Timeline
            projectId={projectId}
            segments={segments.segments}
            duration={project.duration}
            editable={editable}
            selectedId={selectedId}
            onSelect={setSelectedId}
            currentTime={clock.time}
            playing={clock.playing}
            onSeek={(t) => {
              if (video) video.currentTime = t;
            }}
            onTimingChange={async (id, start, end) => {
              await api.patchSegment(projectId, id, { start, end });
              setSegments(await api.segments(projectId));
            }}
            renderVersion={job?.finished_at ?? 0}
          />
        </section>
      )}

      <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h3 className="mb-3 font-medium">Dialogue</h3>
        <DialogueEditor
          projectId={projectId}
          data={segments}
          options={options}
          editable={editable}
          selectedId={selectedId}
          onSelect={setSelectedId}
          renderVersion={job?.finished_at ?? 0}
          onChange={() => void api.segments(projectId).then(setSegments)}
          onRerender={() => void act(() => api.startJob(projectId, "tts"))}
          busy={busy}
        />
      </section>
    </div>
  );
}
