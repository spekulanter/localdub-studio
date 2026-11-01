import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { UpdateInfo } from "../api";
import { UpdateBanner } from "./UpdateBanner";

const base: UpdateInfo = {
  current: "0.5.2", available: true, version: "0.6.0", notes: "x", page: "https://github.com/spekulanter/localdub-studio/releases/tag/v0.6.0",
  asset: "LocalDub-Studio-0.6.0-Setup.exe", size: 14_000_000, error: null,
  download: { status: "idle", done: 0, total: 0, error: null },
};
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });

function serve(handlers: Record<string, () => Response>) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url.split("?")[0]}`);
    const h = handlers[url.split("?")[0] ?? url];
    return h ? h() : json({ detail: "unexpected" }, 404);
  }));
  return calls;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("UpdateBanner", () => {
  it("says nothing when there is no newer version, and asks nobody when switched off", async () => {
    const calls = serve({ "/api/update": () => json({ ...base, available: false, version: null }) });
    const { container } = render(<UpdateBanner enabled />);
    await waitFor(() => expect(calls).toContain("GET /api/update"));
    expect(container.textContent).toBe("");
    cleanup();
    const off = serve({});
    render(<UpdateBanner enabled={false} />);
    expect(off).toEqual([]);
  });

  it("offers the new version, downloads it and then installs on a second click", async () => {
    let state: UpdateInfo = base;
    const calls = serve({
      "/api/update": () => json(state),
      "/api/update/download": () => {
        state = { ...base, download: { status: "ready", done: 14_000_000, total: 14_000_000, error: null } };
        return json(state, 202);
      },
      "/api/update/install": () => json({ closing: true }),
    });
    render(<UpdateBanner enabled />);
    expect(await screen.findByText(/Version 0.6.0 is available \(you have 0.5.2\)/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Download and update/ }));
    const install = await screen.findByRole("button", { name: "Install now" });
    fireEvent.click(install);
    expect(await screen.findByText(/Closing so the update can be installed/)).toBeTruthy();
    expect(calls).toContain("POST /api/update/install");
  });

  it("asks before interrupting a running dub", async () => {
    const ready: UpdateInfo = { ...base, download: { status: "ready", done: 1, total: 1, error: null } };
    let forced = false;
    serve({
      "/api/update": () => json(ready),
      "/api/update/install": () => (forced ? json({ closing: true }) : json({ detail: "A dubbing job is running or waiting. It is paused and continues after the update." }, 409)),
    });
    render(<UpdateBanner enabled />);
    fireEvent.click(await screen.findByRole("button", { name: "Install now" }));
    const anyway = await screen.findByRole("button", { name: "Install anyway" });
    forced = true;
    fireEvent.click(anyway);
    expect(await screen.findByText(/Closing so the update/)).toBeTruthy();
  });

  it("stays away for a version the user said 'later' to", async () => {
    serve({ "/api/update": () => json(base) });
    const { container } = render(<UpdateBanner enabled />);
    fireEvent.click(await screen.findByRole("button", { name: "Later" }));
    expect(container.textContent).toBe("");
    cleanup();
    serve({ "/api/update": () => json(base) });
    const again = render(<UpdateBanner enabled />);
    await waitFor(() => expect(localStorage.getItem("localdub.update.dismissed")).toBe("0.6.0"));
    expect(again.container.textContent).toBe("");
  });

  it("shows a failed download with its reason and lets the user try again", async () => {
    serve({ "/api/update": () => json({ ...base, download: { status: "error", done: 0, total: 0, error: "Download failed: offline" } }) });
    render(<UpdateBanner enabled />);
    expect(await screen.findByText(/Download failed: offline/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Download and update/ })).toBeTruthy();
  });
});
