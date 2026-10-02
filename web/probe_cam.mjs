// debug: render stills from arbitrary cameras: node probe_cam.mjs t "px,py,pz|tx,ty,tz|fov" ...
import { chromium } from 'playwright';
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path';
const root = path.dirname(new URL(import.meta.url).pathname);
const server = http.createServer((req, res) => { fs.readFile(path.join(root, decodeURIComponent(req.url.split('?')[0])), (e, b) => { if (e) { res.writeHead(404); return res.end(); } res.writeHead(200, { 'Content-Type': req.url.endsWith('.js') ? 'text/javascript' : req.url.endsWith('.html') ? 'text/html' : 'application/octet-stream' }); res.end(b); }); }).listen(0);
const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
page.on('pageerror', e => console.log('[pageerror]', e.message));
await page.goto(`http://localhost:${server.address().port}/index.html${process.env.HASH||""}`);
await page.waitForFunction(() => window.READY === true);
const [t, ...cams] = process.argv.slice(2);
fs.mkdirSync(path.join(root, '../out/debug'), { recursive: true });
let i = 0;
for (const c of cams) {
  const [p, tg, fov] = c.split('|');
  await page.evaluate(([t, p, tg, fov]) => { if (window.location.hash==="#nohaze") window.__dbg.hazeMat.uniforms.strength.value = 0; if (window.location.hash.startsWith("#dbg")) { window.__dbg.compMat.uniforms.sceneMul.value = 0; window.__dbg.hazeMat.uniforms.dbg.value = Number(window.location.hash.slice(4)); } if (window.location.hash==="#hazeonly") window.__dbg.compMat.uniforms.sceneMul.value = 0; window.__camOverride = [0, p.split(',').map(Number), tg.split(',').map(Number), Number(fov)]; return window.seek(t); }, [Number(t), p, tg, fov]);
  const f = path.join(root, `../out/debug/cam_${i++}.png`);
  fs.writeFileSync(f, await page.screenshot({ type: 'png' })); console.log(f);
}
await browser.close(); server.close();
