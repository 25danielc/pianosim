// Moonlight — III. Presto agitato
// Deterministic renderer: every frame is a pure function of t (window.seek).
// The note list comes from build/performance.mid via notes.json, the same
// MIDI the audio was synthesized from.
import * as THREE from 'three';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

const W = 1920, H = 1080, FPS = 60;
const LEAD = 0.25;                 // video t of MIDI t = 0
const DURATION = 91.0;
const C = {
  void: 0x07090F, midnight: 0x0E1A2E, moon: 0xCFE0FF,
  ivory: 0xF2EDE3, ebony: 0x0B0B0D, glow: 0x8FB4FF,
};

// ---------------------------------------------------------------- helpers
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
function mulberry32(a) {
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------------------------------------------------------- renderer
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(1);
renderer.setSize(W, H, false);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.shadowMap.autoUpdate = true;
renderer.toneMapping = THREE.NoToneMapping;          // tonemapped in final pass
renderer.outputColorSpace = THREE.LinearSRGBColorSpace;

const scene = new THREE.Scene();
scene.background = new THREE.Color(C.void).convertSRGBToLinear().multiplyScalar(0.6);
const camera = new THREE.PerspectiveCamera(30, W / H, 0.05, 60);

const hazeHidden = [];             // excluded from the light depth pass
const depthHidden = [];            // excluded from every depth pre-pass (glows, motes, window)

// ---------------------------------------------------------------- data
const data = await (await fetch('notes.json')).json();
const NOTES = data.notes;          // {p,on,off,v}
const PEDAL = data.pedal;          // {on,off}

// ---------------------------------------------------------------- keyboard geometry
const WK = 0.0235, WL = 0.150, WH = 0.022;            // white key width/length/height
const BW = 0.0137, BL = 0.095, BH = 0.0125;           // black key width/length/rise
const GAP = 0.0010;
const KEY_BASE_Y = 0.700;                              // keybed height
const PIVOT_Z = -WL;                                   // keys pivot at their back end
const MAX_DIP = THREE.MathUtils.degToRad(3.6);
const BLACK_PC = new Set([1, 3, 6, 8, 10]);
const isBlack = p => BLACK_PC.has(((p % 12) + 12) % 12);
const WHITE_IDX = { 0: 0, 2: 1, 4: 2, 5: 3, 7: 4, 9: 5, 11: 6 };
const absWhite = p => Math.floor(p / 12) * 7 + WHITE_IDX[((p % 12) + 12) % 12];
const NWHITE = 52;
const X0 = -NWHITE * WK / 2;
const whiteX0 = p => X0 + (absWhite(p) - absWhite(21)) * WK;
function blackCenter(p) {
  const pc = ((p % 12) + 12) % 12;
  if (pc === 1 || pc === 3) {            // C# D#: C–E group split into 5 slots
    const cx = whiteX0(p - pc), s = 3 * WK / 5;
    return cx + (pc === 1 ? 1.5 : 3.5) * s;
  }
  const fx = whiteX0(p - (pc - 5)), s = 4 * WK / 7;   // F# G# A#: F–B group, 7 slots
  return fx + ({ 6: 1.5, 8: 3.5, 10: 5.5 })[pc] * s;
}
const keyCenterX = p => isBlack(p) ? blackCenter(p) : whiteX0(p) + WK / 2;

function whiteKeyGeometry(p) {
  const x0 = whiteX0(p) + GAP / 2, x1 = whiteX0(p) + WK - GAP / 2;
  const hasL = p - 1 >= 21 && isBlack(p - 1), hasR = p + 1 <= 108 && isBlack(p + 1);
  const bl = hasL ? blackCenter(p - 1) + BW / 2 + GAP * 0.8 : x0;
  const br = hasR ? blackCenter(p + 1) - BW / 2 - GAP * 0.8 : x1;
  const zf = BL + 0.006;                                // where the full-width front starts
  const s = new THREE.Shape();
  s.moveTo(bl, 0.001); s.lineTo(br, 0.001); s.lineTo(br, zf); s.lineTo(x1, zf);
  s.lineTo(x1, WL); s.lineTo(x0, WL); s.lineTo(x0, zf); s.lineTo(bl, zf); s.closePath();
  const g = new THREE.ExtrudeGeometry(s, { depth: WH - 0.0016, bevelEnabled: true, bevelThickness: 0.0008, bevelSize: 0.0005, bevelSegments: 2, curveSegments: 1 });
  g.rotateX(Math.PI / 2);            // shape y -> world z, extrude -> -y
  g.translate(0, WH - 0.0008, 0);
  return g;
}
function blackKeyGeometry(p) {
  const cx = blackCenter(p), h = WH + BH;
  const s = new THREE.Shape();
  s.moveTo(cx - BW / 2, 0); s.lineTo(cx + BW / 2, 0);
  s.lineTo(cx + BW * 0.40, h); s.lineTo(cx - BW * 0.40, h); s.closePath();
  const g = new THREE.ExtrudeGeometry(s, { depth: BL - 0.002, bevelEnabled: true, bevelThickness: 0.001, bevelSize: 0.0006, bevelSegments: 2, curveSegments: 1 });
  // extrude runs along +z from the pivot (back) to the front
  g.translate(0, 0, 0.001);
  return g;
}

const keyboard = new THREE.Group();
keyboard.position.set(0, KEY_BASE_Y, 0);
scene.add(keyboard);
const keys = [];                    // index p-21
// ACES pushes saturated blues further, so the emissive is pre-softened toward
// white to land on #8FB4FF on screen
const glowColor = new THREE.Color(C.glow).convertSRGBToLinear().lerp(new THREE.Color(1, 1, 1), 0.32);
for (let p = 21; p <= 108; p++) {
  const black = isBlack(p);
  const mat = new THREE.MeshPhysicalMaterial(black ? {
    color: new THREE.Color(C.ebony), roughness: 0.32, clearcoat: 0.8, clearcoatRoughness: 0.18,
    emissive: glowColor, emissiveIntensity: 0,
  } : {
    color: new THREE.Color(C.ivory), roughness: 0.42, clearcoat: 0.35, clearcoatRoughness: 0.25,
    sheen: 0.0, emissive: glowColor, emissiveIntensity: 0,
  });
  const mesh = new THREE.Mesh(black ? blackKeyGeometry(p) : whiteKeyGeometry(p), mat);
  mesh.castShadow = true; mesh.receiveShadow = true;
  const pivot = new THREE.Group();
  pivot.position.set(0, 0, PIVOT_Z);
  pivot.add(mesh);
  keyboard.add(pivot);
  keys.push({ p, black, pivot, mat, x: keyCenterX(p), notes: [] });
}
for (const n of NOTES) keys[n.p - 21].notes.push(n);

// ---------------------------------------------------------------- key state (pure function of music time)
const PRESS_T = 0.018;   // key travel before the onset: full depth on the onset frame
const RELEASE_T = 0.065;
function pedalDownAt(t) {
  for (const s of PEDAL) if (t >= s.on && t < s.off) return s;
  return null;
}
function pedalUpAfter(t) {        // time the pedal lifts, if it is down at t
  const s = pedalDownAt(t);
  return s ? s.off : t;
}
// per-note precompute: when does the sound (and glow) get damped?
for (const k of keys) {
  k.notes.forEach((n, i) => {
    // repeated notes on one key: the finger lets the key rise early enough to
    // be seen between strikes (audio note-off is unchanged)
    const next = k.notes[i + 1];
    const ioi = next ? next.on - n.on : Infinity;
    n.vOff = Math.min(n.off, n.on + 0.55 * ioi);
    n.rel = Math.min(RELEASE_T, 0.35 * ioi);
    n.damp = pedalUpAfter(n.off);          // pedal catches the note -> glow lasts
    n.g0 = 0.30 + 0.70 * Math.pow(n.v / 120, 1.3);
    n.depth = 0.55 + 0.45 * (n.v / 120);
  });
}
function lastNoteIndex(arr, t) {           // last index with on - PRESS_T <= t
  let lo = 0, hi = arr.length - 1, r = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (arr[m].on - PRESS_T <= t) { r = m; lo = m + 1; } else hi = m - 1; }
  return r;
}
function keyState(k, t) {
  let depth = 0, glow = 0;
  const i = lastNoteIndex(k.notes, t);
  for (let j = i; j >= 0 && j >= i - 6; j--) {
    const n = k.notes[j];
    // physical depression
    if (t <= n.vOff + n.rel) {
      const down = smooth(n.on - PRESS_T, n.on, t);
      const up = t > n.vOff ? 1 - smooth(n.vOff, n.vOff + n.rel, t) : 1;
      depth = Math.max(depth, n.depth * down * up);
    }
    // glow: rises with the press, decays like the string while held,
    // lingers under the pedal, dies quickly when damped
    if (t >= n.on - PRESS_T) {
      const age = Math.max(0, t - n.on);
      let g = n.g0 * smooth(n.on - PRESS_T, n.on, t) * (0.5 + 0.5 * Math.exp(-age / 0.55));
      g += 0.25 * n.g0 * Math.exp(-age / 0.09) * (t >= n.on ? 1 : 0);   // attack bloom
      const end = Math.max(n.off, n.damp);
      if (t > n.off && n.damp > n.off) g *= Math.exp(-(Math.min(t, n.damp) - n.off) / 1.4);
      if (t > end) g *= Math.exp(-(t - end) / 0.085);
      glow = Math.max(glow, g);
    }
  }
  return { depth, glow };
}

// ---------------------------------------------------------------- materials
const lacquer = new THREE.MeshPhysicalMaterial({
  color: new THREE.Color(C.ebony), roughness: 0.22, metalness: 0.0,
  clearcoat: 1.0, clearcoatRoughness: 0.04, envMapIntensity: 1.0,
});
const satin = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(C.ebony), roughness: 0.55, clearcoat: 0.3, clearcoatRoughness: 0.4 });
const nickel = new THREE.MeshStandardMaterial({ color: new THREE.Color(0x9AA6B8), metalness: 1.0, roughness: 0.28 });
const feltDark = new THREE.MeshStandardMaterial({ color: new THREE.Color(0x07090F), roughness: 1.0 });

// ---------------------------------------------------------------- piano case
const CASE_FRONT = -0.165, HALF_W = 0.785;
function caseOutline() {
  const s = new THREE.Shape();             // (x, z) top view, z negative = towards the tail
  s.moveTo(-HALF_W, CASE_FRONT);
  s.lineTo(-HALF_W, -2.42);
  s.bezierCurveTo(-HALF_W, -2.66, -0.62, -2.76, -0.40, -2.76);       // rounded tail
  s.bezierCurveTo(-0.10, -2.76, 0.12, -2.55, 0.22, -2.20);           // into the bentside
  s.bezierCurveTo(0.34, -1.75, 0.40, -1.30, 0.62, -1.02);            // S-curve
  s.bezierCurveTo(0.74, -0.86, HALF_W, -0.78, HALF_W, -0.58);
  s.lineTo(HALF_W, CASE_FRONT);
  return s;
}
function offsetOpen(pts, d, sgn) {         // inward offset of an open polyline
  return pts.map((b, i) => {
    const a = pts[Math.max(0, i - 1)], c = pts[Math.min(pts.length - 1, i + 1)];
    const nrm = new THREE.Vector2(-(c.y - a.y), c.x - a.x).normalize().multiplyScalar(d * sgn);
    return new THREE.Vector2(b.x + nrm.x, b.y + nrm.y);
  });
}
function offsetPolygon(pts, d) {           // inward offset of a CCW/CW polyline
  const n = pts.length, out = [];
  let area = 0;
  for (let i = 0; i < n; i++) { const a = pts[i], b = pts[(i + 1) % n]; area += a.x * b.y - b.x * a.y; }
  const sgn = area > 0 ? 1 : -1;
  for (let i = 0; i < n; i++) {
    const a = pts[(i - 1 + n) % n], b = pts[i], c = pts[(i + 1) % n];
    const n1 = new THREE.Vector2(-(b.y - a.y), b.x - a.x).normalize();
    const n2 = new THREE.Vector2(-(c.y - b.y), c.x - b.x).normalize();
    const nm = n1.add(n2).normalize().multiplyScalar(d * sgn);
    out.push(new THREE.Vector2(b.x + nm.x, b.y + nm.y));
  }
  return out;
}
const openPts = caseOutline().getSpacedPoints(220);
const outlinePts = openPts.slice();
const innerPts = offsetPolygon(outlinePts, 0.045);
const RIM_BOT = 0.600, RIM_TOP = 0.985;
{
  let area = 0;
  for (let i = 0; i < outlinePts.length; i++) { const a = outlinePts[i], b = outlinePts[(i + 1) % outlinePts.length]; area += a.x * b.y - b.x * a.y; }
  const rimInner = offsetOpen(openPts, 0.045, area > 0 ? 1 : -1);
  const s = new THREE.Shape([...openPts, ...rimInner.reverse()]);
  const g = new THREE.ExtrudeGeometry(s, { depth: RIM_TOP - RIM_BOT, bevelEnabled: true, bevelThickness: 0.006, bevelSize: 0.006, bevelSegments: 3, curveSegments: 4 });
  g.rotateX(Math.PI / 2);
  g.translate(0, RIM_TOP, 0);
  const rim = new THREE.Mesh(g, lacquer);
  rim.castShadow = true; rim.receiveShadow = true;
  scene.add(rim);
  // case bottom
  const bg = new THREE.ShapeGeometry(new THREE.Shape(outlinePts), 4);
  bg.rotateX(Math.PI / 2); bg.translate(0, RIM_BOT + 0.01, 0);
  const bottom = new THREE.Mesh(bg, satin);
  bottom.material.side = THREE.DoubleSide;
  scene.add(bottom);
}
// interior: graphite plate + faint silver strings, inside palette
{
  const cv = document.createElement('canvas'); cv.width = 2048; cv.height = 2048;
  const g = cv.getContext('2d');
  g.fillStyle = '#07090F'; g.fillRect(0, 0, 2048, 2048);
  // the plate: slightly lighter graphite band shapes
  g.fillStyle = '#0E1A2E'; g.globalAlpha = 0.55; g.fillRect(0, 0, 2048, 260); g.globalAlpha = 1;
  const rnd = mulberry32(11);
  for (let i = 0; i < 230; i++) {
    const x = 40 + i * (1968 / 230) + (rnd() - 0.5) * 1.5;
    g.strokeStyle = `rgba(207,224,255,${0.16 + 0.10 * (i % 3 === 0)})`;
    g.lineWidth = i < 60 ? 3.2 : 1.6;               // wound bass strings are thicker
    g.beginPath(); g.moveTo(x, 160); g.lineTo(x + (i < 60 ? 70 : 0), 2048); g.stroke();
  }
  // tuning pins row
  g.fillStyle = 'rgba(207,224,255,0.25)';
  for (let i = 0; i < 230; i++) { g.beginPath(); g.arc(40 + i * (1968 / 230), 110 + (i % 2) * 34, 4, 0, Math.PI * 2); g.fill(); }
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
  const sg = new THREE.ShapeGeometry(new THREE.Shape(innerPts), 4);
  // UVs: x across width, z from front (v=1 at top of canvas) to tail
  const pos = sg.attributes.position, uv = sg.attributes.uv;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), z = pos.getY(i);
    uv.setXY(i, (x + HALF_W) / (2 * HALF_W), 1 - (CASE_FRONT - 0.03 - z) / 2.6);
  }
  sg.rotateX(Math.PI / 2); sg.translate(0, 0.86, 0);
  const plate = new THREE.Mesh(sg, new THREE.MeshStandardMaterial({ map: tex, metalness: 0.55, roughness: 0.38, side: THREE.DoubleSide }));
  plate.receiveShadow = true;
  scene.add(plate);
}
// lid, hinged along the bass side, propped open
const LID_ANGLE = 0.50;
const lidPivot = new THREE.Group();
{
  const lidPts = outlinePts.map(v => new THREE.Vector2(v.x, v.y)).filter(v => v.y < -0.42);
  const s = new THREE.Shape([new THREE.Vector2(-HALF_W - 0.006, -0.42), ...lidPts, new THREE.Vector2(HALF_W + 0.006, -0.42)]);
  const g = new THREE.ExtrudeGeometry(s, { depth: 0.022, bevelEnabled: true, bevelThickness: 0.004, bevelSize: 0.004, bevelSegments: 3, curveSegments: 4 });
  g.rotateX(Math.PI / 2); g.translate(HALF_W, 0.022, 0);
  const lid = new THREE.Mesh(g, lacquer);
  lid.castShadow = true; lid.receiveShadow = true;
  lidPivot.position.set(-HALF_W, RIM_TOP + 0.004, 0);
  lidPivot.rotation.z = LID_ANGLE;
  lidPivot.add(lid);
  hazeHidden.push(lid);              // grazing: its haze shadow is a paper-thin sheet that aliases
  scene.add(lidPivot);
  // prop stick from the treble rim up to the lid underside
  const base = new THREE.Vector3(0.70, RIM_TOP, -1.05);
  const lx = base.x + HALF_W;                              // lid-local x of the stick contact
  const top = new THREE.Vector3(-HALF_W + lx * Math.cos(LID_ANGLE) * 0.86, RIM_TOP + lx * Math.sin(LID_ANGLE) * 0.86, -1.05);
  const len = base.distanceTo(top);
  const stick = new THREE.Mesh(new THREE.CylinderGeometry(0.009, 0.011, len, 12), satin);
  stick.position.copy(base).lerp(top, 0.5);
  stick.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), top.clone().sub(base).normalize());
  stick.castShadow = true;
  hazeHidden.push(stick);
  scene.add(stick);
}
// cheeks, key slip, fallboard, keybed
function box(w, h, d, mat, x, y, z, r = 0.004) {
  const m = new THREE.Mesh(new RoundedBoxGeometry(w, h, d, 3, r), mat);
  m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true; scene.add(m); return m;
}
const KB_HALF = NWHITE * WK / 2;
for (const sgn of [-1, 1]) {
  const cw = HALF_W - KB_HALF - 0.002;
  box(cw, 0.175, 0.205, lacquer, sgn * (KB_HALF + 0.002 + cw / 2), 0.6875, -0.0625, 0.012);
}
box(2 * KB_HALF + 0.004, 0.090, 0.200, lacquer, 0, 0.645, -0.096, 0.004);          // keybed block
box(2 * HALF_W - 0.09, 0.230, 0.030, lacquer, 0, 0.715, -0.192, 0.004);            // front beam behind the nameboard
box(2 * KB_HALF + 0.01, 0.034, 0.016, lacquer, 0, 0.684, 0.010, 0.004);        // key slip
box(2 * KB_HALF + 0.004, 0.012, 0.18, feltDark, 0, 0.692, -0.075, 0.001);      // keybed
const fallboard = box(2 * KB_HALF + 0.004, 0.105, 0.022, lacquer, 0, 0.770, -0.166, 0.006);
box(2 * KB_HALF + 0.004, 0.012, 0.012, feltDark, 0, 0.700, -0.152, 0.002);     // back rail felt
// key-glow spill on the fallboard: one gaussian per key, additive
const glowArr = new Float32Array(88);
const spillMat = new THREE.ShaderMaterial({
  uniforms: { glow: { value: glowArr }, xs: { value: keys.map(k => k.x) }, color: { value: glowColor }, strength: { value: 0.0 } },
  vertexShader: `varying vec3 vP; varying vec2 vUv; void main(){ vUv=uv; vec4 w=modelMatrix*vec4(position,1.); vP=w.xyz; gl_Position=projectionMatrix*viewMatrix*w; }`,
  fragmentShader: `uniform float glow[88]; uniform float xs[88]; uniform vec3 color; uniform float strength; varying vec3 vP; varying vec2 vUv;
    void main(){ float s=0.; for(int i=0;i<88;i++){ float d=(vP.x-xs[i])/0.028; s+=glow[i]*exp(-d*d); }
      float v = exp(-vUv.y*6.0);
      gl_FragColor=vec4(color*s*v*strength,1.); }`,
  transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
});
{
  const g = new THREE.PlaneGeometry(2 * KB_HALF, 0.10);
  const spill = new THREE.Mesh(g, spillMat);
  hazeHidden.push(spill); depthHidden.push(spill);
  spill.position.set(0, 0.704 + 0.05, -0.1545);
  scene.add(spill);
}
// legs + lyre + pedals
function leg(x, z) {
  const g = new THREE.CylinderGeometry(0.055, 0.042, RIM_BOT - 0.04, 24);
  const m = new THREE.Mesh(g, lacquer); m.position.set(x, (RIM_BOT - 0.04) / 2 + 0.04, z);
  m.castShadow = true; scene.add(m);
  const w = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.04, 16), nickel);
  w.position.set(x, 0.02, z); scene.add(w);
}
leg(-0.69, -0.11); leg(0.69, -0.11); leg(-0.32, -2.30);
box(0.035, RIM_BOT - 0.10, 0.03, lacquer, -0.07, (RIM_BOT + 0.10) / 2, -0.28, 0.006);
box(0.035, RIM_BOT - 0.10, 0.03, lacquer, 0.07, (RIM_BOT + 0.10) / 2, -0.28, 0.006);
box(0.26, 0.07, 0.11, lacquer, 0, 0.075, -0.27, 0.01);
const pedals = [];
for (const x of [-0.055, 0, 0.055]) {
  const piv = new THREE.Group(); piv.position.set(x, 0.07, -0.22); scene.add(piv);
  const m = new THREE.Mesh(new RoundedBoxGeometry(0.03, 0.012, 0.13, 2, 0.004), nickel);
  m.position.set(0, 0, 0.065); m.castShadow = true; piv.add(m); pedals.push(piv);
}

// ---------------------------------------------------------------- hall
const floorMat = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(C.midnight).multiplyScalar(0.30), roughness: 0.62, clearcoat: 0.2, clearcoatRoughness: 0.45, envMapIntensity: 0.18 });
const floor = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), floorMat);
floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
const wallMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(C.void), roughness: 0.95 });
const WALL_X = -5.6;
{
  const left = new THREE.Mesh(new THREE.PlaneGeometry(30, 12), wallMat);
  left.position.set(WALL_X, 6, 0); left.rotation.y = Math.PI / 2; left.receiveShadow = true; scene.add(left);
  const back = new THREE.Mesh(new THREE.PlaneGeometry(30, 12), wallMat);
  back.position.set(0, 6, -9); back.receiveShadow = true; scene.add(back);
}

// window pane cookie (arched, 2x5 panes) — shared by the light, the window and the haze
const cookieCanvas = document.createElement('canvas'); cookieCanvas.width = cookieCanvas.height = 1024;
{
  const g = cookieCanvas.getContext('2d');
  g.fillStyle = '#000'; g.fillRect(0, 0, 1024, 1024);
  const cx = 512, w = 300, top = 170, bot = 860, archR = w / 2;
  g.save();
  g.beginPath();
  g.moveTo(cx - w / 2, bot); g.lineTo(cx - w / 2, top + archR);
  g.arc(cx, top + archR, archR, Math.PI, 0); g.lineTo(cx + w / 2, bot); g.closePath();
  g.clip();
  g.filter = 'blur(6px)';
  g.fillStyle = '#fff'; g.fillRect(0, 0, 1024, 1024);
  g.fillStyle = '#000';
  const bar = 16;
  g.fillRect(cx - bar / 2, 0, bar, 1024);                         // mullion
  for (let i = 1; i < 5; i++) g.fillRect(0, top + archR + i * (bot - top - archR) / 5 - bar / 2, 1024, bar);
  g.restore();
}
const cookie = new THREE.CanvasTexture(cookieCanvas);
cookie.colorSpace = THREE.NoColorSpace;   // used as a light mask, not a colour

// moonlight
const moonColor = new THREE.Color(C.moon).convertSRGBToLinear();
const moon = new THREE.SpotLight(new THREE.Color(C.moon), 230, 0, 0.30, 0.15, 2.0);
const WIN_Z = -2.2;                       // window behind-left of the piano: moonlight backlights the case
moon.position.set(WALL_X + 0.25, 5.0, WIN_Z);
moon.target.position.set(0.05, 0.62, -0.30);
moon.map = cookie;
moon.castShadow = true;
moon.shadow.mapSize.set(4096, 4096);
moon.shadow.camera.near = 2.5; moon.shadow.camera.far = 14;
moon.shadow.bias = -0.00008; moon.shadow.normalBias = 0.012;
moon.shadow.radius = 3;
scene.add(moon, moon.target);
// very low fill so the shadow side still reads as lacquer, not a hole
const fill = new THREE.HemisphereLight(new THREE.Color(C.midnight), new THREE.Color(C.void), 0.22);
scene.add(fill);

// the window itself (visible in wide framings)
{
  const winMat = new THREE.MeshBasicMaterial({ color: moonColor.clone().multiplyScalar(2.2), alphaMap: cookie, transparent: true, depthWrite: false });
  const win = new THREE.Mesh(new THREE.PlaneGeometry(3.4, 3.4), winMat);
  hazeHidden.push(win); depthHidden.push(win);
  win.position.set(WALL_X + 0.02, 4.6, WIN_Z); win.rotation.y = Math.PI / 2;
  scene.add(win);
}

// environment for lacquer reflections: dark hall + the bright window
{
  const env = new THREE.Scene();
  env.background = new THREE.Color(C.void).convertSRGBToLinear().multiplyScalar(0.8);
  const room = new THREE.Mesh(new THREE.BoxGeometry(14, 10, 22), new THREE.MeshBasicMaterial({ color: new THREE.Color(C.midnight).convertSRGBToLinear().multiplyScalar(0.35), side: THREE.BackSide }));
  room.position.y = 4.5; env.add(room);
  const winE = new THREE.Mesh(new THREE.PlaneGeometry(1.8, 3.8), new THREE.MeshBasicMaterial({ color: moonColor.clone().multiplyScalar(9) }));
  winE.position.set(-6.8, 4.6, WIN_Z); winE.rotation.y = Math.PI / 2; env.add(winE);
  // a soft strip of moonlight on the floor
  const patch = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 1.6), new THREE.MeshBasicMaterial({ color: moonColor.clone().multiplyScalar(0.25) }));
  patch.rotation.x = -Math.PI / 2; patch.position.set(-1.2, -0.48, 0.2); env.add(patch);
  const bounce = new THREE.Mesh(new THREE.PlaneGeometry(10, 3), new THREE.MeshBasicMaterial({ color: moonColor.clone().multiplyScalar(0.10) }));
  bounce.position.set(5.5, 1.5, 3.0); bounce.lookAt(0, 1, 0); env.add(bounce);
  const strip = new THREE.Mesh(new THREE.PlaneGeometry(14, 0.5), new THREE.MeshBasicMaterial({ color: moonColor.clone().multiplyScalar(0.5) }));
  strip.position.set(0, 8.5, -2); strip.lookAt(0, 0, 0); env.add(strip);
  const pm = new THREE.PMREMGenerator(renderer);
  scene.environment = pm.fromScene(env, 0.02, 0.1, 30).texture;
  scene.environmentIntensity = 1.0;
}

// ---------------------------------------------------------------- dust motes (pure function of t)
const MOTES = 1400;
const motes = (() => {
  const rnd = mulberry32(2027);
  const base = new Float32Array(MOTES * 3), seed = new Float32Array(MOTES * 4);
  for (let i = 0; i < MOTES; i++) {
    base.set([-4.5 + rnd() * 6.5, 0.2 + rnd() * 4.6, -2.2 + rnd() * 4.6], i * 3);
    seed.set([rnd() * 6.283, rnd() * 6.283, rnd() * 6.283, 0.4 + rnd() * 0.6], i * 4);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(base, 3));
  g.setAttribute('seed', new THREE.BufferAttribute(seed, 4));
  const m = new THREE.ShaderMaterial({
    uniforms: { t: { value: 0 }, lightVP: { value: new THREE.Matrix4() }, cookie: { value: cookie }, color: { value: moonColor }, px: { value: H * 0.5 } },
    vertexShader: `
      attribute vec4 seed; uniform float t; uniform mat4 lightVP; uniform sampler2D cookie; uniform float px;
      varying float vA;
      void main(){
        vec3 p = position;
        p += vec3(sin(t*0.061 + seed.x)*0.09, sin(t*0.047 + seed.y)*0.05, cos(t*0.053 + seed.z)*0.09);
        p.y -= mod(t*0.006*seed.w + seed.x*0.5, 4.6);
        if (p.y < 0.2) p.y += 4.6;
        float edge = smoothstep(0.2, 0.6, p.y) * smoothstep(4.8, 4.2, p.y);
        vec4 lp = lightVP * vec4(p, 1.0);
        vec2 luv = lp.xy / lp.w * 0.5 + 0.5;
        float lit = (lp.w > 0. && all(greaterThan(luv, vec2(0.))) && all(lessThan(luv, vec2(1.)))) ? texture2D(cookie, luv).r : 0.;
        vec4 mv = viewMatrix * vec4(p, 1.0);
        float d = -mv.z;
        vA = lit * edge * seed.w * smoothstep(0.35, 0.9, d);
        gl_PointSize = clamp(0.006 * px / d, 1.0, 5.0);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `uniform vec3 color; varying float vA;
      void main(){ vec2 c = gl_PointCoord - 0.5; float a = exp(-dot(c,c)*14.0) * vA; gl_FragColor = vec4(color * a * 0.9, 1.0); }`,
    transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
  });
  const pts = new THREE.Points(g, m);
  hazeHidden.push(pts); depthHidden.push(pts);
  pts.frustumCulled = false;
  scene.add(pts);
  return m;
})();

// ---------------------------------------------------------------- post: volumetric haze, bloom, grade
const sceneRT = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, samples: 8, depthTexture: new THREE.DepthTexture(W, H) });
const hdrRT = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType });
// haze is smooth: computed at half resolution from the farthest depth of each
// 2x2 block, so MSAA silhouettes don't print dark outlines into it
const hazeRT = new THREE.WebGLRenderTarget(W / 2, H / 2, { type: THREE.HalfFloatType });
// clean single-sample depth for the haze (MSAA-resolved depth is unreliable on silhouettes)
const hazeDepthRT = new THREE.WebGLRenderTarget(W / 2, H / 2, { depthTexture: new THREE.DepthTexture(W / 2, H / 2) });
const fsCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
const fsGeo = new THREE.PlaneGeometry(2, 2);
function fsPass(material) { const s = new THREE.Scene(); s.add(new THREE.Mesh(fsGeo, material)); return s; }
const lightCam = new THREE.PerspectiveCamera(1, 1, 3.0, 14);
// depth from the moon's point of view, so the haze is shadowed by the piano
const lightDepthRT = new THREE.WebGLRenderTarget(2048, 2048, { depthTexture: new THREE.DepthTexture(2048, 2048) });
const depthOnly = new THREE.MeshBasicMaterial({ colorWrite: false });

const lightVP = new THREE.Matrix4();

const hazeMat = new THREE.ShaderMaterial({
  uniforms: {
    tScene: { value: sceneRT.texture }, tDepth: { value: hazeDepthRT.depthTexture }, tLight: { value: lightDepthRT.depthTexture },
    invProj: { value: new THREE.Matrix4() }, camWorld: { value: new THREE.Matrix4() }, camPos: { value: new THREE.Vector3() },
    lightVP: { value: lightVP }, lightPos: { value: new THREE.Vector3() }, cookie: { value: cookie },
    color: { value: moonColor }, t: { value: 0 }, strength: { value: 0.22 }, dbg: { value: 0 },
  },
  vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=vec4(position.xy,0.,1.); }`,
  fragmentShader: `
    precision highp float;
    uniform sampler2D tScene, tDepth, tLight, cookie; uniform mat4 invProj, camWorld, lightVP;
    uniform vec3 camPos, lightPos, color; uniform float t, strength; uniform int dbg; varying vec2 vUv;
    float hash(vec3 p){ p=fract(p*0.3183099+.1); p*=17.0; return fract(p.x*p.y*p.z*(p.x+p.y+p.z)); }
    float noise(vec3 x){ vec3 i=floor(x), f=fract(x); f=f*f*(3.-2.*f);
      return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x), mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
                 mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x), mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y), f.z); }
    void main(){
      float z = texture2D(tDepth, vUv).r;
      vec4 vp = invProj * vec4(vUv*2.-1., z*2.-1., 1.); vp /= vp.w;
      vec3 wp = (camWorld * vp).xyz;
      vec3 rd = wp - camPos; float dist = min(length(rd), 16.0); rd = normalize(rd);
      const int STEPS = 56;
      float stepLen = dist / float(STEPS);
      // static (not per-frame) dither: no flicker
      float dither = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
      if (dbg == 4) dither = 0.5;
      if (dbg == 1) { gl_FragColor = vec4(vec3(dist / 16.0), 1.); return; }
      if (dbg == 6) { gl_FragColor = vec4(!(length(wp) < 1e6) ? 1. : 0., !(rd.x == rd.x) ? 1. : 0., (z - 0.97) * 30., 1.); return; }
      float acc = 0., occl = 0.;
      vec3 drift = vec3(0.020, -0.006, 0.014) * t;
      for (int i = 0; i < STEPS; i++) {
        vec3 p = camPos + rd * (float(i) + dither) * stepLen;
        vec4 lp = lightVP * vec4(p, 1.);
        if (lp.w <= 0.) continue;
        vec2 luv = lp.xy / lp.w * 0.5 + 0.5;
        if (any(lessThan(luv, vec2(0.))) || any(greaterThan(luv, vec2(1.)))) continue;
        // explicit LOD: implicit derivatives are garbage across silhouettes inside
        // this divergent loop and would pick a blurred (dark) mip
        float lit = textureLod(cookie, luv, 0.0).r;
        float ld = lp.z / lp.w * 0.5 + 0.5;
        // occluded by the piano: soft 5-tap compare so thin edges (the lid) don't alias
        const float LT = 1.5 / 2048.0;
        float vis = step(ld - 0.0004, textureLod(tLight, luv, 0.0).r) * 0.4
                  + step(ld - 0.0004, textureLod(tLight, luv + vec2( LT, 0.), 0.0).r) * 0.15
                  + step(ld - 0.0004, textureLod(tLight, luv + vec2(-LT, 0.), 0.0).r) * 0.15
                  + step(ld - 0.0004, textureLod(tLight, luv + vec2(0.,  LT), 0.0).r) * 0.15
                  + step(ld - 0.0004, textureLod(tLight, luv + vec2(0., -LT), 0.0).r) * 0.15;
        if (dbg == 3) vis = 1.;
        lit *= vis; occl += (1. - vis) / float(STEPS);
        float dl = length(p - lightPos);
        float dens = 0.25 + 0.75 * noise(p * 1.1 + drift) ;
        dens *= smoothstep(0.0, 0.8, p.y);                       // thinner near the floor
        float near = smoothstep(0.5, 2.2, (float(i) + dither) * stepLen);
        if (dbg == 5) near = 1.;
        acc += near * lit * dens / (0.35 + 0.03 * dl * dl) * stepLen;
      }
      if (dbg == 2) { gl_FragColor = vec4(vec3(occl * 4.), 1.); return; }
      gl_FragColor = vec4(color * acc * strength, 1.);
    }`,
  depthTest: false, depthWrite: false,
});
const hazeScene = fsPass(hazeMat);
const compMat = new THREE.ShaderMaterial({
  uniforms: { sceneMul: { value: 1 }, tScene: { value: sceneRT.texture }, tHaze: { value: hazeRT.texture }, texel: { value: new THREE.Vector2(2 / W, 2 / H) } },
  vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=vec4(position.xy,0.,1.); }`,
  fragmentShader: `uniform sampler2D tScene, tHaze; uniform vec2 texel; uniform float sceneMul; varying vec2 vUv;
    // grazing clearcoat specular can overflow half floats on silhouettes (Inf/NaN);
    // NaN-safe test: comparisons with NaN are false
    bool ok(vec3 c){ return c.r >= 0. && c.g >= 0. && c.b >= 0. && c.r < 4000. && c.g < 4000. && c.b < 4000.; }
    vec3 sceneAt(vec2 uv){
      vec3 c = texture2D(tScene, uv).rgb;
      if (ok(c)) return min(c, vec3(64.));
      vec2 px = texel * 0.5; vec3 s = vec3(0.); float n = 0.;
      for (int i = 0; i < 4; i++) {
        vec2 o = i == 0 ? vec2(px.x, 0.) : i == 1 ? vec2(-px.x, 0.) : i == 2 ? vec2(0., px.y) : vec2(0., -px.y);
        vec3 q = texture2D(tScene, uv + o).rgb;
        if (ok(q)) { s += min(q, vec3(64.)); n += 1.; }
      }
      return n > 0. ? s / n : vec3(0.);
    }
    void main(){
      vec3 h = vec3(0.); float wsum = 0.;
      for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
        float w = (x == 0 ? 2. : 1.) * (y == 0 ? 2. : 1.);
        h += w * texture2D(tHaze, vUv + vec2(x, y) * texel).rgb; wsum += w;
      }
      gl_FragColor = vec4(sceneMul * sceneAt(vUv) + h / wsum, 1.);
    }`,
  depthTest: false, depthWrite: false,
});
const compScene = fsPass(compMat);

const bloom = new UnrealBloomPass(new THREE.Vector2(W, H), 0.6, 0.5, 1.0);

const finalMat = new THREE.ShaderMaterial({
  uniforms: { tHdr: { value: hdrRT.texture }, exposure: { value: 1.0 }, fade: { value: 1.0 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=vec4(position.xy,0.,1.); }`,
  fragmentShader: `
    precision highp float;
    uniform sampler2D tHdr; uniform float exposure, fade; varying vec2 vUv;
    // ACES filmic (Hill fit), same curve three.js uses
    vec3 RRTAndODTFit(vec3 v){ vec3 a=v*(v+0.0245786)-0.000090537; vec3 b=v*(0.983729*v+0.4329510)+0.238081; return a/b; }
    vec3 aces(vec3 c){
      const mat3 i=mat3(vec3(0.59719,0.07600,0.02840),vec3(0.35458,0.90834,0.13383),vec3(0.04823,0.01566,0.83777));
      const mat3 o=mat3(vec3(1.60475,-0.10208,-0.00327),vec3(-0.53108,1.10813,-0.07276),vec3(-0.07367,-0.00605,1.07602));
      c *= exposure/0.6; c = i*c; c = RRTAndODTFit(c); c = o*c; return clamp(c,0.,1.); }
    vec3 toSRGB(vec3 c){ return mix(c*12.92, 1.055*pow(c,vec3(1./2.4))-0.055, step(0.0031308,c)); }
    void main(){
      vec3 c = texture2D(tHdr, vUv).rgb;
      vec2 q = (vUv - 0.5) * vec2(1.7778, 1.0);
      float vig = mix(0.62, 1.0, smoothstep(1.05, 0.25, length(q)));
      c = aces(c * vig);
      c = toSRGB(c) * fade;
      // static ordered dither against banding in the dark blues
      float d = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715)))) - 0.5;
      gl_FragColor = vec4(c + d / 255.0, 1.0);
    }`,
  depthTest: false, depthWrite: false,
});
const finalScene = fsPass(finalMat);

// ---------------------------------------------------------------- camera path (time-aware Hermite, C1)
// [video t, position, target, vertical fov]
const SHOTS = [
  [0.0,  [0.52, 0.86, 0.30], [-0.10, 0.725, -0.07], 30],   // hook: low, close, treble side
  [4.0,  [0.62, 0.92, 0.40], [-0.10, 0.735, -0.10], 30],
  [11.7, [1.55, 1.55, 1.55], [-0.15, 0.80, -0.55], 32],    // revealed: medium-wide 3/4
  [18.8, [1.25, 1.42, 1.25], [-0.12, 0.76, -0.38], 32],
  [21.1, [1.30, 1.55, 1.35], [-0.12, 0.78, -0.45], 32],    // fermata breath
  [28.0, [0.62, 1.10, 0.62], [-0.10, 0.72, -0.10], 31],    // back close, treble side
  [34.5, [0.05, 1.12, 0.62], [-0.02, 0.72, -0.10], 34],    // player's seat
  [41.1, [-0.15, 1.14, 0.64], [0.02, 0.72, -0.10], 34],
  [50.0, [1.15, 1.40, 1.20], [-0.12, 0.76, -0.35], 32],    // big chords: medium 3/4
  [60.0, [1.00, 1.36, 1.08], [-0.10, 0.75, -0.30], 32],
  [68.0, [0.12, 1.12, 0.60], [0.00, 0.72, -0.10], 34],     // closing theme, close
  [80.5, [0.35, 1.16, 0.62], [-0.04, 0.72, -0.10], 33],
  [87.5, [2.40, 1.85, 2.70], [-0.50, 0.95, -0.60], 34],    // ring-out: slow rise toward the window shot
];
function camAt(t) {
  const n = SHOTS.length;
  if (t <= SHOTS[0][0]) return SHOTS[0];
  if (t >= SHOTS[n - 1][0]) return SHOTS[n - 1];
  let i = 0; while (SHOTS[i + 1][0] < t) i++;
  const a = SHOTS[i], b = SHOTS[i + 1], dt = b[0] - a[0];
  const s = (t - a[0]) / dt, s2 = s * s, s3 = s2 * s;
  const h00 = 2 * s3 - 3 * s2 + 1, h10 = s3 - 2 * s2 + s, h01 = -2 * s3 + 3 * s2, h11 = s3 - s2;
  const tangent = (k, comp, j) => {          // finite-difference slope in units / second
    if (k === 0 || k === n - 1) return 0;
    const A = SHOTS[k - 1], B = SHOTS[k + 1];
    const va = comp === 3 ? A[3] : A[comp][j], vb = comp === 3 ? B[3] : B[comp][j];
    return (vb - va) / (B[0] - A[0]) * 0.85;
  };
  const lerpComp = (comp, j) => {
    const va = comp === 3 ? a[3] : a[comp][j], vb = comp === 3 ? b[3] : b[comp][j];
    return h00 * va + h10 * dt * tangent(i, comp, j) + h01 * vb + h11 * dt * tangent(i + 1, comp, j);
  };
  return [t, [0, 1, 2].map(j => lerpComp(1, j)), [0, 1, 2].map(j => lerpComp(2, j)), lerpComp(3)];
}

// ---------------------------------------------------------------- cards
const endEl = document.getElementById('end');
function cards(t) {
  const e = smooth(86.8, 87.6, t) * (1 - smooth(90.0, 90.7, t));
  endEl.style.opacity = e.toFixed(4);
  endEl.style.filter = `blur(${((1 - smooth(86.8, 87.6, t)) * 6).toFixed(2)}px)`;
}

// ---------------------------------------------------------------- seek
const tmpV = new THREE.Vector3();
function update(t) {
  const mt = t - LEAD;                                    // music time
  // keys
  for (let i = 0; i < 88; i++) {
    const k = keys[i];
    const { depth, glow } = keyState(k, mt);
    k.pivot.rotation.x = depth * MAX_DIP;
    k.mat.emissiveIntensity = glow * (k.black ? 2.0 : 1.3);
    glowArr[i] = glow;
  }
  spillMat.uniforms.strength.value = 0.22;
  pedals[2].rotation.x = pedalDownAt(mt) ? 0.08 : 0;

  // camera
  const [, p, tg, fov] = window.__camOverride || camAt(t);
  camera.position.set(p[0], p[1], p[2]);
  camera.lookAt(tmpV.set(tg[0], tg[1], tg[2]));
  camera.fov = fov; camera.updateProjectionMatrix(); camera.updateMatrixWorld();

  // light camera (matches SpotLight.map projection)
  lightCam.fov = THREE.MathUtils.radToDeg(moon.angle) * 2;
  lightCam.position.copy(moon.position); lightCam.lookAt(moon.target.position);
  lightCam.updateProjectionMatrix(); lightCam.updateMatrixWorld();
  lightVP.multiplyMatrices(lightCam.projectionMatrix, lightCam.matrixWorldInverse);
  motes.uniforms.t.value = t; motes.uniforms.lightVP.value.copy(lightVP);

  hazeMat.uniforms.invProj.value.copy(camera.projectionMatrixInverse);
  hazeMat.uniforms.camWorld.value.copy(camera.matrixWorld);
  hazeMat.uniforms.camPos.value.copy(camera.position);
  hazeMat.uniforms.lightPos.value.copy(moon.position);
  hazeMat.uniforms.t.value = t;

  // global fades: up from black at the start, down to black after the ring-out
  finalMat.uniforms.fade.value = smooth(0.0, 0.45, t) * (1 - smooth(85.0, 86.5, t));
  cards(t);
}
function render() {
  scene.overrideMaterial = depthOnly;
  for (const o of hazeHidden) o.visible = false;
  renderer.setRenderTarget(lightDepthRT); renderer.render(scene, lightCam);
  for (const o of hazeHidden) o.visible = true;
  for (const o of depthHidden) o.visible = false;
  renderer.setRenderTarget(hazeDepthRT); renderer.render(scene, camera);
  for (const o of depthHidden) o.visible = true;
  scene.overrideMaterial = null;
  renderer.setRenderTarget(sceneRT); renderer.render(scene, camera);
  renderer.setRenderTarget(hazeRT); renderer.render(hazeScene, fsCam);
  renderer.setRenderTarget(hdrRT); renderer.render(compScene, fsCam);
  bloom.render(renderer, null, hdrRT, 0, false);
  renderer.setRenderTarget(null); renderer.render(finalScene, fsCam);
}

window.DURATION = DURATION;
window.FPS = FPS;
window.seek = async (t) => {
  update(t);
  render();
  renderer.getContext().finish();
  await document.fonts.ready;
};
// debug hooks for QA
window.__keyDepth = (p, t) => keyState(keys[p - 21], t - LEAD).depth;
window.__notes = NOTES;
window.__lead = LEAD;
window.__dbg = { hazeMat, compMat, moon, renderer };
await document.fonts.load('300 64px "Cormorant Garamond"');
await document.fonts.load('italic 400 38px "Cormorant Garamond"');
await window.seek(0);
window.READY = true;
