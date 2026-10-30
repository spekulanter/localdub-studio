import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Options, type SegmentRow, type SegmentsResponse } from "../api";
import { formatTime } from "../lib/format";

const FIT: Record<string, { label: string; cls: string; hint: string }> = {
  ok: { label: "fits", cls: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200", hint: "Fits its time slot." },
  stretched: { label: "sped up", cls: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-200", hint: "Spoken slightly faster to fit." },
  shifted: { label: "shifted", cls: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200", hint: "Starts a little late so lines do not overlap." },
  overflow: { label: "too long", cls: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200", hint: "Too long for the slot even at top speed; shorten the text or widen the timing." },
};

const input = "rounded-md border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900";

interface Props {
  projectId: number;
  data: SegmentsResponse | null;
  options: Options;
  /** Editing is only possible when no job runs and translation exists. */
  editable: boolean;
  /** The line highlighted in the timeline (and the other way round). */
  selectedId?: number | null;
  onSelect?: (id: number) => void;
  renderVersion: number;
  onChange: () => void;
  onRerender: () => void;
  busy: boolean;
}

/** Plays one clip at a time across all rows. */
function useSinglePlayer() {
  const audio = useRef<HTMLAudioElement | null>(null);
  const blob = useRef<string | null>(null); // object URL of the last "Try this text" clip
  useEffect(
    () => () => {
      audio.current?.pause(); // leaving the page must not leave a voice talking
      if (blob.current) URL.revokeObjectURL(blob.current);
    },
    [],
  );
  return (url: string) => {
    audio.current?.pause();
    if (blob.current && blob.current !== url) URL.revokeObjectURL(blob.current);
    blob.current = url.startsWith("blob:") ? url : null;
    audio.current = new Audio(url);
    void audio.current.play();
  };
}

export function DialogueEditor({ projectId, data, options, editable, selectedId = null, onSelect, renderVersion, onChange, onRerender, busy }: Props) {
  const play = useSinglePlayer();
  const speakers = useMemo(() => Array.from(new Set(data?.segments.map((s) => s.speaker_id) ?? [])), [data]);
  const [error, setError] = useState<string | null>(null);

  if (!data || data.segments.length === 0) {
    return <p className="text-sm text-slate-500">Dialogue appears here once speech has been recognised.</p>;
  }
  const tight = data.segments.filter((s) => s.fit_status === "overflow" || s.fit_status === "shifted").length;
  const edited = data.segments.filter((s) => s.edited).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {data.segments.length} lines{tight > 0 && ` · ${tight} where timing is tight`}
          {edited > 0 && ` · ${edited} edited by you`}
        </p>
        {editable && data.edits_pending && (
          <button onClick={onRerender} disabled={busy} className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
            Re-render changed lines
          </button>
        )}
      </div>
      {!editable && data.stage !== null && (
        <p className="text-xs text-slate-500">Editing unlocks when the translation has finished and no job is running.</p>
      )}
      {error && (
        <p className="rounded-md bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200" role="alert">
          {error}
        </p>
      )}
      {speakers.length > 1 && editable && (
        <fieldset className="rounded-md border border-slate-200 p-3 dark:border-slate-800">
          <legend className="px-1 text-sm font-medium">Voice per speaker</legend>
          <div className="flex flex-wrap gap-3">
            {speakers.map((sp) => (
              <label key={sp} className="text-sm">
                <span className="mr-2">{sp}</span>
                <select
                  className={input}
                  value={data.speaker_voices[sp] ?? ""}
                  onChange={(e) => {
                    const next = { ...data.speaker_voices };
                    if (e.target.value) next[sp] = e.target.value;
                    else delete next[sp];
                    api.setSpeakerVoices(projectId, next).then(onChange).catch((err: unknown) => setError(String(err)));
                  }}
                >
                  <option value="">auto ({data.speaker_defaults[sp] ?? "project voice"})</option>
                  {options.voices.map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <ul className="max-h-[40rem] space-y-2 overflow-auto pr-1">
        {data.segments.map((s) => (
          <Row key={`${s.id}-${s.translated_text}-${s.voice_id}-${s.start}-${s.end}`} seg={s} projectId={projectId} options={options} editable={editable} renderVersion={renderVersion} play={play} onChange={onChange} onError={setError} multiSpeaker={speakers.length > 1} selected={s.id === selectedId} onSelect={onSelect} />
        ))}
      </ul>
    </div>
  );
}

interface RowProps {
  seg: SegmentRow;
  projectId: number;
  options: Options;
  editable: boolean;
  renderVersion: number;
  play: (url: string) => void;
  onChange: () => void;
  onError: (msg: string | null) => void;
  multiSpeaker: boolean;
  selected: boolean;
  onSelect?: (id: number) => void;
}

function Row({ seg, projectId, options, editable, renderVersion, play, onChange, onError, multiSpeaker, selected, onSelect }: RowProps) {
  const item = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (selected) item.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [selected]);
  const [text, setText] = useState(seg.translated_text);
  const [voice, setVoice] = useState(seg.voice_id ?? "");
  const [start, setStart] = useState(String(seg.start));
  const [end, setEnd] = useState(String(seg.end));
  const [hint, setHint] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [showTiming, setShowTiming] = useState(false);

  const dirty = text !== seg.translated_text || voice !== (seg.voice_id ?? "") || Number(start) !== seg.start || Number(end) !== seg.end;
  const fit = seg.fit_status ? FIT[seg.fit_status] : undefined;

  async function run(fn: () => Promise<void>) {
    setWorking(true);
    onError(null);
    try {
      await fn();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setWorking(false);
    }
  }

  const save = () =>
    run(async () => {
      await api.patchSegment(projectId, seg.id, {
        translated_text: text,
        voice_id: voice || null,
        start: Number(start),
        end: Number(end),
      });
      onChange();
    });

  const preview = () =>
    run(async () => {
      const p = await api.previewSegment(projectId, seg.id, { text, voice: voice || undefined });
      setHint(p.duration > p.window + 0.02 ? `Too long: ${p.duration.toFixed(1)} s for a ${p.window.toFixed(1)} s slot` : `Fits: ${p.duration.toFixed(1)} s in ${p.window.toFixed(1)} s`);
      play(p.url);
    });

  return (
    <li
      ref={item}
      onClick={() => onSelect?.(seg.id)}
      className={`rounded-md border p-3 ${seg.stale_edit ? "border-amber-400" : "border-slate-200 dark:border-slate-800"} ${selected ? "ring-2 ring-indigo-500" : ""}`}
    >
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="tabular-nums">
          {formatTime(seg.start)}–{formatTime(seg.end)}
        </span>
        {multiSpeaker && <span className="rounded bg-slate-100 px-1.5 dark:bg-slate-800">{seg.speaker_id}</span>}
        {fit && (
          <span title={fit.hint} className={`rounded px-1.5 py-0.5 ${fit.cls}`}>
            {fit.label}
          </span>
        )}
        {seg.edited && <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200">edited</span>}
        {seg.review_status === "approved" && <span className="text-emerald-600">✓ approved</span>}
        {seg.stale_edit && <span className="text-amber-600">the recognised English changed; your edit was ignored</span>}
      </div>
      <p className="mb-2 text-sm text-slate-600 dark:text-slate-300">{seg.source_text}</p>
      <textarea
        aria-label={`Slovak text for line ${seg.id}`}
        className={`${input} w-full`}
        rows={Math.max(2, Math.ceil(text.length / 90))}
        value={text}
        disabled={!editable || working}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select aria-label={`Voice for line ${seg.id}`} className={input} value={voice} disabled={!editable || working} onChange={(e) => setVoice(e.target.value)}>
          <option value="">{seg.effective_voice ? `default (${seg.effective_voice})` : "default voice"}</option>
          {options.voices.map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        <button type="button" onClick={() => void preview()} disabled={working || !text.trim()} className="rounded-md border border-slate-300 px-2 py-1 text-sm disabled:opacity-50 dark:border-slate-700">
          ▶ Try this text
        </button>
        {seg.has_audio && !dirty && (
          <button type="button" onClick={() => play(api.segmentAudioUrl(projectId, seg.id, renderVersion))} className="rounded-md border border-slate-300 px-2 py-1 text-sm dark:border-slate-700">
            ▶ Rendered
          </button>
        )}
        <button type="button" onClick={() => setShowTiming((v) => !v)} className="text-sm underline" aria-expanded={showTiming}>
          Timing
        </button>
        {editable && (
          <label className="flex items-center gap-1 text-sm">
            <input
              type="checkbox"
              checked={seg.review_status === "approved"}
              onChange={(e) => void run(async () => { await api.patchSegment(projectId, seg.id, { review_status: e.target.checked ? "approved" : null }); onChange(); })}
            />
            approved
          </label>
        )}
        <span className="ml-auto flex gap-2">
          {seg.edited && editable && (
            <button type="button" disabled={working} onClick={() => void run(async () => { await api.revertSegment(projectId, seg.id); onChange(); })} className="rounded-md border border-slate-300 px-2 py-1 text-sm dark:border-slate-700">
              Revert
            </button>
          )}
          <button type="button" onClick={() => void save()} disabled={!dirty || !editable || working} className="rounded-md bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-40">
            Save
          </button>
        </span>
      </div>
      {showTiming && (
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
          <label>
            Start (s) <input className={`${input} w-24`} type="number" step="0.05" min="0" value={start} disabled={!editable} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label>
            End (s) <input className={`${input} w-24`} type="number" step="0.05" min="0" value={end} disabled={!editable} onChange={(e) => setEnd(e.target.value)} />
          </label>
          <span className="text-xs text-slate-500">Moves when this line is spoken. Lines cannot overlap their neighbours.</span>
        </div>
      )}
      {hint && <p className="mt-1 text-xs text-slate-500" role="status">{hint}</p>}
    </li>
  );
}
