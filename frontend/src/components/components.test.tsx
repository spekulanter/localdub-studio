import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Health, Job, Options, SegmentRow, SegmentsResponse } from "../api";
import { NewProject } from "./NewProject";
import { ProgressPanel } from "./ProgressPanel";
import { DialogueEditor } from "./DialogueEditor";

afterEach(cleanup);

const options: Options = {
  voices: ["F1", "M1"],
  source_languages: { en: "English", auto: "Auto-detect" },
  target_language: "sk",
  default_voice: "F1",
  default_llm: "translategemma:4b",
  stages: ["probe", "extract", "asr", "translate", "tts", "assemble", "export"],
  max_upload_mb: 1,
  separation_available: false,
};
const health: Health = { ok: true, ollama: { reachable: true, error: null, models: ["translategemma:4b", "qwen3:8b"] } };

const job = (over: Partial<Job>): Job => ({
  id: 7, project_id: 1, status: "running", stage: "tts", message: "3/10", progress: 0.5, error: null,
  from_stage: null, attempts: 1, created_at: 0, started_at: 0, finished_at: null, ...over,
});

describe("NewProject", () => {
  it("keeps the submit button disabled until a file is chosen, and rejects oversized files", () => {
    render(<NewProject options={options} health={health} onCreated={vi.fn()} />);
    const submit = screen.getByRole("button", { name: /upload and start/i });
    expect((submit as HTMLButtonElement).disabled).toBe(true);

    const input = screen.getByLabelText("Video file");
    const small = new File([new Uint8Array(10)], "malý klip ✓.mp4", { type: "video/mp4" });
    fireEvent.change(input, { target: { files: [small] } });
    expect(screen.getByText("malý klip ✓.mp4")).toBeTruthy();
    expect((submit as HTMLButtonElement).disabled).toBe(false);

    const big = new File([new Uint8Array(2 * 1024 * 1024)], "big.mp4", { type: "video/mp4" });
    fireEvent.change(input, { target: { files: [big] } });
    expect(screen.getByText(/larger than 1 MB/)).toBeTruthy();
    expect((submit as HTMLButtonElement).disabled).toBe(true);
  });

  it("warns that muting removes music", () => {
    render(<NewProject options={options} health={health} onCreated={vi.fn()} />);
    expect(screen.queryByText(/removes music/)).toBeNull();
    fireEvent.click(screen.getByLabelText(/Mute completely/));
    expect(screen.getByText(/removes music/)).toBeTruthy();
  });
});

describe("NewProject batch", () => {
  it("lists several chosen videos and uploads them one after another", async () => {
    const posted: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      posted.push(((init?.body as FormData).get("file") as File).name);
      return new Response(JSON.stringify({ id: posted.length, name: "x" }), { status: 201 });
    }));
    const onCreated = vi.fn();
    render(<NewProject options={options} health={health} onCreated={onCreated} />);
    const a = new File([new Uint8Array(5)], "a.mp4", { type: "video/mp4" });
    const b = new File([new Uint8Array(5)], "b ľ.mp4", { type: "video/mp4" });
    fireEvent.change(screen.getByLabelText("Video file"), { target: { files: [a, b] } });
    expect(screen.getByText(/dubbed one after another/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /dub 2 videos/i }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledOnce());
    expect(posted).toEqual(["a.mp4", "b ľ.mp4"]);
    vi.unstubAllGlobals();
  });
});

describe("ProgressPanel", () => {
  it("shows percent, stage and a cancel button while running", () => {
    const onCancel = vi.fn();
    render(<ProgressPanel job={job({})} onCancel={onCancel} onRetry={vi.fn()} busy={false} />);
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("50");
    expect(screen.getByText("Generating Slovak voice")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("shows the error and offers a retry after a failure", () => {
    const onRetry = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ lines: ["boom line"] }))));
    render(<ProgressPanel job={job({ status: "failed", error: "[translate] Ollama is not running" })} onCancel={vi.fn()} onRetry={onRetry} busy={false} />);
    expect(screen.getByRole("alert").textContent).toContain("Ollama is not running");
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });
});

const segment = (over: Partial<SegmentRow>): SegmentRow => ({
  id: 1, start: 0, end: 2, source_text: "Hello", translated_text: "Ahoj", fit_status: "ok", speaker_id: "S1",
  voice_id: null, effective_voice: "F1", review_status: "pending", edited: false, stale_edit: false, has_audio: false, ...over,
});
const data = (segments: SegmentRow[], pending = false): SegmentsResponse => ({
  stage: "segments", segments, edits_pending: pending, speaker_voices: {}, speaker_defaults: { S1: "F1", S2: "M1" }, speaker_gender_estimate: {},
});

describe("DialogueEditor", () => {
  const renderEditor = (d: SegmentsResponse | null, editable = true, onRerender = vi.fn()) =>
    render(<DialogueEditor projectId={1} data={d} options={options} editable={editable} renderVersion={0} onChange={vi.fn()} onRerender={onRerender} busy={false} />);

  it("renders rows with timing chips and counts tight and edited lines", () => {
    renderEditor(data([segment({}), segment({ id: 2, translated_text: "Dovidenia", fit_status: "overflow", edited: true })]));
    expect(screen.getByDisplayValue("Ahoj")).toBeTruthy();
    expect(screen.getByText("too long")).toBeTruthy();
    expect(screen.getByText(/1 where timing is tight/)).toBeTruthy();
    expect(screen.getByText(/1 edited by you/)).toBeTruthy();
  });

  it("enables Save only for a changed line and sends the edit", async () => {
    const patch = vi.fn().mockResolvedValue(segment({}));
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      patch(url, init?.body);
      return new Response(JSON.stringify(segment({})));
    }));
    renderEditor(data([segment({})]));
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Slovak text for line 1"), { target: { value: "Čau svet" } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await waitFor(() => expect(patch).toHaveBeenCalled());
    const [url, body] = patch.mock.calls[0] as [string, string];
    expect(url).toBe("/api/projects/1/segments/1");
    expect(JSON.parse(body)).toMatchObject({ translated_text: "Čau svet", voice_id: null, start: 0, end: 2 });
    vi.unstubAllGlobals();
  });

  it("offers re-render only when edits are pending", () => {
    const onRerender = vi.fn();
    const { rerender } = renderEditor(data([segment({})], false), true, onRerender);
    expect(screen.queryByRole("button", { name: /re-render/i })).toBeNull();
    rerender(<DialogueEditor projectId={1} data={data([segment({})], true)} options={options} editable renderVersion={0} onChange={vi.fn()} onRerender={onRerender} busy={false} />);
    fireEvent.click(screen.getByRole("button", { name: /re-render changed lines/i }));
    expect(onRerender).toHaveBeenCalledOnce();
  });

  it("locks editing while a job runs and shows speaker voices for multiple speakers", () => {
    renderEditor(data([segment({}), segment({ id: 2, speaker_id: "S2" })]), false);
    expect((screen.getByLabelText("Slovak text for line 1") as HTMLTextAreaElement).disabled).toBe(true);
    expect(screen.queryByText("Voice per speaker")).toBeNull();
    cleanup();
    renderEditor(data([segment({}), segment({ id: 2, speaker_id: "S2" })]), true);
    expect(screen.getByText("Voice per speaker")).toBeTruthy();
  });

  it("explains the empty state", () => {
    renderEditor(null);
    expect(screen.getByText(/appears here/)).toBeTruthy();
  });
});

describe("original voice options", () => {
  it("disables speech removal when the optional packages are missing and explains how to enable it", () => {
    render(<NewProject options={options} health={health} onCreated={vi.fn()} />);
    expect((screen.getByLabelText(/Remove the speech/) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText(/uv sync --extra separation/)).toBeTruthy();
  });

  it("enables it when available", () => {
    render(<NewProject options={{ ...options, separation_available: true }} health={health} onCreated={vi.fn()} />);
    const radio = screen.getByLabelText(/Remove the speech/) as HTMLInputElement;
    expect(radio.disabled).toBe(false);
    fireEvent.click(radio);
    expect(screen.getByText(/downloads an 80 MB model/)).toBeTruthy();
  });
});
