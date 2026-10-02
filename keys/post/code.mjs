// Render the code panel overlay: transparent 1920x1080 PNGs, one per 60 fps frame.
import { chromium } from '/Users/danielchen/projects/pianosim/web/node_modules/playwright/index.mjs';
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path';
const dir = path.dirname(new URL(import.meta.url).pathname);
const N = +(process.argv[2] || 204);
const server = http.createServer((q, r) => fs.readFile(path.join(dir, decodeURIComponent(q.url.split('?')[0])), (e, b) => {
  if (e) { r.writeHead(404); return r.end(); }
  r.writeHead(200, { 'Content-Type': q.url.endsWith('.html') ? 'text/html' : q.url.endsWith('.json') ? 'application/json' : 'font/ttf' }); r.end(b); })).listen(0);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto(`http://localhost:${server.address().port}/code.html`);
await page.waitForFunction(() => window.READY === true);
fs.mkdirSync(path.join(dir, 'code_frames'), { recursive: true });
for (let f = 0; f < N; f++) {
  await page.evaluate(([t, f]) => window.render(t, f), [f / 60, f]);
  await page.screenshot({ path: path.join(dir, 'code_frames', `c_${String(f).padStart(5, '0')}.png`), omitBackground: true });
}
await browser.close(); server.close();
console.log('code frames', N);
