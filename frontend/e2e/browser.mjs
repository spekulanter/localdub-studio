// Shared helper: drive the installed Microsoft Edge with playwright-core (no browser download).
import { chromium } from "playwright-core";

export const BASE = process.env.BASE_URL ?? "http://127.0.0.1:8767";

export async function launch(viewport = { width: 1360, height: 1000 }) {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const page = await context.newPage();
  return { browser, page };
}

export async function api(path, init) {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok && res.status !== 204) throw new Error(`${init?.method ?? "GET"} ${path} -> ${res.status}`);
  return res.status === 204 ? null : res.json();
}
