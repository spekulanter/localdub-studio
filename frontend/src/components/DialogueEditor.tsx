import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Options, type SegmentRow, type SegmentsResponse } from "../api";
import { useT } from "../i18n";
import { formatTime } from "../lib/format";

const FIT: Record<string, { label: string; cls: string; hint: string }> = {
  ok: { label: "fits", cls: "bg-ok-soft text-ok", hint: "Fits its time slot." },
  stretched: { label: "sped up", cls: "bg-dub-soft text-dub", hint: "Spoken slightly faster to fit." },
  shifted: { label: "shifted", cls: "bg-warn-soft text-warn", hint: "Starts a little late so lines do not overlap." },
  overflow: { label: "too long", cls: "bg-bad-soft text-bad", hint: "Too long for the slot even at top speed; shorten the text or widen the timing." },
};

const input = "field";

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
  const t = useT();
  const play = useSinglePlayer();
  const speakers = useMemo(() => Array.from(new Set(data?.segments.map((s) => s.speaker_id) ?? [])), [data]);
  const [error, setError] = useState<string | null>(null);

  if (!data || data.segments.length === 0) {
    return <p className="text-sm text-muted">{t("Dialogue appears here once speech has been recognised.")}</p>;
  }
  const tight = data.segments.filter((s) => s.fit_status === "overflow" || s.fit_status === "shifted").length;
  const edited = data.segments.filter((s) => s.edited).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted">
          {t("{n} lines", { n: data.segments.length })}
          {tight > 0 && ` · ${t("{n} where timing is tight", { n: tight })}`}
          {edited > 0 && ` · ${t("{n} edited by you", { n: edited })}`}
        </p>
        {editable && data.edits_pending && (
          <button onClick={onRerender} disabled={busy} className="btn-primary">
            {t("Re-render changed lines")}
          </button>
        )}
      </div>
      {!editable && data.stage !== null && (
        <p className="text-xs text-muted">{t("Editing unlocks when the translation has finished and no job is running.")}</p>
      )}
      {error && (
        <p className="alert alert-bad" role="alert">
          {error}
        </p>
      )}
      {speakers.length > 1 && editable && (
        <fieldset className="rounded-md border border-line p-3">
          <legend className="px-1 text-sm font-medium">{t("Voice per speaker")}</legend>
          <div className="flex flex-wrap gap-3">
            {speakers.map((sp) => (
              <label key={sp} className="text-sm">
                <span className="mr-2">{sp}</span>
                <select
                  className={`${input} w-auto`}
                  value={data.speaker_voices[sp] ?? ""}
                  onChange={(e) => {
                    const next = { ...data.speaker_voices };
                    if (e.target.value) next[sp] = e.target.value;
                    else delete next[sp];
                    api.setSpeakerVoices(projectId, next).then(onChange).catch((err: unknown) => setError(String(err)));
                  }}
                >
                  <option value="">{t("auto")} ({data.speaker_defaults[sp] ?? t("project voice")})</option>
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
  const t = useT();
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
      setHint(p.duration > p.window + 0.02 ? t("Too long: {a} s for a {b} s slot", { a: p.duration.toFixed(1), b: p.window.toFixed(1) }) : t("Fits: {a} s in {b} s", { a: p.duration.toFixed(1), b: p.window.toFixed(1) }));
      play(p.url);
    });

  return (
    <li
      ref={item}
      onClick={() => onSelect?.(seg.id)}
      className={`rounded-md border p-3 ${seg.stale_edit ? "border-warn" : "border-line"} ${selected ? "ring-2 ring-accent" : ""}`}
    >
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted">
        <span className="tabular-nums">
          {formatTime(seg.start)}–{formatTime(seg.end)}
        </span>
        {multiSpeaker && <span className="rounded bg-inset px-1.5">{seg.speaker_id}</span>}
        {fit && (
          <span title={t(fit.hint)} className={`rounded px-1.5 py-0.5 ${fit.cls}`}>
            {t(fit.label)}
          </span>
        )}
        {seg.edited && <span className="chip chip-accent">{t("edited")}</span>}
        {seg.review_status === "approved" && <span className="text-ok">{t("✓ approved")}</span>}
        {seg.stale_edit && <span className="text-warn">{t("the recognised English changed; your edit was ignored")}</span>}
      </div>
      <p className="mb-2 text-sm text-muted">{seg.source_text}</p>
      <textarea
        aria-label={t("Slovak text for line {n}", { n: seg.id })}
        className={`${input} w-full`}
        rows={Math.max(2, Math.ceil(text.length / 90))}
        value={text}
        disabled={!editable || working}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select aria-label={t("Voice for line {n}", { n: seg.id })} className={`${input} w-auto`} value={voice} disabled={!editable || working} onChange={(e) => setVoice(e.target.value)}>
          <option value="">{seg.effective_voice ? t("default ({voice})", { voice: seg.effective_voice }) : t("default voice")}</option>
          {options.voices.map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
        <button type="button" onClick={() => void preview()} disabled={working || !text.trim()} className="btn-secondary btn-sm">
          {t("▶ Try this text")}
        </button>
        {seg.has_audio && !dirty && (
          <button type="button" onClick={() => play(api.segmentAudioUrl(projectId, seg.id, renderVersion))} className="btn-secondary btn-sm">
            {t("▶ Rendered")}
          </button>
        )}
        <button type="button" onClick={() => setShowTiming((v) => !v)} className="text-sm underline" aria-expanded={showTiming}>
          {t("Timing")}
        </button>
        {editable && (
          <label className="flex items-center gap-1 text-sm">
            <input
              type="checkbox"
              checked={seg.review_status === "approved"}
              onChange={(e) => void run(async () => { await api.patchSegment(projectId, seg.id, { review_status: e.target.checked ? "approved" : null }); onChange(); })}
            />
            {t("approved")}
          </label>
        )}
        <span className="ml-auto flex gap-2">
          {seg.edited && editable && (
            <button type="button" disabled={working} onClick={() => void run(async () => { await api.revertSegment(projectId, seg.id); onChange(); })} className="btn-secondary btn-sm">
              {t("Revert")}
            </button>
          )}
          <button type="button" onClick={() => void save()} disabled={!dirty || !editable || working} className="btn-primary btn-sm">
            {t("Save")}
          </button>
        </span>
      </div>
      {showTiming && (
        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
          <label>
            {t("Start (s)")} <input className={`${input} w-24`} type="number" step="0.05" min="0" value={start} disabled={!editable} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label>
            {t("End (s)")} <input className={`${input} w-24`} type="number" step="0.05" min="0" value={end} disabled={!editable} onChange={(e) => setEnd(e.target.value)} />
          </label>
          <span className="text-xs text-muted">{t("Moves when this line is spoken. Lines cannot overlap their neighbours.")}</span>
        </div>
      )}
      {hint && <p className="mt-1 text-xs text-muted" role="status">{hint}</p>}
    </li>
  );
}
