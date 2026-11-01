// Screenshots of the New dub page: simple view and with "Advanced options" open. Usage: node e2e/simple.mjs [out dir]
import { mkdirSync } from "node:fs";
import { BASE, closeBrowser, launch } from "./browser.mjs";

setTimeout(() => process.exit(2), 90000).unref();
const out = process.argv[2] ?? "../work/shots";
mkdirSync(out, { recursive: true });
const { browser, page } = await launch({ width: 1200, height: 1100 });
page.setDefaultTimeout(20000);
await page.addInitScript(() => localStorage.setItem("localdub.lang", "en"));
await page.goto(`${BASE}/`);
await page.waitForSelector("text=Advanced options");
await page.screenshot({ path: `${out}/simple_closed.png`, fullPage: true });
await page.click("text=Advanced options");
await page.waitForTimeout(300);
await page.screenshot({ path: `${out}/simple_open.png`, fullPage: true });
await closeBrowser(browser);
process.exit(0);
