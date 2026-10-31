// Slovak UI, voice sample and cancelling a download in real Edge. Usage: node e2e/i18n.mjs [out dir]
import { mkdirSync } from "node:fs";
import { BASE, closeBrowser, launch } from "./browser.mjs";

setTimeout(() => process.exit(2), 150000).unref();
const out = process.argv[2] ?? "../work/shots";
mkdirSync(out, { recursive: true });
const { browser, page } = await launch({ width: 1360, height: 900 });
page.setDefaultTimeout(20000);
await page.addInitScript(() => { if (!window.localStorage.getItem("localdub.lang")) window.localStorage.setItem("localdub.lang", "en"); });
await page.goto(`${BASE}/`);
await page.waitForSelector("text=Dub a video into Slovak");
await page.locator("aside select").selectOption("sk");
await page.waitForSelector("text=Nadabovať video do slovenčiny");
await page.waitForTimeout(600);
await page.screenshot({ path: `${out}/ui_sk_new.png`, fullPage: true });
// voice sample: the request must succeed and audio must start
const sample = page.waitForResponse((r) => r.url().includes("/api/voices/") && r.url().endsWith("/sample"));
await page.getByRole("button", { name: "▶ Vypočuť" }).click();
const r = await sample;
console.log("sample:", r.status(), r.headers()["content-type"]);
await page.waitForSelector("text=Zastaviť");
await page.getByRole("button", { name: "Zastaviť" }).click();

await page.goto(`${BASE}/#/models`);
await page.getByRole("heading", { name: "Rozpoznávanie reči" }).waitFor();
await page.waitForTimeout(500);
await page.screenshot({ path: `${out}/ui_sk_models.png`, fullPage: true });
// cancel a real download (Whisper small.en, 486 MB) a moment after it started
const card = page.getByTestId("model-whisper-small-en");
await card.getByRole("button", { name: /^Stiahnuť \(/ }).click();
await card.getByRole("progressbar").waitFor();
await page.waitForTimeout(2500);
console.log("progress:", await card.getByRole("progressbar").getAttribute("aria-valuenow"), "%");
await card.getByRole("button", { name: "Zrušiť" }).click();
await card.getByText("Sťahovanie zrušené").waitFor({ timeout: 30000 });
console.log("cancelled ok; install button back:", await card.getByRole("button", { name: /^Stiahnuť \(/ }).isVisible());
await page.locator("aside select").selectOption("en");
await closeBrowser(browser);
process.exit(0);
