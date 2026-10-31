// The AI models library in real Edge: screenshots, details, update check. Usage: node e2e/models.mjs [out dir]
import { mkdirSync } from "node:fs";
import { BASE, closeBrowser, launch } from "./browser.mjs";

setTimeout(() => process.exit(2), 120000).unref();
const out = process.argv[2] ?? "../work/shots";
mkdirSync(out, { recursive: true });
const { browser, page } = await launch({ width: 1360, height: 900 });
page.setDefaultTimeout(20000);
for (const scheme of ["light", "dark"]) {
  await page.emulateMedia({ colorScheme: scheme });
  await page.goto(`${BASE}/#/models`);
  await page.waitForSelector("text=Parakeet");
  if (scheme === "light") {
    await page.locator('[data-testid="model-translategemma-12b"] summary').click();
    await page.getByRole("button", { name: "Check for updates" }).click();
    const note = page.getByText(/installed models? checked/);
    await note.waitFor({ timeout: 60000 });
    console.log("update check:", await note.innerText());
  }
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${out}/ui_${scheme}_models_library.png`, fullPage: true });
}
await page.goto(`${BASE}/`);
await page.waitForSelector("text=Speech recognition");
console.log("asr options:", await page.locator("select").filter({ hasText: "Whisper" }).first().innerText());
await closeBrowser(browser);
process.exit(0);
