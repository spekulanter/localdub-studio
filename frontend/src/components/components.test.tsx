import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Health, Job, ModelInfo, ModelsResponse, Options, SegmentRow, SegmentsResponse } from "../api";
import { ModelsPanel } from "./ModelsPanel";
import { InstallNotice } from "./InstallNotice";

const INTRO = (size: string) => `This needs an extra download of about ${size} (PyTorch).`;
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
    expect(screen.getByRole("heading", { name: /Generating Slovak voice/ })).toBeTruthy();
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
  voice_id: null, effective_voice: "F1", review_status: "pending", edited: false, stale_edit: false, has_audio: false, placed_start: null, audio_duration: null, ...over,
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
    expect(screen.queryByText(/uv sync/)).toBeNull(); // no manual commands any more
  });

  it("enables it when available", () => {
    render(<NewProject options={{ ...options, separation_available: true }} health={health} onCreated={vi.fn()} />);
    const radio = screen.getByLabelText(/Remove the speech/) as HTMLInputElement;
    expect(radio.disabled).toBe(false);
    fireEvent.click(radio);
    expect(screen.getByText(/downloads an 80 MB model/)).toBeTruthy();
  });
});

describe("voice cloning consent", () => {
  it("cannot start until the consent box is ticked", () => {
    render(<NewProject options={{ ...options, separation_available: true }} health={health} onCreated={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Video file"), { target: { files: [new File([new Uint8Array(5)], "a.mp4")] } });
    const submit = screen.getByRole("button", { name: /upload and start/i }) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    fireEvent.click(screen.getByLabelText(/sound like the original speaker/));
    expect(submit.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/I have the right to imitate/));
    expect(submit.disabled).toBe(false);
    fireEvent.click(screen.getByLabelText(/sound like the original speaker/));
    expect(screen.queryByLabelText(/I have the right to imitate/)).toBeNull();
  });

  it("is unavailable without the optional packages", () => {
    render(<NewProject options={options} health={health} onCreated={vi.fn()} />);
    expect((screen.getByLabelText(/sound like the original speaker/) as HTMLInputElement).disabled).toBe(true);
  });
});

describe("ModelsPanel", () => {
  const model = (over: Partial<ModelInfo>): ModelInfo => ({
    id: "whisper", title: "Speech recognition", description: "d", size_bytes: 3_000_000_000, required: true,
    group: "core", installed: false, available: true, download: null, ...over,
  });
  const resp = (models: ModelInfo[], busy = false): ModelsResponse => ({
    models, busy, required_missing: models.filter((m) => m.required && !m.installed).map((m) => m.id),
  });

  it("offers one button for all missing required models and shows the total size", () => {
    render(<ModelsPanel data={resp([model({}), model({ id: "tts", title: "Voice", size_bytes: 400_000_000 })])} onChanged={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Download the required models \(3\.4 GB\)/ })).toBeTruthy();
  });

  it("shows a progress bar with percent and bytes while downloading", () => {
    const dl = { status: "running" as const, done: 1_500_000_000, total: 3_000_000_000, message: "", error: null };
    render(<ModelsPanel data={resp([model({ download: dl })], true)} onChanged={vi.fn()} />);
    const bar = screen.getByRole("progressbar", { name: /Download of Speech recognition/ });
    expect(bar.getAttribute("aria-valuenow")).toBe("50");
    expect(screen.getByText(/50% · 1\.5 GB of 3\.0 GB/)).toBeTruthy();
  });

  it("shows a failed download with its reason and a retry button", () => {
    const dl = { status: "error" as const, done: 0, total: 1, message: "Failed", error: "Ollama is not running" };
    render(<ModelsPanel data={resp([model({ download: dl })])} onChanged={vi.fn()} />);
    expect(screen.getByRole("alert").textContent).toContain("Ollama is not running");
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it("marks installed models and explains unavailable optional ones", () => {
    render(<ModelsPanel data={resp([model({ installed: true }), model({ id: "separation", title: "Separation", required: false, available: false })])} onChanged={vi.fn()} />);
    expect(screen.getByText("✓ installed")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download with the optional packages" })).toBeTruthy();
  });
});

describe("failed job log actions", () => {
  it("copies the error and offers the full log as a download", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: write } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ lines: [] }))));
    render(<ProgressPanel job={job({ status: "failed", error: "[tts] boom" })} onCancel={vi.fn()} onRetry={vi.fn()} busy={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy error" }));
    await waitFor(() => expect(write).toHaveBeenCalledWith("[tts] boom"));
    const link = screen.getByRole("link", { name: "Download log" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/api/jobs/7/log/download");
    vi.unstubAllGlobals();
  });
});

describe("start is blocked while required models are missing", () => {
  it("disables the upload button and explains why", () => {
    render(<NewProject options={options} health={health} onCreated={vi.fn()} modelsMissing />);
    fireEvent.change(screen.getByLabelText("Video file"), { target: { files: [new File([new Uint8Array(5)], "a.mp4")] } });
    expect((screen.getByRole("button", { name: /upload and start/i }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Download the AI models first/)).toBeTruthy();
  });
});

describe("InstallNotice (install the optional packages without commands)", () => {
  const row = (over: Partial<ModelInfo>): ModelInfo => ({
    id: "packages", title: "Optional packages", description: "d", size_bytes: 2_900_000_000, required: false,
    group: "packages", installed: false, available: true, download: null, ...over,
  });
  const sep = (over: Partial<ModelInfo> = {}) =>
    row({ id: "separation", title: "Separation", size_bytes: 80_000_000, group: "separation", available: false, ...over });
  const reply = (models: ModelInfo[]) =>
    new Response(JSON.stringify({ models, required_missing: [], busy: false }), { status: 200 });

  it("offers one button with the total size and sends the packages together with the model", async () => {
    const posted: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posted.push(String(init.body));
        return new Response(JSON.stringify({ started: ["packages", "separation"] }), { status: 202 });
      }
      return reply([row({}), sep()]);
    }));
    render(<InstallNotice intro={INTRO} ids={["packages", "separation"]} onInstalled={vi.fn()} />);
    const button = await screen.findByRole("button", { name: /Install now \(3\.0 GB\)/ });
    expect(screen.getByText(/no administrator rights and no commands are needed/)).toBeTruthy();
    fireEvent.click(button);
    await waitFor(() => expect(posted).toEqual(['{"ids":["packages","separation"]}']));
    vi.unstubAllGlobals();
  });

  it("shows live progress in bytes while installing", async () => {
    const dl = { status: "running" as const, done: 1_500_000_000, total: 2_900_000_000, message: "Downloading torch", error: null };
    vi.stubGlobal("fetch", vi.fn(async () => reply([row({ download: dl }), sep()])));
    render(<InstallNotice intro={INTRO} ids={["packages", "separation"]} onInstalled={vi.fn()} />);
    const bar = await screen.findByRole("progressbar", { name: /Installing the optional packages/ });
    expect(Number(bar.getAttribute("aria-valuenow"))).toBeGreaterThanOrEqual(49);
    expect(screen.getByText(/1\.5 GB of 3\.0 GB · Downloading torch/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Install now/ })).toBeNull();
    vi.unstubAllGlobals();
  });

  it("shows only a percentage and the step text for the package install (its total includes unpacking)", async () => {
    const dl = {
      status: "running" as const, done: 2_960_000_000, total: 7_400_000_000,
      message: "Downloading torch (1.2 GB of 2.9 GB)", error: null, show_bytes: false,
    };
    vi.stubGlobal("fetch", vi.fn(async () => reply([row({ download: dl }), sep({ installed: true })])));
    render(<InstallNotice intro={INTRO} ids={["packages", "separation"]} onInstalled={vi.fn()} />);
    expect(await screen.findByText("40% · Downloading torch (1.2 GB of 2.9 GB)")).toBeTruthy();
    expect(screen.queryByText(/7\.4 GB/)).toBeNull(); // no misleading byte totals
    vi.unstubAllGlobals();
  });

  it("shows why it failed and lets the user try again", async () => {
    const dl = { status: "error" as const, done: 0, total: 1, message: "Failed", error: "Not enough free disk space" };
    vi.stubGlobal("fetch", vi.fn(async () => reply([row({ download: dl }), sep()])));
    render(<InstallNotice intro={INTRO} ids={["packages", "separation"]} onInstalled={vi.fn()} />);
    expect((await screen.findByRole("alert")).textContent).toContain("Not enough free disk space");
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    vi.unstubAllGlobals();
  });

  it("tells the page once when everything is installed", async () => {
    const onInstalled = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async () => reply([row({ installed: true }), sep({ installed: true, available: true })])));
    render(<InstallNotice intro={INTRO} ids={["packages", "separation"]} onInstalled={onInstalled} />);
    expect(await screen.findByText(/Installed\. This option is ready to use\./)).toBeTruthy();
    await waitFor(() => expect(onInstalled).toHaveBeenCalledTimes(1));
    vi.unstubAllGlobals();
  });
});

describe("DialogueEditor audio", () => {
  const row = (over: Partial<SegmentRow> = {}): SegmentRow => ({
    id: 1, start: 0, end: 2, source_text: "Hello", translated_text: "Ahoj", fit_status: "ok", speaker_id: "S1",
    voice_id: null, effective_voice: "F1", review_status: "pending", edited: false, stale_edit: false,
    has_audio: false, placed_start: null, audio_duration: null, ...over,
  });

  it("frees the previewed clips and stops talking when the page is left", async () => {
    let n = 0;
    const created: string[] = [];
    const revoked: string[] = [];
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: () => { const u = `blob:clip-${++n}`; created.push(u); return u; },
      revokeObjectURL: (u: string) => { revoked.push(u); },
    }));
    const pause = vi.fn();
    class FakeAudio {
      constructor(public src: string) {}
      play = vi.fn().mockResolvedValue(undefined);
      pause = pause;
    }
    vi.stubGlobal("Audio", FakeAudio);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new Blob(["x"]), { headers: { "X-Audio-Duration": "1.0", "X-Window": "2.0" } })));
    const { unmount } = render(
      <DialogueEditor projectId={1} data={data([row()])} options={options} editable renderVersion={0} onChange={vi.fn()} onRerender={vi.fn()} busy={false} />,
    );
    const tryText = screen.getByRole("button", { name: /Try this text/ });
    fireEvent.click(tryText);
    await waitFor(() => expect(created).toEqual(["blob:clip-1"]));
    fireEvent.click(tryText);
    await waitFor(() => expect(created).toEqual(["blob:clip-1", "blob:clip-2"]));
    expect(revoked).toEqual(["blob:clip-1"]); // the first clip was freed when the second one played
    unmount();
    expect(revoked).toEqual(["blob:clip-1", "blob:clip-2"]);
    expect(pause).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
