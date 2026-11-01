// The update banner with a pretend newer release. Usage: node e2e/update.mjs [out dir]
import { mkdirSync } from "node:fs";
import { BASE, closeBrowser, launch } from "./browser.mjs";

setTimeout(() => process.exit(2), 90000).unref();
const out = process.argv[2] ?? "../work/shots";
mkdirSync(out, { recursive: true });
const { browser, page } = await launch({ width: 1200, height: 800 });
page.setDefaultTimeout(20000);
await page.addInitScript(() => localStorage.setItem("localdub.lang", "en"));
let state = {
  current: "0.5.2", available: true, version: "0.6.0", notes: "x", page: "https://github.com/spekulanter/localdub-studio/releases", asset: "a", size: 14346103, error: null,
  download: { status: "idle", done: 0, total: 0, error: null },
};
await page.route("**/api/update**", (route) => {
  const url = route.request().url();
  if (url.includes("/download")) state = { ...state, download: { status: "ready", done: 1, total: 1, error: null } };
  return route.fulfill({ json: state });
});
await page.goto(`${BASE}/`);
await page.waitForSelector("[data-testid=update-banner]");
await page.screenshot({ path: `${out}/update_offer.png` });
await page.click("text=Download and update");
await page.waitForSelector("text=Install now");
await page.screenshot({ path: `${out}/update_ready.png` });
await closeBrowser(browser);
process.exit(0);
