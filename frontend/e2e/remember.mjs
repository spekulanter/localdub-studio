// New dub keeps what was chosen when the user visits another page, and after a reload. Usage: node e2e/remember.mjs
import { BASE, closeBrowser, launch } from "./browser.mjs";

setTimeout(() => process.exit(2), 90000).unref();
const { browser, page } = await launch({ width: 1200, height: 1000 });
page.setDefaultTimeout(20000);
await page.addInitScript(() => {
  if (!sessionStorage.getItem("seen")) { localStorage.clear(); sessionStorage.setItem("seen", "1"); }
  localStorage.setItem("localdub.lang", "en");
});
await page.goto(`${BASE}/`);
await page.waitForSelector("#slovak-voice");
const voice = () => page.inputValue("#slovak-voice");
const radios = () => page.locator('input[name="original_audio"]').evaluateAll((els) => els.map((e) => e.checked));
console.log("first start: voice", await voice(), "| radios", await radios());
await page.selectOption("#slovak-voice", "F2");
await page.click("text=Mute completely");
await page.locator("aside").getByText("AI models", { exact: true }).click();
await page.waitForSelector("h2:has-text('AI models')");
await page.locator("aside").getByText("New dub", { exact: true }).click();
await page.waitForSelector("#slovak-voice");
console.log("after visiting AI models: voice", await voice(), "| radios", await radios());
await page.reload();
await page.waitForSelector("#slovak-voice");
console.log("after reload: voice", await voice(), "| radios", await radios());
await closeBrowser(browser);
process.exit(0);
