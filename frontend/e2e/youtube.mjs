// Real-browser click-through of the YouTube import: tab -> link -> check -> start -> progress -> done.
// Needs a running server (BASE_URL) with the YouTube tools installed, models present, and internet.
// Usage: node e2e/youtube.mjs [url] [screenshot dir]
import { mkdirSync } from "node:fs";
import { api, BASE, closeBrowser, launch } from "./browser.mjs";

setTimeout(() => {
  console.log("TIMEOUT: did not finish in 240 s");
  process.exit(2);
}, 240000).unref();

const url = process.argv[2] ?? "https://www.youtube.com/watch?v=HOfdboHvshg"; // Blender's Sintel trailer (CC-BY)
const shots = process.argv[3] ?? "../work/shots";
mkdirSync(shots, { recursive: true });
const { browser, page } = await launch({ width: 1280, height: 1100 });
page.setDefaultTimeout(60000);
const failures = [];
const check = (ok, what) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${what}`);
  if (!ok) failures.push(what);
};

try {
  await page.goto(`${BASE}/`);
  await page.getByRole("tab", { name: "YouTube link" }).click();
  await page.getByLabel("YouTube link").fill(url);
  const start = page.getByRole("button", { name: /Download and start dubbing/ });
  check(await start.isDisabled(), "start is disabled until the link was checked");
  await page.getByRole("button", { name: "Check link" }).click();
  await page.getByTestId("youtube-card").waitFor();
  const title = await page.getByTestId("youtube-card").innerText();
  check(/Sintel/i.test(title), `the card shows the video: ${title.split("\n")[0]}`);
  const thumb = await page
    .getByTestId("youtube-card")
    .locator("img")
    .evaluate(
      (i) =>
        i.complete
          ? i.naturalWidth > 0
          : new Promise((resolve) => {
              i.onload = () => resolve(true);
              i.onerror = () => resolve(false);
              setTimeout(() => resolve(false), 10000);
            }),
    )
    .catch(() => false);
  check(thumb, "the thumbnail loaded");
  check(await start.isEnabled(), "start is enabled after the check");
  await page.screenshot({ path: `${shots}/youtube_form.png` });

  await start.click();
  await page.waitForURL(/#\/project\/\d+/);
  const pid = Number(page.url().match(/project\/(\d+)/)[1]);
  console.log(`project ${pid} created`);
  await page.getByRole("progressbar").first().waitFor();
  let sawDownload = false;
  for (let i = 0; i < 120; i++) {
    const label = await page.getByLabel("Job progress").locator("h3").first().innerText().catch(() => "");
    if (/Downloading from YouTube/.test(label)) sawDownload = true;
    if (sawDownload && i === 0) await page.screenshot({ path: `${shots}/youtube_progress.png` });
    const p = await api(`/api/projects/${pid}`);
    if (p.latest_job && !["queued", "running"].includes(p.latest_job.status)) break;
    await page.waitForTimeout(1000);
  }
  const proj = await api(`/api/projects/${pid}`);
  check(proj.latest_job.status === "done", `the job finished: ${proj.latest_job.status} ${proj.latest_job.error ?? ""}`);
  check(sawDownload, "the page showed the download step");
  check(proj.source_url?.includes("HOfdboHvshg") === true && proj.has_input && proj.has_output, "link stored, video downloaded, dub exported");
  await page.waitForSelector('[data-testid="timeline"]');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${shots}/youtube_done.png`, fullPage: true });
  const link = await page.getByRole("link", { name: "YouTube" }).first().getAttribute("href");
  check(link?.includes("HOfdboHvshg") === true, "the project links back to the YouTube video");
  const videoSrc = await page.locator("video").first().getAttribute("src");
  check(Boolean(videoSrc), "the preview player has a video");
} catch (e) {
  failures.push(String(e));
  console.log("ERROR", e);
  await page.screenshot({ path: `${shots}/youtube_error.png` }).catch(() => undefined);
} finally {
  await closeBrowser(browser);
}
console.log(failures.length ? `\n${failures.length} FAILED` : "\nALL PASSED");
process.exit(failures.length ? 1 : 0);
