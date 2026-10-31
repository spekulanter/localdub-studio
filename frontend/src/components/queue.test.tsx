import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Health, Job, Options, Project } from "../api";
import { useTheme } from "../i18n/theme";
import { NewProject } from "./NewProject";
import { ProjectList } from "./ProjectList";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

const job = (id: number, status: Job["status"]): Job => ({
  id, project_id: id, status, stage: "", message: "", progress: 0, error: null, from_stage: null, attempts: 1,
  created_at: 0, started_at: null, finished_at: null,
});
const project = (id: number, status: Job["status"]): Project =>
  ({ id, name: `Dub ${id}`, duration: 10, source_url: null, latest_job: job(id, status) }) as Project;

describe("the queue in the project list", () => {
  it("numbers the waiting dubs in the order they were added, after the one that runs", () => {
    render(
      <ProjectList
        projects={[project(7, "queued"), project(6, "queued"), project(5, "running"), project(4, "done")]}
        selected="new"
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText(/2 waiting in the queue/)).toBeTruthy();
    expect(screen.getByText(/Waiting in queue \(#1\)/).closest("button")?.textContent).toContain("Dub 6");
    expect(screen.getByText(/Waiting in queue \(#2\)/).closest("button")?.textContent).toContain("Dub 7");
  });
});

describe("theme", () => {
  it("applies and remembers light and dark, and goes back to following Windows", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.pref).toBe("system");
    act(() => result.current.setPref("dark"));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("localdub.theme")).toBe("dark");
    act(() => result.current.setPref("light"));
    expect(document.documentElement.dataset.theme).toBe("light");
    act(() => result.current.setPref("system"));
    expect(window.localStorage.getItem("localdub.theme")).toBeNull();
  });
});

describe("several YouTube links at once", () => {
  const options: Options = {
    voices: ["F1"], source_languages: { en: "English", de: "German" }, target_language: "sk", default_voice: "F1",
    default_llm: "m", default_asr: "whisper-large-v3", asr_choices: [], translation_choices: [],
    stages: [], max_upload_mb: 100, separation_available: true,
  };
  const health: Health = { ok: true, ollama: { reachable: true, error: null, models: [] } };

  it("creates one dub per link, in order, and opens the first", async () => {
    const created: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? (JSON.parse(String(init.body)) as { url?: string }) : {};
      if (url.startsWith("/api/youtube/status")) {
        return new Response(JSON.stringify({ installed: true, yt_dlp: { available: true, version: "1", error: null }, deno: { available: true, version: "1", error: null }, qualities: ["auto"], browsers: ["none"] }));
      }
      if (url === "/api/youtube/info") {
        return new Response(JSON.stringify({ title: `T ${body.url}`, uploader: "u", duration: 5, thumbnail: null, is_live: false }));
      }
      if (url === "/api/projects/from-youtube") {
        created.push(body.url ?? "");
        return new Response(JSON.stringify({ id: created.length, name: body.url }), { status: 201 });
      }
      return new Response("{}", { status: 404 });
    }));
    const onCreated = vi.fn();
    render(<NewProject options={options} health={health} onCreated={onCreated} />);
    fireEvent.click(screen.getByRole("tab", { name: "YouTube link" }));
    fireEvent.change(await screen.findByLabelText("YouTube links (one per line)"), { target: { value: "https://youtu.be/a\nhttps://youtu.be/b" } });
    fireEvent.click(screen.getByRole("button", { name: "Check links" }));
    const start = await screen.findByRole("button", { name: "Download and dub 2 videos" });
    await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(start);
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(created).toEqual(["https://youtu.be/a", "https://youtu.be/b"]);
    expect(onCreated.mock.calls[0]?.[0]).toMatchObject({ id: 1 });
  });
});
