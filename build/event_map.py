"""Musical event map for the storm film.

Reads the performance (notes.json, score dynamics, mix.wav) and writes
event_map.json, which every visual cue in the Blender build reads:

  accents      sf / f / ff / fp chords: lightning + punch-in candidates
  peaks        velocity peaks at the tops of the arpeggio waves
  phrases      phrase boundaries (cut points), from the score's structure
  loudness     momentary + short-term LUFS at 10 Hz, centred on their windows
  storm        0..1 storm intensity derived from the short-term loudness
  climax       the come-apart moment and the reassembly chord

All times are VIDEO seconds (music time + LEAD), the same clock as mix.wav.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from perform import build_time_map, read_events, END_MOMENT  # noqa: E402

HERE = Path(__file__).parent
LEAD = 0.25
FPS = 30

notes = json.load(open(HERE / "notes.json"))
to_sec = build_time_map(END_MOMENT + 2)
vt = lambda m: to_sec(m) + LEAD                       # score moment -> video time
bar_t = lambda b: vt(b - 1)                           # bar number -> video time
bar_of = lambda m: int(m) + 1

# ---- onsets grouped into chords (simultaneous within 12 ms) ----
ons = sorted(notes["notes"], key=lambda n: n["on"])
chords = []
for n in ons:
    if chords and n["on"] - chords[-1]["t0"] < 0.012:
        chords[-1]["notes"].append(n)
    else:
        chords.append({"t0": n["on"], "notes": [n]})
for c in chords:
    c["t"] = round(c["t0"] + LEAD, 4)
    c["vmax"] = max(n["v"] for n in c["notes"])
    c["size"] = len(c["notes"])
    c["pitches"] = sorted(n["p"] for n in c["notes"])

def chord_at(t, tol=0.03):
    best = min(chords, key=lambda c: abs(c["t"] - t))
    return best if abs(best["t"] - t) <= tol else None

# ---- score accents (sf/f/ff/fp) inside the excerpt ----
marks = [(m, val) for m, kind, val in read_events(HERE / "events-up.notes") +
         read_events(HERE / "events-down.notes")
         if kind == "dynamic" and m <= END_MOMENT + 1e-6]
STRENGTH = {"ff": 1.0, "sf": 0.75, "sfz": 0.75, "f": 0.7, "fp": 0.6}
accents = {}
for m, val in sorted(marks):
    if val not in STRENGTH:
        continue
    t = vt(m)
    c = chord_at(t)
    key = round(t, 3)
    if key in accents:
        continue
    accents[key] = {
        "t": round(t, 4), "frame": int(np.ceil(t * FPS - 1e-9)), "bar": bar_of(m),
        "beat": round((m % 1) * 4 + 1, 2), "mark": val, "strength": STRENGTH[val],
        "chord_size": c["size"] if c else 0, "vmax": c["vmax"] if c else 0,
        "pitches": c["pitches"] if c else [],
    }
accents = sorted(accents.values(), key=lambda a: a["t"])

# ---- velocity peaks at the tops of the arpeggio waves (not already accents) ----
vel = np.array([c["vmax"] for c in chords])
peaks = []
for i, c in enumerate(chords):
    lo, hi = max(0, i - 8), min(len(chords), i + 9)
    local = vel[lo:hi]
    if c["vmax"] == local.max() and c["vmax"] >= np.median(local) + 10 and c["vmax"] >= 70:
        if all(abs(c["t"] - a["t"]) > 0.08 for a in accents):
            peaks.append({"t": c["t"], "frame": int(np.ceil(c["t"] * FPS - 1e-9)),
                          "v": int(c["vmax"]), "top": max(c["pitches"])})

# ---- phrase boundaries: the score's sections (bar numbers are the excerpt's) ----
PHRASES = [
    (1, "A1  arpeggio waves, p, sf crashes at bars 2/4/6-8"),
    (9, "A2  f chords, descending; fermata in bar 14"),
    (15, "A3  arpeggio waves again, cresc. from bar 19"),
    (21, "B1  second theme (G# minor), melody over bass, cresc. from bar 25"),
    (29, "B2  syncopated sf chords with trills"),
    (33, "B3  ff -> p, cresc.  (first ff)"),
    (37, "B4  ff -> p, cresc.  (second ff)"),
    (41, "B5  four f chords"),
    (43, "C1  closing theme, p"),
    (49, "C2  p cresc. -> f (bar 50), p cresc. -> f (bar 52)"),
    (53, "C3  p, cresc./decresc. into the cadence"),
    (57, "END cadence on G# minor, ring-out"),
]
phrases = [{"bar": b, "t": round(bar_t(b), 4), "frame": int(round(bar_t(b) * FPS)), "what": w}
           for b, w in PHRASES]
bars = [{"bar": b, "t": round(bar_t(b), 4)} for b in range(1, 58)]

# ---- loudness (ffmpeg ebur128, 10 Hz) ----
log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(HERE / "mix.wav"),
                      "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
rows = re.findall(r"t:\s*([\d.]+).*?M:\s*(-?[\d.]+)\s+S:\s*(-?[\d.]+)", log)
t_raw = np.array([float(r[0]) for r in rows])
M = np.array([float(r[1]) for r in rows])
S = np.array([float(r[2]) for r in rows])
grid = np.round(np.arange(0, 91.0 + 1e-9, 0.1), 2)
Mc = np.interp(grid, t_raw - 0.2, M)          # centre the 0.4 s window
Sc = np.interp(grid, t_raw - 1.5, S)          # centre the 3 s window
Mc = np.maximum(Mc, -60); Sc = np.maximum(Sc, -60)

# storm intensity = narrative envelope (gathering -> full -> clearing) modulated
# by the music's loudness: momentary LUFS in energy terms, smoothed over ~1.5 s,
# with a fast attack / slow release so gusts land on loud bars and linger
music = (grid > 1.0) & (grid < bar_t(57))
energy = 10 ** (Mc / 10)
kern = np.hanning(15); kern /= kern.sum()
Lsm = 10 * np.log10(np.convolve(energy, kern, mode="same") + 1e-12)
lo, hi = np.percentile(Lsm[music], 5), np.percentile(Lsm[music], 99)
raw = np.clip((Lsm - lo) / (hi - lo), 0, 1)
env_follow = np.zeros_like(raw)
for i in range(1, len(raw)):
    k = 0.25 if raw[i] > env_follow[i - 1] else 0.04          # per 0.1 s step
    env_follow[i] = env_follow[i - 1] + k * (raw[i] - env_follow[i - 1])
# act envelope: moon clear -> clouds gather (act 1) -> full storm from bar 29
ACT = [(0.0, 0.10), (bar_t(9), 0.30), (bar_t(21), 0.50), (bar_t(29), 0.85),
       (bar_t(33), 1.00), (bar_t(53), 0.90), (bar_t(57), 0.80),
       (bar_t(57) + 3.5, 0.0), (91.0, 0.0)]
base = np.interp(grid, [a[0] for a in ACT], [a[1] for a in ACT])
storm = np.clip(base * (0.55 + 0.45 * env_follow), 0, 1)

# ---- climax: highest short-term loudness on an ff/f chord ----
def s_at(t):
    return float(np.interp(t, grid, Sc))
def m_peak(t):
    w = (grid >= t) & (grid <= t + 0.6)
    return float(Mc[w].max())
cands = [dict(a, S=round(s_at(a["t"] + 1.0), 2), Mpk=round(m_peak(a["t"]), 2))
         for a in accents if a["mark"] in ("ff", "f")]
for c in cands:
    c["score"] = round(c["Mpk"] + 0.5 * c["S"] + (2.0 if c["mark"] == "ff" else 0), 2)
cands.sort(key=lambda c: -c["score"])
climax = cands[0]
reassemble = next(a for a in accents if a["t"] > climax["t"] + 6.0 and a["mark"] in ("ff", "f"))

out = {
    "fps": FPS, "lead": LEAD, "duration": 91.0, "cadence_t": round(bar_t(57), 4),
    "accents": accents, "peaks": peaks, "phrases": phrases, "bars": bars,
    "loudness": {"t": grid.tolist(), "M": np.round(Mc, 2).tolist(), "S": np.round(Sc, 2).tolist()},
    "storm": np.round(storm, 4).tolist(),
    "climax": climax, "climax_candidates": cands[:6], "reassemble": reassemble,
    "pedal": [{"on": round(p["on"] + LEAD, 4), "off": round(p["off"] + LEAD, 4)} for p in notes["pedal"]],
}
json.dump(out, open(HERE / "event_map.json", "w"), indent=1)

# ---- summary ----
print(f"chords/onsets: {len(chords)}   accents: {len(accents)}   velocity peaks: {len(peaks)}")
print("\nACCENTS")
for a in accents:
    print(f"  {a['t']:6.2f}s  f{a['frame']:4d}  bar {a['bar']:2d} beat {a['beat']:<4}  {a['mark']:<3} "
          f"chord {a['chord_size']}  vmax {a['vmax']}")
print("\nPHRASES")
for p in phrases:
    print(f"  {p['t']:6.2f}s  bar {p['bar']:2d}  {p['what']}")
print("\nCLIMAX CANDIDATES")
for c in cands[:6]:
    print(f"  {c['t']:6.2f}s bar {c['bar']} {c['mark']}  M-peak {c['Mpk']}  S {c['S']}  score {c['score']}")
print(f"\nclimax {climax['t']:.2f}s bar {climax['bar']}   reassemble {reassemble['t']:.2f}s bar {reassemble['bar']}")
print(f"peaks: {[round(p['t'],2) for p in peaks]}")
