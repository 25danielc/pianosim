import { chromium } from '/Users/danielchen/projects/pianosim/web/node_modules/playwright/index.mjs';
import path from 'node:path';
const dir = path.dirname(new URL(import.meta.url).pathname);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
for (const [name, w, h, y] of [['end_169', 1920, 1080, 110], ['end_45', 1080, 1350, 150]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  await page.goto(`file://${dir}/end.html?w=${w}&h=${h}&y=${y}`);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${dir}/${name}.png`, omitBackground: true });
}
await browser.close();
