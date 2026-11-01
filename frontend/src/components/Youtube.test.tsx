import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Health, Job, ModelsResponse, Options, Project, YoutubeInfo, YoutubeStatus } from "../api";
import { mkModel } from "../testing/models";
import { NewProject } from "./NewProject";
import { ProgressPanel } from "./ProgressPanel";
import { YoutubeSource } from "./YoutubeSource";

const STATUS: YoutubeStatus = {
  installed: true,
  yt_dlp: { available: true, version: "2026.10.26", error: null },
  deno: { available: true, version: "deno 2.9.8", error: null },
  qualities: ["auto", "720", "1080", "1440", "2160"],
  browsers: ["none", "edge", "chrome", "firefox"],
};
const INFO: YoutubeInfo = { id: "abc", title: "A talk about dubbing", uploader: "Someone", thumbnail: "https://i.ytimg.com/x.jpg", duration: 125, is_live: false };

type Handler = (body: unknown) => Response | Promise<Response>;
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });

function route(handlers: Record<string, Handler>) {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, body });
    const handler = handlers[url.split("?")[0] ?? url];
    return handler ? handler(body) : json({ detail: `unexpected ${url}` }, 404);
  }));
  return calls;
}

beforeEach(() => vi.unstubAllGlobals());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("YoutubeSource", () => {
  it("asks for a one-time setup instead of a link while the tools are missing", async () => {
    const models: ModelsResponse = {
      busy: false, required_missing: [],
      models: [mkModel({ id: "youtube", title: "YouTube import tools", size_bytes: 70_000_000, required: false, group: "tools", role: "tools" })],
    };
    route({
      "/api/youtube/status": () => json({ ...STATUS, installed: false, yt_dlp: { available: false, version: null, error: null } }),
      "/api/models": () => json(models),
    });
    render(<YoutubeSource onChoice={vi.fn()} />);
    expect(await screen.findByText(/One-time setup for YouTube links/)).toBeTruthy();
    expect(await screen.findByText(/yt-dlp and Deno \(about 70 MB\)/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Install now/ })).toBeTruthy();
    expect(screen.queryByLabelText("YouTube links (one per line)")).toBeNull();
  });

  it("checks a link, shows the video card and reports the choice", async () => {
    const calls = route({ "/api/youtube/status": () => json(STATUS), "/api/youtube/info": () => json(INFO) });
    const onChoice = vi.fn();
    render(<YoutubeSource onChoice={onChoice} />);
    const input = await screen.findByLabelText("YouTube links (one per line)");
    const check = screen.getByRole("button", { name: "Check link" }) as HTMLButtonElement;
    expect(check.disabled).toBe(true);
    fireEvent.change(input, { target: { value: " https://youtu.be/abc " } });
    fireEvent.click(check);
    const card = await screen.findByTestId("youtube-card");
    expect(card.textContent).toContain("A talk about dubbing");
    expect(card.textContent).toContain("2:05");
    expect(card.querySelector("img")?.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(calls.find((c) => c.url === "/api/youtube/info")?.body).toEqual({ url: "https://youtu.be/abc", cookies_browser: "none" });
    expect(onChoice).toHaveBeenLastCalledWith([{ url: "https://youtu.be/abc", quality: "auto", cookies_browser: "none", info: INFO }]);
  });

  it("starts the check with Ctrl+Enter and shows the reason when YouTube refuses", async () => {
    route({
      "/api/youtube/status": () => json(STATUS),
      "/api/youtube/info": () => json({ detail: "This video is age-restricted. Choose a browser under 'Use cookies from'" }, 422),
    });
    const onChoice = vi.fn();
    render(<YoutubeSource onChoice={onChoice} />);
    const input = await screen.findByLabelText("YouTube links (one per line)");
    fireEvent.change(input, { target: { value: "https://youtu.be/abc" } });
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
    expect((await screen.findByRole("alert")).textContent).toContain("age-restricted");
    expect(onChoice).toHaveBeenLastCalledWith([]);
    expect(screen.queryByTestId("youtube-card")).toBeNull();
  });

  it("does not accept a live stream", async () => {
    route({ "/api/youtube/status": () => json(STATUS), "/api/youtube/info": () => json({ ...INFO, is_live: true }) });
    const onChoice = vi.fn();
    render(<YoutubeSource onChoice={onChoice} />);
    fireEvent.change(await screen.findByLabelText("YouTube links (one per line)"), { target: { value: "https://youtu.be/abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Check link" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Live streams");
    expect(onChoice).toHaveBeenLastCalledWith([]);
  });

  it("forgets the choice when the link changes, and re-reports it when only the quality changes", async () => {
    route({ "/api/youtube/status": () => json(STATUS), "/api/youtube/info": () => json(INFO) });
    const onChoice = vi.fn();
    render(<YoutubeSource onChoice={onChoice} />);
    const input = await screen.findByLabelText("YouTube links (one per line)");
    fireEvent.change(input, { target: { value: "https://youtu.be/abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Check link" }));
    await screen.findByTestId("youtube-card");
    fireEvent.change(screen.getByLabelText(/Video quality/), { target: { value: "720" } });
    expect(onChoice).toHaveBeenLastCalledWith([expect.objectContaining({ quality: "720", url: "https://youtu.be/abc" })]);
    fireEvent.change(input, { target: { value: "https://youtu.be/other" } });
    expect(onChoice).toHaveBeenLastCalledWith([]);
    expect(screen.queryByTestId("youtube-card")).toBeNull();
  });

  it("shows the yt-dlp version and updates it on request", async () => {
    const calls = route({
      "/api/youtube/status": () => json(STATUS),
      "/api/youtube/update": () => json({ message: "Updated yt-dlp to 2026.11.02" }),
    });
    render(<YoutubeSource onChoice={vi.fn()} />);
    expect(await screen.findByText(/yt-dlp 2026\.10\.26/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Update yt-dlp" }));
    expect(await screen.findByText("Updated yt-dlp to 2026.11.02")).toBeTruthy();
    expect(calls.some((c) => c.url === "/api/youtube/update")).toBe(true);
  });

  it("checks several links one after another and keeps the working ones", async () => {
    const calls = route({
      "/api/youtube/status": () => json(STATUS),
      "/api/youtube/info": (body) =>
        (body as { url: string }).url.endsWith("bad") ? json({ detail: "Video unavailable" }, 422) : json({ ...INFO, title: `Video ${(body as { url: string }).url.slice(-1)}` }),
    });
    const onChoice = vi.fn();
    render(<YoutubeSource onChoice={onChoice} />);
    fireEvent.change(await screen.findByLabelText("YouTube links (one per line)"), {
      target: { value: "https://youtu.be/a\nhttps://youtu.be/bad\n  https://youtu.be/c  \nhttps://youtu.be/a" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Check links" }));
    await waitFor(() => expect(onChoice).toHaveBeenLastCalledWith(expect.arrayContaining([expect.anything()])));
    expect(calls.filter((c) => c.url === "/api/youtube/info").map((c) => (c.body as { url: string }).url)).toEqual([
      "https://youtu.be/a", "https://youtu.be/bad", "https://youtu.be/c",
    ]); // a repeated link is checked once
    expect(screen.getAllByTestId("youtube-card")).toHaveLength(2);
    expect(screen.getByRole("alert").textContent).toContain("Video unavailable");
    expect((onChoice.mock.lastCall?.[0] as { url: string }[]).map((c) => c.url)).toEqual(["https://youtu.be/a", "https://youtu.be/c"]);
  });

  it("warns about rights and terms of service", async () => {
    route({ "/api/youtube/status": () => json(STATUS) });
    render(<YoutubeSource onChoice={vi.fn()} />);
    expect(await screen.findByText(/right to download and dub/)).toBeTruthy();
  });
});

describe("NewProject with a YouTube link", () => {
  const options: Options = {
    voices: ["F1", "M1"], source_languages: { en: "English" }, target_language: "sk", default_voice: "F1",
    default_llm: "translategemma:4b", default_asr: "whisper-large-v3", asr_choices: [], translation_choices: [],
    stages: [], max_upload_mb: 100, default_max_upload_mb: 4096, free_disk_mb: 100000, separation_available: true,
  };
  const health: Health = { ok: true, ollama: { reachable: true, error: null, models: ["translategemma:4b"] } };

  async function openLinkTab(handlers: Record<string, Handler> = {}) {
    const calls = route({ "/api/youtube/status": () => json(STATUS), "/api/youtube/info": () => json(INFO), ...handlers });
    const onCreated = vi.fn();
    render(<NewProject options={options} health={health} onCreated={onCreated} />);
    fireEvent.click(screen.getByRole("tab", { name: "YouTube link" }));
    return { calls, onCreated };
  }

  it("cannot start before a link was checked, then creates the project from the link", async () => {
    const project = { id: 5, name: "A talk about dubbing" } as Project;
    const { calls, onCreated } = await openLinkTab({ "/api/projects/from-youtube": () => json(project, 201) });
    const start = screen.getByRole("button", { name: /Download and start dubbing/ }) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    fireEvent.change(await screen.findByLabelText("YouTube links (one per line)"), { target: { value: "https://youtu.be/abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Check link" }));
    await screen.findByTestId("youtube-card");
    expect(start.disabled).toBe(false);
    fireEvent.click(screen.getByLabelText(/Mute completely/));
    fireEvent.click(start);
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(project));
    const body = calls.find((c) => c.url === "/api/projects/from-youtube")?.body as Record<string, unknown>;
    expect(body).toMatchObject({
      url: "https://youtu.be/abc", quality: "auto", cookies_browser: "none", voice: "M1",
      original_audio: "mute", keep_original_track: true, diarize: false, clone_voice: false,
    });
    expect(body).not.toHaveProperty("file");
  });

  it("shows the server's refusal and stays on the page", async () => {
    const { onCreated } = await openLinkTab({
      "/api/projects/from-youtube": () => json({ detail: "Required models are missing: Speech recognition" }, 409),
    });
    fireEvent.change(await screen.findByLabelText("YouTube links (one per line)"), { target: { value: "https://youtu.be/abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Check link" }));
    await screen.findByTestId("youtube-card");
    fireEvent.click(screen.getByRole("button", { name: /Download and start dubbing/ }));
    expect((await screen.findAllByRole("alert")).map((a) => a.textContent).join()).toContain("Required models are missing");
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("goes back to uploading a file with the other tab", async () => {
    await openLinkTab();
    fireEvent.click(screen.getByRole("tab", { name: "Video file" }));
    expect(screen.getByRole("button", { name: /Upload and start dubbing/ })).toBeTruthy();
    expect(screen.queryByLabelText("YouTube links (one per line)")).toBeNull();
  });
});

describe("ProgressPanel for a video from a link", () => {
  const job = (over: Partial<Job>): Job => ({
    id: 3, project_id: 1, status: "running", stage: "download", message: "45.0% - 3MiB/s", progress: 0.05,
    error: null, from_stage: null, attempts: 1, created_at: 0, started_at: 0, finished_at: null, ...over,
  });

  it("lists the download as the first step and names it while it runs", () => {
    render(<ProgressPanel job={job({})} hasDownload onCancel={vi.fn()} onRetry={vi.fn()} busy={false} />);
    expect(screen.getAllByText("Downloading from YouTube").length).toBeGreaterThan(0);
    expect(screen.getByText("45.0% - 3MiB/s")).toBeTruthy();
  });

  it("does not mention a download for an uploaded file", () => {
    render(<ProgressPanel job={job({ stage: "asr", message: "" })} onCancel={vi.fn()} onRetry={vi.fn()} busy={false} />);
    expect(screen.queryByText("Downloading from YouTube")).toBeNull();
  });
});

describe("YoutubeSource: a slow answer for an old link", () => {
  it("is ignored when the link was changed meanwhile", async () => {
    let answer: (r: Response) => void = () => undefined;
    const calls = route({
      "/api/youtube/status": () => json(STATUS),
      "/api/youtube/info": () => new Promise<Response>((resolve) => (answer = resolve)),
    });
    const onChoice = vi.fn();
    render(<YoutubeSource onChoice={onChoice} />);
    const input = await screen.findByLabelText("YouTube links (one per line)");
    fireEvent.change(input, { target: { value: "https://youtu.be/AAA" } });
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(calls.some((c) => c.url === "/api/youtube/info")).toBe(true));
    fireEvent.change(input, { target: { value: "https://youtu.be/BBB" } }); // the user pastes another link
    answer(json({ ...INFO, title: "Video A" })); // the answer for the first one arrives late
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByTestId("youtube-card")).toBeNull();
    expect(onChoice).not.toHaveBeenCalledWith([expect.objectContaining({ url: "https://youtu.be/AAA" })]);
    expect((screen.getByRole("button", { name: "Check link" }) as HTMLButtonElement).disabled).toBe(false);
  });
});
