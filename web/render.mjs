// Deterministic frame renderer: serves this folder, opens index.html in
// headless Chrome, calls window.seek(t) per frame and pipes PNGs to FFmpeg.
//
//   node render.mjs --at 1.0,46.82          stills -> ../out/stills/
//   node render.mjs --from 0 --to 10 --out ../out/test.mp4 [--audio ../build/mix.wav]
import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]);
  return acc;
}, []));
const root = path.dirname(new URL(import.meta.url).pathname);
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.ttf': 'font/ttf' };
const server = http.createServer((req, res) => {
  const f = path.join(root, decodeURIComponent(req.url.split('?')[0]));
  fs.readFile(f, (err, buf) => {
    if (err) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(f)] || 'application/octet-stream' });
    res.end(buf);
  });
}).listen(0);
const port = server.address().port;

const browser = await chromium.launch({
  channel: 'chrome', headless: true,
  args: ['--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist', '--enable-unsafe-swiftshader=false', '--force-color-profile=srgb'],
});
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') console.log('[page]', m.text()); });
page.on('pageerror', e => console.log('[pageerror]', e.message));
await page.goto(`http://localhost:${port}/index.html`);
await page.waitForFunction(() => window.READY === true, null, { timeout: 120000 });
const FPS = await page.evaluate(() => window.FPS);
const DURATION = await page.evaluate(() => window.DURATION);
console.log('renderer:', await page.evaluate(() => {
  const gl = document.getElementById('c').getContext('webgl2');
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'unknown';
}));

async function shot(t) {
  // headless Chrome occasionally stalls a capture; seek again and retry
  for (let attempt = 1; ; attempt++) {
    try {
      await page.evaluate(t => window.seek(t), t);
      return await page.screenshot({ type: 'png', clip: { x: 0, y: 0, width: 1920, height: 1080 }, timeout: 60000 });
    } catch (e) {
      if (attempt >= 4) throw e;
      console.log(`capture at t=${t.toFixed(3)} failed (${e.name}), retry ${attempt}`);
    }
  }
}

if (args.at) {
  const dir = path.resolve(root, args.dir || '../out/stills');
  fs.mkdirSync(dir, { recursive: true });
  for (const s of String(args.at).split(',')) {
    const t = parseFloat(s);
    const t0 = Date.now();
    const png = await shot(t);
    const f = path.join(dir, `${args.prefix || 'still'}_${t.toFixed(2)}.png`);
    fs.writeFileSync(f, png);
    console.log(f, `${Date.now() - t0} ms`);
  }
} else {
  const from = parseFloat(args.from ?? 0), to = parseFloat(args.to ?? DURATION);
  const f0 = Math.round(from * FPS), f1 = Math.round(to * FPS);
  const out = path.resolve(root, args.out || '../out/render.mp4');
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const ff = ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'png', '-i', '-'];
  if (args.audio) ff.push('-ss', String(from), '-t', String(to - from), '-i', path.resolve(root, args.audio));
  ff.push('-map', '0:v');
  if (args.audio) ff.push('-map', '1:a', '-c:a', 'aac', '-b:a', '320k', '-ar', '48000');
  ff.push('-c:v', 'libx264', '-preset', 'slow', '-crf', String(args.crf || 14), '-pix_fmt', 'yuv420p',
    '-profile:v', 'high', '-tune', 'film', '-x264-params', 'keyint=120:min-keyint=60',
    '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
    '-r', String(FPS), '-movflags', '+faststart', out);
  const enc = spawn('ffmpeg', ff, { stdio: ['pipe', 'inherit', 'inherit'] });
  const t0 = Date.now();
  for (let f = f0; f < f1; f++) {
    const png = await shot(f / FPS);
    if (!enc.stdin.write(png)) await new Promise(r => enc.stdin.once('drain', r));
    if ((f - f0) % 120 === 0) {
      const el = (Date.now() - t0) / 1000, done = f - f0 + 1;
      console.log(`frame ${f}/${f1}  ${(done / el).toFixed(1)} fps  eta ${((f1 - f) * el / done / 60).toFixed(1)} min`);
    }
  }
  enc.stdin.end();
  await new Promise(r => enc.on('close', r));
  console.log('wrote', out, `${((Date.now() - t0) / 1000).toFixed(1)} s`);
}
await browser.close();
server.close();
