/** Pure helpers for the timeline: time <-> pixels, drag limits and snapping. */

/** Same limits the server enforces (localdub/core/timeline/edits.py). */
export const MIN_SEGMENT_S = 0.3;

export interface Span {
  id: number;
  start: number;
  end: number;
}

export interface Bounds {
  /** Earliest allowed start: the end of the previous segment, or 0. */
  min: number;
  /** Latest allowed end: the start of the next segment, or the video duration. */
  max: number;
}

export const round2 = (t: number): number => Math.round(t * 100) / 100;

/** Free room around a segment: neighbours (sorted by start) and the video edges. */
export function boundsFor(spans: Span[], id: number, duration: number): Bounds {
  const sorted = [...spans].sort((a, b) => a.start - b.start);
  const i = sorted.findIndex((s) => s.id === id);
  const prev = i > 0 ? sorted[i - 1] : undefined;
  const next = i >= 0 ? sorted[i + 1] : undefined;
  return { min: prev ? prev.end : 0, max: next ? next.start : duration };
}

/** Move a segment by `delta` seconds, keeping its length, inside its bounds. */
export function moveSpan(span: Span, delta: number, b: Bounds): { start: number; end: number } {
  const length = span.end - span.start;
  const start = Math.min(Math.max(span.start + delta, b.min), Math.max(b.max - length, b.min));
  return { start: round2(start), end: round2(start + length) };
}

/** Drag one edge to time `t`, never below the minimum length or into a neighbour. */
export function resizeSpan(
  span: Span,
  edge: "start" | "end",
  t: number,
  b: Bounds,
): { start: number; end: number } {
  if (edge === "start") {
    const start = Math.min(Math.max(t, b.min), span.end - MIN_SEGMENT_S);
    return { start: round2(start), end: span.end };
  }
  const end = Math.max(Math.min(t, b.max), span.start + MIN_SEGMENT_S);
  return { start: span.start, end: round2(end) };
}

/** Snap `t` to the nearest target within `tolerance` seconds (or return it unchanged). */
export function snapTime(t: number, targets: number[], tolerance: number): number {
  let best = t;
  let bestDistance = tolerance;
  for (const target of targets) {
    const d = Math.abs(target - t);
    if (d <= bestDistance) {
      best = target;
      bestDistance = d;
    }
  }
  return best;
}

export const timeToX = (t: number, pps: number): number => t * pps;
export const xToTime = (x: number, pps: number): number => x / pps;

const STEPS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600];

/** Tick spacing in seconds so that labelled ticks are at least `minPx` apart. */
export function tickStep(pps: number, minPx = 90): number {
  return STEPS.find((s) => s * pps >= minPx) ?? STEPS[STEPS.length - 1]!;
}

export function formatTick(t: number, step: number): string {
  const total = Math.max(0, t);
  const m = Math.floor(total / 60);
  const s = total - m * 60;
  return step < 1 ? `${m}:${s.toFixed(1).padStart(4, "0")}` : `${m}:${String(Math.round(s)).padStart(2, "0")}`;
}

export function formatSpan(start: number, end: number): string {
  return `${start.toFixed(2)} – ${end.toFixed(2)} s (${(end - start).toFixed(2)} s)`;
}

/** Zoom that makes the whole video fit into `width` pixels (never absurdly small or large). */
export function fitZoom(duration: number, width: number): number {
  if (duration <= 0 || width <= 0) return 40;
  return Math.min(Math.max(width / duration, MIN_PPS), MAX_PPS);
}

export const MIN_PPS = 2;
export const MAX_PPS = 400;
export const clampZoom = (pps: number): number => Math.min(Math.max(pps, MIN_PPS), MAX_PPS);

export function decodePeaks(base64: string): Uint8Array {
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** Peak (0..255) of the waveform for the time range [t0, t1) (a pixel column). */
export function peakAt(peaks: Uint8Array, binsPerSecond: number, t0: number, t1: number): number {
  const a = Math.max(0, Math.floor(t0 * binsPerSecond));
  const b = Math.min(peaks.length, Math.max(a + 1, Math.ceil(t1 * binsPerSecond)));
  let max = 0;
  for (let i = a; i < b; i++) {
    const v = peaks[i] ?? 0;
    if (v > max) max = v;
  }
  return max;
}
