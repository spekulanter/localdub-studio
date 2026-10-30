import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { SegmentRow } from "../api";
import {
  boundsFor,
  clampZoom,
  decodePeaks,
  fitZoom,
  formatSpan,
  formatTick,
  moveSpan,
  peakAt,
  resizeSpan,
  round2,
  snapTime,
  tickStep,
} from "../lib/timeline";

const GUTTER = 92; // px for the lane labels
const H_RULER = 24;
const H_WAVE = 76;
const H_EN = 44;
const H_SK = 36;
const HANDLE = 7;
const SNAP_PX = 8;

interface Props {
  projectId: number;
  segments: SegmentRow[];
  duration: number;
  /** Editing is only possible when no job runs and the translation exists. */
  editable: boolean;
  selectedId: number | null;
  onSelect: (id: number | null) => void;
  currentTime: number;
  playing: boolean;
  onSeek: (t: number) => void;
  /** Persist new timing; rejects with the server's message when it is refused. */
  onTimingChange: (id: number, start: number, end: number) => Promise<void>;
  /** Changes whenever the audio was rendered again, so the waveform is fetched again. */
  renderVersion?: number;
}

interface Drag {
  id: number;
  mode: "move" | "start" | "end";
  originX: number;
  start: number;
  end: number;
  moved: boolean;
}

const STATUS_BORDER: Record<string, string> = {
  ok: "border-emerald-500/70",
  stretched: "border-sky-500/70",
  shifted: "border-amber-500/80",
  overflow: "border-red-500/80",
};

export function Timeline({
  projectId,
  segments,
  duration,
  editable,
  selectedId,
  onSelect,
  currentTime,
  playing,
  onSeek,
  onTimingChange,
  renderVersion = 0,
}: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [viewWidth, setViewWidth] = useState(800);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [pps, setPps] = useState(0); // 0 = not decided yet: fit once the width is known
  const [snap, setSnap] = useState(true);
  const [peaks, setPeaks] = useState<{ data: Uint8Array; bps: number } | null>(null);
  const [waveState, setWaveState] = useState<"loading" | "ready" | "missing">("loading");
  const [drag, setDrag] = useState<Drag | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Readable by default (at least 32 px per second, the view scrolls); "Fit" shows the whole video.
  const zoom = pps || Math.max(fitZoom(duration, viewWidth), 32);
  const width = Math.max(duration * zoom, viewWidth);

  // ---- measure the visible area -----------------------------------------------------------
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => setViewWidth(el.clientWidth || 800);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ---- waveform ----------------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setWaveState("loading");
    fetch(`/api/projects/${projectId}/waveform?kind=original&v=${renderVersion}`)
      .then((r) => r.json() as Promise<{ available: boolean; peaks?: string; bins_per_second?: number }>)
      .then((w) => {
        if (cancelled) return;
        if (w.available && w.peaks && w.bins_per_second) {
          setPeaks({ data: decodePeaks(w.peaks), bps: w.bins_per_second });
          setWaveState("ready");
        } else {
          setPeaks(null);
          setWaveState("missing");
        }
      })
      .catch(() => {
        if (!cancelled) setWaveState("missing");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, renderVersion]);

  const drawWave = useCallback(() => {
    const c = canvas.current;
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.floor(viewWidth * dpr);
    c.height = Math.floor(H_WAVE * dpr);
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, viewWidth, H_WAVE);
    const mid = H_WAVE / 2;
    const style = getComputedStyle(c);
    ctx.fillStyle = style.color || "#64748b";
    if (!peaks) {
      ctx.fillRect(0, mid - 0.5, viewWidth, 1);
      return;
    }
    for (let x = 0; x < viewWidth; x++) {
      const t0 = (scrollLeft + x) / zoom;
      const p = peakAt(peaks.data, peaks.bps, t0, t0 + 1 / zoom) / 255;
      const h = Math.max(1, p * (H_WAVE - 6));
      ctx.fillRect(x, mid - h / 2, 1, h);
    }
  }, [peaks, scrollLeft, viewWidth, zoom]);

  useEffect(() => {
    const id = requestAnimationFrame(drawWave);
    return () => cancelAnimationFrame(id);
  }, [drawWave]);

  // ---- keep the playhead and the selection visible ----------------------------------------
  useEffect(() => {
    const el = scroller.current;
    if (!el || !playing) return;
    const x = currentTime * zoom;
    if (x < el.scrollLeft || x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = Math.max(0, x - el.clientWidth * 0.2);
  }, [currentTime, playing, zoom]);

  useEffect(() => {
    const el = scroller.current;
    const seg = segments.find((s) => s.id === selectedId);
    if (!el || !seg) return;
    const x0 = seg.start * zoom;
    const x1 = seg.end * zoom;
    if (x1 < el.scrollLeft || x0 > el.scrollLeft + el.clientWidth) el.scrollLeft = Math.max(0, x0 - el.clientWidth * 0.3);
    // only when the selection changes, not on every zoom or scroll
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  // ---- dragging ----------------------------------------------------------------------------
  const spans = useMemo(() => segments.map((s) => ({ id: s.id, start: s.start, end: s.end })), [segments]);

  const snapTargets = useCallback(
    (excludeId: number) => [
      0,
      duration,
      currentTime,
      ...segments.filter((s) => s.id !== excludeId).flatMap((s) => [s.start, s.end]),
    ],
    [segments, duration, currentTime],
  );

  const compute = useCallback(
    (d: Drag, clientX: number): { start: number; end: number } => {
      const seg = spans.find((s) => s.id === d.id);
      if (!seg) return { start: d.start, end: d.end };
      const b = boundsFor(spans, d.id, duration);
      const delta = (clientX - d.originX) / zoom;
      const tol = SNAP_PX / zoom;
      const targets = snap ? snapTargets(d.id) : [];
      if (d.mode === "move") {
        let m = moveSpan(seg, delta, b);
        // snap whichever edge is closer to a target
        const ds = snapTime(m.start, targets, tol) - m.start;
        const de = snapTime(m.end, targets, tol) - m.end;
        const shift = Math.abs(ds) <= Math.abs(de) && ds !== 0 ? ds : de;
        if (shift !== 0) m = moveSpan(seg, delta + shift, b);
        return m;
      }
      const raw = (d.mode === "start" ? seg.start : seg.end) + delta;
      return resizeSpan(seg, d.mode, snapTime(raw, targets, tol), b);
    },
    [spans, duration, zoom, snap, snapTargets],
  );

  const onPointerDown = (e: React.PointerEvent, seg: SegmentRow, mode: Drag["mode"]) => {
    if (e.button !== 0) return;
    onSelect(seg.id);
    if (!editable || busy) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setError(null);
    setDrag({ id: seg.id, mode, originX: e.clientX, start: seg.start, end: seg.end, moved: false });
    e.stopPropagation();
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag) return;
    const next = compute(drag, e.clientX);
    const moved = drag.moved || Math.abs(e.clientX - drag.originX) > 3;
    setDrag({ ...drag, ...next, moved });
  };

  const commit = useCallback(
    async (id: number, start: number, end: number) => {
      setBusy(true);
      try {
        await onTimingChange(id, round2(start), round2(end));
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [onTimingChange],
  );

  const onPointerUp = (e: React.PointerEvent) => {
    if (!drag) return;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    const d = drag;
    setDrag(null);
    const seg = segments.find((s) => s.id === d.id);
    if (!d.moved) {
      if (seg) onSeek(seg.start);
      return;
    }
    if (seg && (seg.start !== d.start || seg.end !== d.end)) void commit(d.id, d.start, d.end);
  };

  const onKeyDown = (e: React.KeyboardEvent, seg: SegmentRow) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(seg.id);
      onSeek(seg.start);
      return;
    }
    if (!editable || busy || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    e.preventDefault();
    const step = (e.shiftKey ? 0.5 : 0.05) * (e.key === "ArrowLeft" ? -1 : 1);
    const m = moveSpan(seg, step, boundsFor(spans, seg.id, duration));
    if (m.start !== seg.start) void commit(seg.id, m.start, m.end);
  };

  // ---- zoom --------------------------------------------------------------------------------
  const zoomTo = useCallback(
    (next: number, anchorPx?: number) => {
      const el = scroller.current;
      const target = clampZoom(next);
      if (el) {
        const anchor = anchorPx ?? el.clientWidth / 2;
        const timeAtAnchor = (el.scrollLeft + anchor) / zoom;
        requestAnimationFrame(() => {
          el.scrollLeft = Math.max(0, timeAtAnchor * target - anchor);
        });
      }
      setPps(target);
    },
    [zoom],
  );

  const onWheel = (e: React.WheelEvent) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    const rect = scroller.current?.getBoundingClientRect();
    zoomTo(zoom * (e.deltaY < 0 ? 1.2 : 1 / 1.2), rect ? e.clientX - rect.left : undefined);
  };

  const seekFromClick = (e: React.MouseEvent) => {
    const el = scroller.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    onSeek(Math.min(Math.max((e.clientX - rect.left + el.scrollLeft) / zoom, 0), duration));
  };

  // ---- ticks -------------------------------------------------------------------------------
  const step = tickStep(zoom);
  const ticks: number[] = [];
  const first = Math.floor(scrollLeft / zoom / step) * step;
  for (let t = Math.max(0, first); t <= Math.min(duration, (scrollLeft + viewWidth) / zoom + step); t += step) ticks.push(round2(t));

  const active = (s: SegmentRow) => (drag && drag.id === s.id ? { ...s, start: drag.start, end: drag.end } : s);
  const dragging = drag?.moved ? segments.find((s) => s.id === drag.id) : undefined;

  return (
    <div className="space-y-2" data-testid="timeline">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <button type="button" aria-label="Zoom out" onClick={() => zoomTo(zoom / 1.5)} className="tl-btn">
          −
        </button>
        <button type="button" aria-label="Zoom in" onClick={() => zoomTo(zoom * 1.5)} className="tl-btn">
          +
        </button>
        <button type="button" onClick={() => zoomTo(fitZoom(duration, viewWidth))} className="tl-btn">
          Fit
        </button>
        <label className="ml-2 flex items-center gap-1.5">
          <input type="checkbox" checked={snap} onChange={(e) => setSnap(e.target.checked)} />
          Snap to neighbours and playhead
        </label>
        <span className="ml-auto text-xs text-slate-500 dark:text-slate-400">
          {editable ? "Drag a block to move it, drag its edges to resize. Ctrl + wheel zooms." : "Editing unlocks when no job is running."}
        </span>
      </div>

      {error && (
        <p className="rounded-md bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200" role="alert">
          {error}
        </p>
      )}

      <div className="flex overflow-hidden rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950">
        <div className="shrink-0 border-r border-slate-200 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400" style={{ width: GUTTER }}>
          <div style={{ height: H_RULER }} />
          <div className="flex items-center px-2" style={{ height: H_WAVE }}>
            Original audio
          </div>
          <div className="flex items-center px-2" style={{ height: H_EN }}>
            English lines
          </div>
          <div className="flex items-center px-2" style={{ height: H_SK }}>
            Slovak dub
          </div>
        </div>

        <div
          ref={scroller}
          tabIndex={0}
          role="region"
          aria-label="Timeline: scroll with the arrow keys, Tab moves between lines"
          className="relative min-w-0 flex-1 overflow-x-auto"
          onScroll={(e) => setScrollLeft(e.currentTarget.scrollLeft)}
          onWheel={onWheel}
        >
          <div className="relative" style={{ width, height: H_RULER + H_WAVE + H_EN + H_SK }}>
            {/* ruler */}
            <div className="absolute inset-x-0 top-0 cursor-pointer border-b border-slate-200 dark:border-slate-800" style={{ height: H_RULER }} onClick={seekFromClick}>
              {ticks.map((t) => (
                <div key={t} className="absolute top-0 h-full border-l border-slate-300 pl-1 text-[10px] leading-6 text-slate-500 dark:border-slate-700 dark:text-slate-400" style={{ left: t * zoom }}>
                  {formatTick(t, step)}
                </div>
              ))}
            </div>

            {/* waveform: one viewport-wide canvas that follows the scroll position */}
            <div className="absolute inset-x-0 cursor-pointer" style={{ top: H_RULER, height: H_WAVE }} onClick={seekFromClick}>
              <canvas
                ref={canvas}
                aria-label="Waveform of the original audio"
                className="sticky left-0 text-indigo-400/80 dark:text-indigo-300/70"
                style={{ width: viewWidth, height: H_WAVE }}
              />
              {waveState === "missing" && (
                <span className="pointer-events-none absolute left-2 top-1 text-[11px] text-slate-400">The waveform appears once the audio was extracted.</span>
              )}
            </div>

            {/* English lines: the editable windows */}
            <div className="absolute inset-x-0" style={{ top: H_RULER + H_WAVE, height: H_EN }}>
              {segments.map((raw) => {
                const s = active(raw);
                const selected = s.id === selectedId;
                const left = s.start * zoom;
                const w = Math.max((s.end - s.start) * zoom, 6);
                return (
                  <div
                    key={s.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`English line ${s.id}: ${s.source_text}. ${formatSpan(s.start, s.end)}`}
                    aria-current={selected ? "true" : undefined}
                    onKeyDown={(e) => onKeyDown(e, raw)}
                    onPointerDown={(e) => onPointerDown(e, raw, "move")}
                    onPointerMove={onPointerMove}
                    onPointerUp={onPointerUp}
                    onPointerCancel={() => setDrag(null)}
                    className={`absolute top-1 flex select-none items-center overflow-hidden rounded-md border bg-white/90 px-2 text-xs shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:bg-slate-800/90 ${
                      STATUS_BORDER[raw.fit_status ?? ""] ?? "border-slate-300 dark:border-slate-600"
                    } ${selected ? "ring-2 ring-indigo-500" : ""} ${raw.edited ? "bg-indigo-50 dark:bg-indigo-950/70" : ""} ${editable ? "cursor-grab active:cursor-grabbing" : "cursor-pointer"}`}
                    style={{ left, width: w, height: H_EN - 8, touchAction: "none" }}
                  >
                    {editable && (
                      <>
                        <span
                          data-handle="start"
                          className="absolute inset-y-0 left-0 cursor-col-resize bg-indigo-500/0 hover:bg-indigo-500/30"
                          style={{ width: HANDLE }}
                          onPointerDown={(e) => onPointerDown(e, raw, "start")}
                          onPointerMove={onPointerMove}
                          onPointerUp={onPointerUp}
                    onPointerCancel={() => setDrag(null)}
                        />
                        <span
                          data-handle="end"
                          className="absolute inset-y-0 right-0 cursor-col-resize bg-indigo-500/0 hover:bg-indigo-500/30"
                          style={{ width: HANDLE }}
                          onPointerDown={(e) => onPointerDown(e, raw, "end")}
                          onPointerMove={onPointerMove}
                          onPointerUp={onPointerUp}
                    onPointerCancel={() => setDrag(null)}
                        />
                      </>
                    )}
                    <span className="truncate">{raw.source_text}</span>
                  </div>
                );
              })}
            </div>

            {/* Slovak dub: where the generated speech really sits */}
            <div className="absolute inset-x-0" style={{ top: H_RULER + H_WAVE + H_EN, height: H_SK }}>
              {segments.map((s) => {
                if (s.audio_duration == null) return null;
                const start = s.placed_start ?? s.start;
                const late = start + s.audio_duration > s.end + 0.02;
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => {
                      onSelect(s.id);
                      onSeek(start);
                    }}
                    title={`${s.translated_text}\n${formatSpan(start, start + s.audio_duration)}${late ? "\nRuns past its window" : ""}`}
                    className={`absolute top-1 overflow-hidden truncate rounded-md border px-2 text-left text-xs ${
                      late
                        ? "border-red-500/70 bg-red-100/80 text-red-900 dark:bg-red-950/70 dark:text-red-100"
                        : "border-emerald-500/60 bg-emerald-100/80 text-emerald-900 dark:bg-emerald-950/70 dark:text-emerald-100"
                    } ${s.id === selectedId ? "ring-2 ring-indigo-500" : ""}`}
                    style={{ left: start * zoom, width: Math.max(s.audio_duration * zoom, 6), height: H_SK - 8 }}
                  >
                    {s.translated_text}
                  </button>
                );
              })}
            </div>

            {/* time label while dragging */}
            {dragging && drag && (
              <div
                className="pointer-events-none absolute z-20 -translate-y-full rounded bg-slate-900 px-2 py-0.5 text-[11px] text-white shadow"
                style={{ left: Math.max(drag.start * zoom, 0), top: H_RULER + H_WAVE + 2 }}
              >
                {formatSpan(drag.start, drag.end)}
              </div>
            )}

            {/* playhead */}
            <div
              className="pointer-events-none absolute top-0 z-10 w-px bg-rose-500"
              data-testid="playhead"
              style={{ left: currentTime * zoom, height: H_RULER + H_WAVE + H_EN + H_SK }}
            >
              <span className="absolute -left-1 top-0 size-2 rotate-45 bg-rose-500" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
