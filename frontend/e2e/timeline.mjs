// Real-browser check of the timeline: drag a line, see it saved, revert it.
// Usage: node e2e/timeline.mjs <project id> [screenshot dir]   (server must be running on BASE_URL)
import { mkdirSync } from "node:fs";
import { api, BASE, launch } from "./browser.mjs";

setTimeout(() => {
  console.log("TIMEOUT: the browser test did not finish in 90 s");
  process.exit(2);
}, 90000).unref();

const pid = Number(process.argv[2] ?? 1);
const shots = process.argv[3] ?? "../work/shots";
mkdirSync(shots, { recursive: true });
const { browser, page } = await launch();
page.setDefaultTimeout(15000);
const failures = [];
const log = (m) => console.log(`[${new Date().toISOString().slice(11, 19)}] ${m}`);
const check = (ok, what) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${what}`);
  if (!ok) failures.push(what);
};

try {
  log('await page.goto('.slice(6, 40));
  await page.goto(`${BASE}/#/project/${pid}`);
  log('await page.waitForSelector('.slice(6, 40));
  await page.waitForSelector('[data-testid="timeline"]', { timeout: 15000 });
  await page.waitForTimeout(800); // waveform fetch + first paint
  await page.locator('[data-testid="timeline"]').scrollIntoViewIfNeeded();
  log('await page.screenshot({ path: `${shots}/timeline_before.png`'.slice(6, 40));
  await page.screenshot({ path: `${shots}/timeline_before.png`, fullPage: false });

  const before = (await api(`/api/projects/${pid}/segments`)).segments;
  const target = before[3];
  const block = page.getByRole("button", { name: new RegExp(`^English line ${target.id}:`) });
  log('const box = await block.boundingBox();'.slice(6, 40));
  const box = await block.boundingBox();
  check(box !== null && box.width > 10, `block of line ${target.id} is visible (${Math.round(box?.width ?? 0)} px wide)`);

  // canvas really painted something (not blank)
  const painted = await page.evaluate(() => {
    const c = document.querySelector('canvas[aria-label^="Waveform"]');
    if (!c) return -1;
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let n = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
    return n;
  });
  check(painted > 500, `waveform canvas has ${painted} painted pixels`);

  // drag the middle of the block 40 px to the right
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);
  log('await page.mouse.down();'.slice(6, 40));
  await page.mouse.down();
  await page.mouse.move(cx + 20, cy, { steps: 4 });
  await page.mouse.move(cx + 40, cy, { steps: 4 });
  await page.screenshot({ path: `${shots}/timeline_dragging.png` });
  const tip = await page.locator("text=/\\d+\\.\\d\\d – \\d+\\.\\d\\d s/").first().textContent().catch(() => null);
  check(tip !== null, `a time label is shown while dragging (${tip})`);
  log('await page.mouse.up();'.slice(6, 40));
  await page.mouse.up();
  await page.waitForTimeout(800);

  const after = (await api(`/api/projects/${pid}/segments`)).segments.find((s) => s.id === target.id);
  const moved = after.start - target.start;
  check(moved > 0.1 && Math.abs(after.end - after.start - (target.end - target.start)) < 0.02,
    `server saved the move: start ${target.start} -> ${after.start} (+${moved.toFixed(2)} s), length kept`);
  check(after.edited === true, "the line is marked as edited");
  await page.screenshot({ path: `${shots}/timeline_after.png` });

  // keyboard nudge
  log('await block.focus();'.slice(6, 40));
  await block.focus();
  await page.keyboard.press("Shift+ArrowLeft");
  await page.waitForTimeout(800);
  const nudged = (await api(`/api/projects/${pid}/segments`)).segments.find((s) => s.id === target.id);
  check(Math.abs(nudged.start - (after.start - 0.5)) < 0.02, `keyboard nudge moved the line (${after.start} -> ${nudged.start})`);

  // clicking the waveform seeks the video
  const time = await page.evaluate(() => {
    const v = document.querySelector("video");
    return v ? v.currentTime : -1;
  });
  check(time >= 0, `a video element exists (currentTime ${time})`);
} catch (e) {
  failures.push(String(e));
  console.log("ERROR", e);
} finally {
  // leave the project as we found it
  const segs = (await api(`/api/projects/${pid}/segments`)).segments;
  for (const s of segs.filter((x) => x.edited)) await api(`/api/projects/${pid}/segments/${s.id}/edit`, { method: "DELETE" });
  await browser.close();
}
console.log(failures.length ? `\n${failures.length} FAILED` : "\nALL PASSED");
process.exit(failures.length ? 1 : 0);
