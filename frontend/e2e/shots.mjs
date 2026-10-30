// Screenshots of the main screens in light and dark. Usage: node e2e/shots.mjs <project id> [out dir]
import { mkdirSync } from "node:fs";
import { BASE, closeBrowser, launch } from "./browser.mjs";

setTimeout(() => process.exit(2), 120000).unref();
const pid = process.argv[2] ?? "2";
const out = process.argv[3] ?? "../work/shots";
mkdirSync(out, { recursive: true });
const { browser, page } = await launch({ width: 1360, height: 900 });
page.setDefaultTimeout(20000);
for (const scheme of ["light", "dark"]) {
  await page.emulateMedia({ colorScheme: scheme });
  await page.goto(`${BASE}/`);
  await page.waitForSelector("text=Dub a video into Slovak");
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${out}/ui_${scheme}_new.png` });
  await page.goto(`${BASE}/#/project/${pid}`);
  await page.waitForSelector('[data-testid="timeline"]');
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${out}/ui_${scheme}_project.png`, fullPage: true });
  await page.goto(`${BASE}/#/models`);
  await page.waitForSelector("text=AI models");
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${out}/ui_${scheme}_models.png`, fullPage: true });
}
await closeBrowser(browser);
console.log("shots written to", out);
process.exit(0);
