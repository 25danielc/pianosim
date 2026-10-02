// QA: for every note, find the first video frame where the key is >50% down
// (using the renderer's own key-state function) and compare with the frame
// that contains the MIDI onset.
import { chromium } from 'playwright';
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path';
const root = path.dirname(new URL(import.meta.url).pathname);
const server = http.createServer((req, res) => { fs.readFile(path.join(root, decodeURIComponent(req.url.split('?')[0])), (e, b) => { if (e) { res.writeHead(404); return res.end(); } res.writeHead(200, { 'Content-Type': req.url.endsWith('.js') ? 'text/javascript' : req.url.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); res.end(b); }); }).listen(0);
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto(`http://localhost:${server.address().port}/index.html`);
await page.waitForFunction(() => window.READY === true);
const r = await page.evaluate(() => {
  const FPS = window.FPS, lead = window.__lead;
  const errs = [];
  for (const n of window.__notes) {
    const onsetFrame = Math.ceil((n.on + lead) * FPS - 1e-9);   // first frame at/after the onset
    let f = Math.floor((n.on + lead) * FPS) - 3, found = null;
    const thr = 0.5 * (0.55 + 0.45 * n.v / 120);
    // the frame where the key crosses half its press depth on the way down
    for (; f <= onsetFrame + 3; f++) if (window.__keyDepth(n.p, f / FPS) > thr && window.__keyDepth(n.p, (f - 1) / FPS) <= thr) { found = f; break; }
    errs.push(found === null ? 99 : found - onsetFrame);
  }
  const hist = {}; for (const e of errs) hist[e] = (hist[e] || 0) + 1;
  return { n: errs.length, hist, maxAbs: Math.max(...errs.map(Math.abs)) };
});
console.log(JSON.stringify(r));
await browser.close(); server.close();
