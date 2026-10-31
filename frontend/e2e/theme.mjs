// Dark mode switch and the new source languages in real Edge. Usage: node e2e/theme.mjs [out dir]
import { mkdirSync } from "node:fs";
import { BASE, closeBrowser, launch } from "./browser.mjs";

setTimeout(() => process.exit(2), 100000).unref();
const out = process.argv[2] ?? "../work/shots";
mkdirSync(out, { recursive: true });
const { browser, page } = await launch({ width: 1360, height: 900 });
page.setDefaultTimeout(20000);
await page.emulateMedia({ colorScheme: "light" });
await page.goto(`${BASE}/`);
await page.waitForSelector("aside select");
const selects = page.locator("aside select");
await selects.nth(1).selectOption("dark");
await page.waitForTimeout(400);
console.log("theme attr:", await page.evaluate(() => document.documentElement.dataset.theme));
console.log("languages:", (await page.locator("main select").first().innerText()).replace(/\n/g, ", "));
await page.screenshot({ path: `${out}/ui_dark_toggle_new.png`, fullPage: true });
await page.reload();
console.log("after reload:", await page.evaluate(() => document.documentElement.dataset.theme));
await selects.nth(1).selectOption("light");
console.log("light:", await page.evaluate(() => document.documentElement.dataset.theme));
await selects.nth(1).selectOption("system");
console.log("system (emulated light):", await page.evaluate(() => document.documentElement.dataset.theme));
await closeBrowser(browser);
process.exit(0);
