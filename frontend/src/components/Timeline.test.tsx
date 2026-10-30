import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SegmentRow } from "../api";
import { Timeline } from "./Timeline";

const seg = (over: Partial<SegmentRow>): SegmentRow => ({
  id: 1, start: 1, end: 3, source_text: "Hello there", translated_text: "Ahoj", fit_status: "ok", speaker_id: "S1",
  voice_id: null, effective_voice: "F1", review_status: "pending", edited: false, stale_edit: false, has_audio: true,
  placed_start: 1, audio_duration: 1.5, ...over,
});

// 10 s long, the view is 800 px wide in jsdom -> 80 px per second
const SEGMENTS = [
  seg({ id: 1, start: 1, end: 3 }),
  seg({ id: 2, start: 3.5, end: 6, source_text: "Second line", translated_text: "Druhá veta", placed_start: 3.5, audio_duration: 3 }),
  seg({ id: 3, start: 7, end: 9, source_text: "Third", audio_duration: null, placed_start: null, has_audio: false }),
];

type TimingFn = (id: number, start: number, end: number) => Promise<void>;

function setup(over: Partial<Omit<React.ComponentProps<typeof Timeline>, "onTimingChange">> & { onTimingChange?: ReturnType<typeof vi.fn<TimingFn>> } = {}) {
  const onTimingChange = over.onTimingChange ?? vi.fn<TimingFn>().mockResolvedValue(undefined);
  const props = {
    projectId: 1, segments: SEGMENTS, duration: 10, editable: true, selectedId: null as number | null,
    onSelect: vi.fn(), currentTime: 0, playing: false, onSeek: vi.fn(), ...over, onTimingChange,
  };
  render(<Timeline {...props} />);
  return { ...props, onTimingChange };
}

const block = (id: number) => screen.getByRole("button", { name: new RegExp(`^English line ${id}:`) });

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ available: false }))));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Timeline", () => {
  it("shows every English line with its time span and the Slovak dub where audio exists", () => {
    setup();
    expect(block(1).getAttribute("aria-label")).toContain("1.00 – 3.00 s (2.00 s)");
    expect(block(2).getAttribute("aria-label")).toContain("Second line");
    expect(block(1).style.left).toBe("80px");
    expect(block(1).style.width).toBe("160px");
    expect(screen.getByTitle(/Ahoj/)).toBeTruthy();
    expect(screen.queryByTitle(/Third/)).toBeNull(); // line 3 has no audio yet
  });

  it("marks Slovak speech that runs past its window", () => {
    setup();
    const late = screen.getByTitle(/Druhá veta/);
    expect(late.getAttribute("title")).toContain("Runs past its window");
    expect(late.className).toContain("red");
    expect(screen.getByTitle(/Ahoj/).className).toContain("emerald");
  });

  it("puts the playhead at the current time", () => {
    setup({ currentTime: 2.5 });
    expect(screen.getByTestId("playhead").style.left).toBe("200px");
  });

  it("selects a line and seeks to its start on click", () => {
    const p = setup();
    fireEvent.pointerDown(block(2), { button: 0, clientX: 300, pointerId: 1 });
    fireEvent.pointerUp(block(2), { clientX: 300, pointerId: 1 });
    expect(p.onSelect).toHaveBeenCalledWith(2);
    expect(p.onSeek).toHaveBeenCalledWith(3.5);
    expect(p.onTimingChange).not.toHaveBeenCalled(); // a click is not a drag
  });

  it("moves a line by dragging and saves the new timing", async () => {
    const p = setup();
    fireEvent.pointerDown(block(1), { button: 0, clientX: 200, pointerId: 1 });
    fireEvent.pointerMove(block(1), { clientX: 240, pointerId: 1 }); // +40 px = +0.5 s
    fireEvent.pointerUp(block(1), { clientX: 240, pointerId: 1 });
    await waitFor(() => expect(p.onTimingChange).toHaveBeenCalledWith(1, 1.5, 3.5));
  });

  it("cannot drag a line into its neighbour", async () => {
    const p = setup();
    fireEvent.pointerDown(block(1), { button: 0, clientX: 200, pointerId: 1 });
    fireEvent.pointerMove(block(1), { clientX: 700, pointerId: 1 }); // far right
    fireEvent.pointerUp(block(1), { clientX: 700, pointerId: 1 });
    await waitFor(() => expect(p.onTimingChange).toHaveBeenCalled());
    const [, start, end] = p.onTimingChange.mock.calls[0] as [number, number, number];
    expect(end).toBe(3.5); // stops where line 2 starts
    expect(end - start).toBeCloseTo(2, 5); // and keeps its length
  });

  it("resizes with the edge handles", async () => {
    const p = setup({ currentTime: 0 });
    const handle = block(2).querySelector('[data-handle="end"]') as HTMLElement;
    fireEvent.pointerDown(handle, { button: 0, clientX: 480, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientX: 560, pointerId: 1 }); // +1 s, limited by line 3 at 7 s
    fireEvent.pointerUp(handle, { clientX: 560, pointerId: 1 });
    await waitFor(() => expect(p.onTimingChange).toHaveBeenCalledWith(2, 3.5, 7));
  });

  it("nudges with the arrow keys (Shift = 0.5 s)", async () => {
    const p = setup();
    fireEvent.keyDown(block(3), { key: "ArrowLeft" });
    await waitFor(() => expect(p.onTimingChange).toHaveBeenCalledWith(3, 6.95, 8.95));
    p.onTimingChange.mockClear();
    fireEvent.keyDown(block(1), { key: "ArrowLeft", shiftKey: true });
    await waitFor(() => expect(p.onTimingChange).toHaveBeenCalledWith(1, 0.5, 2.5));
  });

  it("does nothing when a neighbour leaves no room, and ignores keys while a save is running", async () => {
    let finish: () => void = () => undefined;
    const onTimingChange = vi.fn<TimingFn>().mockReturnValue(new Promise<void>((r) => (finish = r)));
    setup({
      segments: [seg({ id: 1, start: 1, end: 3 }), seg({ id: 2, start: 3, end: 6, audio_duration: null, placed_start: null })],
      onTimingChange,
    });
    fireEvent.keyDown(block(2), { key: "ArrowLeft" }); // touches line 1: no room
    expect(onTimingChange).not.toHaveBeenCalled();
    fireEvent.keyDown(block(2), { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(block(2), { key: "ArrowRight", shiftKey: true }); // a save is already running
    expect(onTimingChange).toHaveBeenCalledTimes(1);
    expect(onTimingChange).toHaveBeenCalledWith(2, 3.5, 6.5);
    finish();
  });

  it("forgets a drag that the system cancelled (pointercancel)", () => {
    const p = setup();
    fireEvent.pointerDown(block(1), { button: 0, clientX: 200, pointerId: 1 });
    fireEvent.pointerMove(block(1), { clientX: 260, pointerId: 1 });
    expect(block(1).style.left).not.toBe("80px"); // it follows the pointer
    fireEvent.pointerCancel(block(1), { pointerId: 1 });
    expect(block(1).style.left).toBe("80px"); // and snaps back
    fireEvent.pointerUp(block(1), { clientX: 260, pointerId: 1 });
    expect(p.onTimingChange).not.toHaveBeenCalled();
  });

  it("marks the selected line with aria-current and can be scrolled with the keyboard", () => {
    setup({ selectedId: 2 });
    expect(block(2).getAttribute("aria-current")).toBe("true");
    expect(block(1).getAttribute("aria-current")).toBeNull();
    const region = screen.getByRole("region", { name: /Timeline/ });
    expect(region.getAttribute("tabindex")).toBe("0");
  });

  it("is read-only while a job runs", () => {
    const p = setup({ editable: false });
    expect(block(1).querySelector("[data-handle]")).toBeNull();
    fireEvent.keyDown(block(1), { key: "ArrowRight" });
    fireEvent.pointerDown(block(1), { button: 0, clientX: 200, pointerId: 1 });
    fireEvent.pointerMove(block(1), { clientX: 260, pointerId: 1 });
    fireEvent.pointerUp(block(1), { clientX: 260, pointerId: 1 });
    expect(p.onTimingChange).not.toHaveBeenCalled();
    expect(p.onSelect).toHaveBeenCalledWith(1); // selecting still works
  });

  it("shows the server's reason when a change is refused", async () => {
    const p = setup({ onTimingChange: vi.fn<TimingFn>().mockRejectedValue(new Error("Start overlaps the previous segment")) });
    fireEvent.keyDown(block(2), { key: "ArrowLeft" });
    expect((await screen.findByRole("alert")).textContent).toContain("overlaps the previous segment");
    expect(p.onTimingChange).toHaveBeenCalledOnce();
  });

  it("seeks when the ruler is clicked", () => {
    const p = setup();
    const ruler = screen.getByText("0:00").parentElement as HTMLElement;
    fireEvent.click(ruler, { clientX: 160 });
    expect(p.onSeek).toHaveBeenCalled();
  });

  it("explains the missing waveform instead of showing an empty box", async () => {
    setup();
    expect(await screen.findByText(/waveform appears once the audio was extracted/i)).toBeTruthy();
  });
});
