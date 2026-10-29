import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Health, Job, Options } from "../api";
import { NewProject } from "./NewProject";
import { ProgressPanel } from "./ProgressPanel";
import { SegmentsTable } from "./SegmentsTable";

afterEach(cleanup);

const options: Options = {
  voices: ["F1", "M1"],
  source_languages: { en: "English", auto: "Auto-detect" },
  target_language: "sk",
  default_voice: "F1",
  default_llm: "translategemma:4b",
  stages: ["probe", "extract", "asr", "translate", "tts", "assemble", "export"],
  max_upload_mb: 1,
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

describe("SegmentsTable", () => {
  it("renders rows with timing chips and counts tight segments", () => {
    render(
      <SegmentsTable
        data={{
          stage: "segments",
          segments: [
            { id: 1, start: 0, end: 2, source_text: "Hello", translated_text: "Ahoj", fit_status: "ok" },
            { id: 2, start: 3, end: 5, source_text: "Bye", translated_text: "Dovidenia a ešte dlho", fit_status: "overflow" },
          ],
        }}
      />,
    );
    expect(screen.getByText("Ahoj")).toBeTruthy();
    expect(screen.getByText("too long")).toBeTruthy();
    expect(screen.getByText(/1 where timing is tight/)).toBeTruthy();
  });

  it("explains the empty state", () => {
    render(<SegmentsTable data={null} />);
    expect(screen.getByText(/appear here/)).toBeTruthy();
  });
});
