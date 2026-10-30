import { describe, expect, it } from "vitest";
import {
  boundsFor,
  clampZoom,
  decodePeaks,
  fitZoom,
  formatTick,
  MAX_PPS,
  MIN_SEGMENT_S,
  moveSpan,
  peakAt,
  resizeSpan,
  snapTime,
  tickStep,
} from "./timeline";

const spans = [
  { id: 1, start: 1, end: 3 },
  { id: 2, start: 4, end: 6 },
  { id: 3, start: 6.5, end: 9 },
];

describe("boundsFor", () => {
  it("uses the neighbours and the video edges", () => {
    expect(boundsFor(spans, 1, 10)).toEqual({ min: 0, max: 4 });
    expect(boundsFor(spans, 2, 10)).toEqual({ min: 3, max: 6.5 });
    expect(boundsFor(spans, 3, 10)).toEqual({ min: 6, max: 10 });
  });
  it("does not depend on the order of the list", () => {
    expect(boundsFor([...spans].reverse(), 2, 10)).toEqual({ min: 3, max: 6.5 });
  });
});

describe("moveSpan", () => {
  const b = { min: 3, max: 6.5 };
  it("moves freely inside the room", () => {
    expect(moveSpan(spans[1]!, 0.25, b)).toEqual({ start: 4.25, end: 6.25 });
  });
  it("stops at the neighbours and keeps the length", () => {
    expect(moveSpan(spans[1]!, 5, b)).toEqual({ start: 4.5, end: 6.5 });
    expect(moveSpan(spans[1]!, -5, b)).toEqual({ start: 3, end: 5 });
  });
  it("does not move at all when there is no room for it", () => {
    expect(moveSpan({ id: 9, start: 4, end: 8 }, 1, { min: 3, max: 6 })).toEqual({ start: 3, end: 7 });
  });
});

describe("resizeSpan", () => {
  const b = { min: 3, max: 6.5 };
  it("moves one edge and clamps to neighbours", () => {
    expect(resizeSpan(spans[1]!, "end", 6.4, b)).toEqual({ start: 4, end: 6.4 });
    expect(resizeSpan(spans[1]!, "end", 99, b)).toEqual({ start: 4, end: 6.5 });
    expect(resizeSpan(spans[1]!, "start", 0, b)).toEqual({ start: 3, end: 6 });
  });
  it("keeps the minimum length", () => {
    expect(resizeSpan(spans[1]!, "start", 5.99, b).end - resizeSpan(spans[1]!, "start", 5.99, b).start).toBeCloseTo(MIN_SEGMENT_S, 5);
    const end = resizeSpan(spans[1]!, "end", 4.01, b);
    expect(end.end - end.start).toBeCloseTo(MIN_SEGMENT_S, 5);
  });
});

describe("snapTime", () => {
  it("snaps within the tolerance only, to the closest target", () => {
    expect(snapTime(5.04, [5, 5.1, 9], 0.08)).toBe(5);
    expect(snapTime(5.07, [5, 5.1], 0.08)).toBe(5.1);
    expect(snapTime(5.5, [5, 9], 0.08)).toBe(5.5);
    expect(snapTime(1, [], 1)).toBe(1);
  });
});

describe("zoom and ticks", () => {
  it("picks readable tick steps", () => {
    expect(tickStep(400)).toBe(0.5);
    expect(tickStep(40)).toBe(5); // 90 px at 40 px/s = 2.25 s, so the next step is 5 s
    expect(tickStep(2)).toBe(60);
  });
  it("formats ticks", () => {
    expect(formatTick(65, 5)).toBe("1:05");
    expect(formatTick(65.5, 0.5)).toBe("1:05.5");
    expect(formatTick(-1, 5)).toBe("0:00");
  });
  it("fits the whole video and clamps zoom", () => {
    expect(fitZoom(100, 1000)).toBe(10);
    expect(fitZoom(0, 1000)).toBe(40);
    expect(fitZoom(1, 100000)).toBe(MAX_PPS);
    expect(clampZoom(0.1)).toBe(2);
  });
});

describe("waveform", () => {
  it("decodes base64 peaks and takes the max over a time range", () => {
    const peaks = decodePeaks(btoa(String.fromCharCode(0, 10, 200, 30)));
    expect(Array.from(peaks)).toEqual([0, 10, 200, 30]);
    expect(peakAt(peaks, 100, 0.01, 0.03)).toBe(200); // bins 1..2
    expect(peakAt(peaks, 100, 0, 0.01)).toBe(0);
    expect(peakAt(peaks, 100, 5, 6)).toBe(0); // past the end
  });
});
