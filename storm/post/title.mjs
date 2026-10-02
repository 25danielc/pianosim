// Render the title overlay to transparent PNGs (one per aspect).
import { chromium } from '/Users/danielchen/projects/pianosim/web/node_modules/playwright/index.mjs';
import path from 'node:path';
const dir = path.dirname(new URL(import.meta.url).pathname);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
for (const [name, w, h, x, y, size, wrap] of [['title_169', 1920, 1080, 96, 84, 38, 0], ['title_45', 1080, 1350, 72, 120, 40, 1]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  await page.goto(`file://${dir}/title.html?w=${w}&h=${h}&x=${x}&y=${y}&size=${size}&wrap=${wrap}`);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${dir}/${name}.png`, omitBackground: true });
  console.log(name);
}
await browser.close();
