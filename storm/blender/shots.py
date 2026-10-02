"""Shot list as data: camera = f(t, render_frame).

Each shot: t0, t1, engine, lens (mm), fstop, and either explicit keyframes
[(u, pos, target)] in world space or a tracking rule.  `frame` decides the shot
(so motion blur never straddles a cut); `t` drives the move (subframe-smooth).

Engines: "CYCLES" for macros and the come-apart, "EEVEE" elsewhere (plan B).
crop45: horizontal centre of the 4:5 window (0..1 of the open-gate width).
"""
import bisect
import math

from mathutils import Vector

from lib import FPS, load_data

NOTES, EMAP = load_data()
LEAD = EMAP["lead"]
KEY_FRONT_X = -1.37                    # world x of the key fronts
W = 0.0235
_BLACK = {1: -0.10, 3: 0.10, 6: -0.13, 8: 0.0, 10: 0.13}


def key_x_local(k):
    wi = 0
    for j in range(k + 1):
        pc = (j + 21) % 12
        if pc in _BLACK:
            if j == k:
                return -26 * W + wi * W + _BLACK[pc] * W
        else:
            if j == k:
                return -26 * W + wi * W + W / 2
            wi += 1


def key_world(k, y_on_key=0.07, z=0.735):
    return Vector((KEY_FRONT_X + y_on_key, -key_x_local(k), z))


def string_x_local(k, y=0.43):
    if k < 20:
        x0, y0 = -0.705 + 0.0145 * k, 0.24
        x1, y1 = -0.46 + 0.012 * k, 2.50 - 0.032 * k
        return x0 + (y - y0) / (y1 - y0) * (x1 - x0)
    return -0.395 + (k - 20) * (1.045 / 67)


def hammer_world(k, z=0.868):
    return Vector((0.43 + KEY_FRONT_X, -string_x_local(k), z))


def local_w(x, y, z):
    """piano-local -> world"""
    return Vector((y + KEY_FRONT_X, -x, z))


def hammer_macro(k, side=1.0, dist=0.33):
    """Camera in the action gap at strike height, looking ACROSS the hammer row
    (along -x*side): the strings of the notes in between cross the frame as
    blurred horizontal lines; the struck hammer rises into focus."""
    hx = string_x_local(k)
    p0 = local_w(hx + side * dist, 0.440, 0.9000)
    p1 = local_w(hx + side * (dist - 0.015), 0.436, 0.8995)
    tg = local_w(hx, 0.430, 0.8970)
    return [(0, p0, tg), (1, p1, tg)]


def top_note(t_video, tol=0.03):
    best = None
    for n in NOTES["notes"]:
        if abs(n["on"] + LEAD - t_video) <= tol and (best is None or n["p"] > best["p"]):
            best = n
    return best["p"] - 21


# pitch centroid of what is being played (for tracking moves), 100 Hz grid
def _centroid_curve(only_top=False, sigma=0.22):
    ts = [i / 100 for i in range(0, 9101)]
    ons = sorted(NOTES["notes"], key=lambda n: n["on"])
    on_t = [n["on"] + LEAD for n in ons]
    out = []
    for t in ts:
        i0 = bisect.bisect_left(on_t, t - 3 * sigma)
        i1 = bisect.bisect_right(on_t, t + 3 * sigma)
        sw = sp = 0.0
        for n in ons[i0:i1]:
            if only_top and n["p"] < 56:
                continue
            w = math.exp(-0.5 * ((n["on"] + LEAD - t) / sigma) ** 2) * n["v"]
            sw += w; sp += w * (n["p"] - 21)
        out.append(sp / sw if sw > 0 else (out[-1] if out else 30.0))
    # second smoothing pass (moving average, 0.5 s)
    k = 25
    sm = []
    for i in range(len(out)):
        a, b = max(0, i - k), min(len(out), i + k + 1)
        sm.append(sum(out[a:b]) / (b - a))
    return sm


_CENT = None
_CENT_TOP = None


def centroid(t, top=False):
    global _CENT, _CENT_TOP
    if _CENT is None:
        _CENT = _centroid_curve(False)
        _CENT_TOP = _centroid_curve(True)
    c = _CENT_TOP if top else _CENT
    i = max(0, min(len(c) - 2, int(t * 100)))
    u = t * 100 - i
    return c[i] * (1 - u) + c[i + 1] * u


def key_y_world_float(kf):
    k0 = int(max(0, min(86, math.floor(kf))))
    u = kf - k0
    return -(key_x_local(k0) * (1 - u) + key_x_local(k0 + 1) * u)


V = Vector
S = []


def shot(t0, t1, name, lens, fstop, keys=None, engine="EEVEE", track=None, focus=None, crop45=0.5,
         hide=(), fill=None, exposure=0.0, shutter=None):
    """fill: (offset from target in world metres, watts, size) for a small soft
    cool-white macro fill light that exists only in this shot."""
    S.append(dict(t0=t0, t1=t1, name=name, lens=lens, fstop=fstop, keys=keys, engine=engine,
                  track=track, focus=focus, crop45=crop45, hide=tuple(hide) + (("haze",) if name.startswith("macro") else ()),
                  fill=fill, exposure=exposure,
                  shutter=shutter if shutter is not None else (0.12 if name.startswith("macro") else 0.5)))


B = {b["bar"]: b["t"] for b in EMAP["bars"]}
k_s4 = top_note(8.464)
k_s19 = top_note(42.893)
k_s32 = top_note(71.107)
k_s16 = top_note(38.25)

# ================================================================ v2: the mechanics film
# The piano's moving parts are the subject.  Cuts land on bar lines / accents.
_CUT = ("rim", "lid", "prop_stick", "plate_side", "plate_side.001", "fallboard", "plate_front", "tuning_pins")
CUT = _CUT + ("cheek_R",)        # cutaway hides (treble side)
CUT_BASS = _CUT + ("cheek_L",)


def graze_front(t0, t1, name="graze_front", lens=40, fstop=2.2, side=-1):
    """Low, close, in front of the keys, tracking the arpeggio wave."""
    shot(t0, t1, name, lens, fstop, track=dict(kind="keys", offset=V((-0.40, 0.30 * side, 0.085)),
         drift=V((0.0, -0.10, 0.0)), look=V((0.04, -0.08 * side, -0.012))))


def graze_end(t0, t1, side, name="graze_end"):
    """Camera just past one end of the keyboard at key height, panning to the music."""
    y = -0.98 if side == "treble" else 0.98
    shot(t0, t1, name, 35, 2.8, track=dict(kind="aim"), keys=[(0, V((-1.34, y, 0.80)), None),
         (1, V((-1.36, y * 0.97, 0.81)), None)], hide=("cheek_R",) if side == "treble" else ("cheek_L",))


def pov(t0, t1, name="pov", near=False):
    """The pianist's eyes: looking down at the keys and into the open piano."""
    shot(t0, t1, name, 30 if not near else 35, 4.0,
         track=dict(kind="pov", eye=V((-2.02 if not near else -1.90, 0.0, 1.30 if not near else 1.18)), follow=0.35))


def cutaway(t0, t1, wide=False, side="treble", name="cutaway"):
    """Side view of the action with the case hidden: key -> jack -> hammer -> string."""
    y = -1.0 if side == "treble" else 1.0
    if wide:
        keys = [(0, V((-1.16, y * 1.20, 0.82)), V((-1.10, 0.0, 0.79))), (1, V((-1.13, y * 1.12, 0.815)), V((-1.09, 0.0, 0.79)))]
        lens = 28
    else:
        keys = [(0, V((-1.13, y * 0.98, 0.805)), V((-1.10, 0.0, 0.795))), (1, V((-1.11, y * 0.92, 0.80)), V((-1.09, 0.0, 0.795)))]
        lens = 35
    shot(t0, t1, name, lens, 4.0, keys=keys, hide=CUT if side == "treble" else CUT_BASS)


def damper_row(t0, t1, side="treble", name="hammer_row"):
    """Down the action gap from one end: the row of white hammer heads, with the
    struck ones popping up into the strings (case parts at that end hidden)."""
    y = -1.05 if side == "treble" else 1.05
    shot(t0, t1, name, 50, 5.6, keys=[(0, V((-0.95, y, 0.905)), V((-0.94, y * -0.1, 0.872))),
         (1, V((-0.95, y * 0.96, 0.903)), V((-0.94, y * -0.1, 0.872)))],
         hide=("rim", "plate_side", "plate_side.001", "cheek_R" if side == "treble" else "cheek_L"))


HF = (V((-0.06, 0.0, 0.05)), 0.10, 0.03)

# ================================================================ v3: calm, keys only
# Feedback: less camera movement, no shots inside the piano.  Every shot looks
# at the keyboard from outside; moves are slow drifts/pushes of a few cm.

def kshot(t0, t1, name, lens, fstop, p0, p1, tgt, focus=None, hide=(), engine="EEVEE", exposure=0.0):
    shot(t0, t1, name, lens, fstop, keys=[(0, V(p0), V(tgt)), (1, V(p1), V(tgt))], focus=focus,
         hide=hide, engine=engine, exposure=exposure)


def low_front(t0, t1, y=0.0, name="low_front"):
    """Low and close in front of the keys, shallow focus, slow sideways drift."""
    kshot(t0, t1, name, 40, 2.2, (-1.70, y - 0.30, 0.815), (-1.69, y - 0.20, 0.81), (-1.26, y + 0.08, 0.724),
          exposure=0.35)


def pianist(t0, t1, y=0.0, name="pianist", push=0.06):
    """The pianist's eyes, tight on the keys, a slow push in."""
    kshot(t0, t1, name, 40, 3.2, (-2.00, y, 1.10), (-2.00 + push, y, 1.10 - push * 0.5), (-1.25, y * 0.9, 0.735),
          exposure=0.25)


def from_end(t0, t1, side, name="from_end"):
    """Down the keyboard from one end at key height."""
    y = -0.98 if side == "treble" else 0.98
    kshot(t0, t1, name, 35, 2.8, (-1.34, y, 0.80), (-1.345, y * 0.975, 0.802), (-1.30, 0.0, 0.735),
          hide=("cheek_R",) if side == "treble" else ("cheek_L",), exposure=0.25)


def keys_side(t0, t1, y=0.0, name="keys_side"):
    """Long lens from the audience side, keys stacked in compression."""
    kshot(t0, t1, name, 85, 2.8, (-1.50, y - 1.25, 0.92), (-1.50, y - 1.17, 0.915), (-1.30, y + 0.18, 0.735),
          exposure=0.25)


def against_windows(t0, t1, name="against_windows"):
    kshot(t0, t1, name, 24, 4.0, (-2.75, -1.35, 0.80), (-2.68, -1.30, 0.82), (-1.0, 0.9, 1.37),
          focus=V((-1.3, -0.3, 0.75)))


# ---------------------------------------------------------------- A (bars 1-14)
low_front(0.0, 2.75, 0.0, "open_low_front")
pianist(2.75, B[5])
from_end(B[5], B[7], "bass")
keys_side(B[7], B[9], -0.15)
against_windows(B[9], B[12])
low_front(B[12], B[15], -0.25, "fermata_low_front")
# ---------------------------------------------------------------- B (bars 15-32)
pianist(B[15], B[18], 0.1)
from_end(B[18], B[21], "treble")
keys_side(B[21], B[25], -0.30, "melody_side")
low_front(B[25], B[29], 0.10, "build_low_front")
against_windows(B[29], B[31], "sf_windows")
pianist(B[31], B[33], 0.0, "pianist_push", push=0.18)
# ---------------------------------------------------------------- C: the come-apart (bars 33-41)
kshot(B[33], B[37], "explode", 35, 5.6, (-3.6, -3.5, 2.50), (-3.9, -3.8, 2.62), (0.15, 0.1, 1.40),
      focus=V((0.0, 0.0, 1.4)), engine="CYCLES", exposure=0.6)
kshot(B[37], B[39], "floating_keys", 35, 4.0, (-2.55, -1.10, 1.25), (-2.52, -1.02, 1.24), (-2.0, 0.18, 0.93),
      focus=V((-2.05, -0.35, 0.93)), engine="CYCLES", exposure=0.5)
kshot(B[39], B[41], "reassemble", 28, 5.6, (-3.6, -3.3, 2.05), (-3.75, -3.45, 2.10), (0.0, 0.0, 1.15),
      focus=V((0.0, 0.0, 1.0)), engine="CYCLES", exposure=0.4)
# ---------------------------------------------------------------- D (bars 41-56)
low_front(B[41], B[43], 0.05, "chords_low_front")
pianist(B[43], B[47], -0.05)
from_end(B[47], B[49], "bass")
keys_side(B[49], B[53], 0.0, "cresc_side")
against_windows(B[53], B[55], "last_windows")
kshot(B[55], B[57], "pianist_pullback", 32, 4.0, (-1.88, 0.05, 1.12), (-2.10, 0.08, 1.30), (-1.20, 0.0, 0.77),
      exposure=0.25)
# ---------------------------------------------------------------- ending: moonlight on the keys
kshot(B[57], 91.0, "ending_moon_keys", 35, 2.8, (-1.33, -0.95, 0.815), (-1.38, -1.08, 0.86), (-1.30, 0.30, 0.745),
      focus=V((-1.30, -0.30, 0.74)), hide=("cheek_R",))

for i, s in enumerate(S):
    s["index"] = i + 1
    s["f0"] = int(math.ceil(s["t0"] * FPS - 1e-9))
    s["f1"] = int(math.ceil(s["t1"] * FPS - 1e-9))
SHOT_STARTS = [s["f0"] for s in S]


def shot_for_frame(frame):
    return S[max(0, bisect.bisect_right(SHOT_STARTS, frame) - 1)]


def _ease(u):
    u = min(1.0, max(0.0, u))
    sm = u * u * (3 - 2 * u)
    return 0.6 * u + 0.4 * sm          # never stops: velocity >= 0.6 of mean


def _interp_keys(keys, u):
    us = [k[0] for k in keys]
    if len(keys) == 2:
        e = _ease(u)
        return keys[0][1].lerp(keys[1][1], e), keys[0][2].lerp(keys[1][2], e)
    # Catmull-Rom through several keyframes, time-normalised
    u = min(1.0, max(0.0, u))
    i = max(0, min(len(keys) - 2, bisect.bisect_right(us, u) - 1))
    span = us[i + 1] - us[i]
    v = (u - us[i]) / span
    def cr(idx):
        p = [keys[max(0, min(len(keys) - 1, j))][idx] for j in (i - 1, i, i + 1, i + 2)]
        return 0.5 * ((2 * p[1]) + (-p[0] + p[2]) * v + (2 * p[0] - 5 * p[1] + 4 * p[2] - p[3]) * v * v
                      + (-p[0] + 3 * p[1] - 3 * p[2] + p[3]) * v ** 3)
    return cr(1), cr(2)


def camera(t, frame):
    s = shot_for_frame(frame)
    u = (t - s["t0"]) / (s["t1"] - s["t0"])
    if s["track"] and s["track"]["kind"] == "aim":
        pos, _ = _interp_keys([(k[0], k[1], k[1]) for k in s["keys"]], u)
        tgt = V((KEY_FRONT_X + 0.07, key_y_world_float(centroid(t)), 0.735))
    elif s["track"] and s["track"]["kind"] == "pov":
        tr = s["track"]
        y = key_y_world_float(centroid(t))
        pos = tr["eye"] + V((0.0, y * tr["follow"], 0.0)) + V((0.06 * (u - 0.5), 0, -0.03 * u))
        tgt = V((KEY_FRONT_X + 0.22, y * 0.85, 0.80))
    elif s["track"]:
        tr = s["track"]
        kf = centroid(t, top=(tr["kind"] == "keys_top"))
        y = key_y_world_float(kf)
        if tr["kind"] == "hammers":
            tgt = V((0.43 + KEY_FRONT_X, y * 1.05, 0.875))
        else:
            tgt = V((KEY_FRONT_X + 0.07, y, 0.735))
        drift = tr["drift"] * (u - 0.5)
        pos = tgt + tr["offset"] + drift
        tgt = tgt + tr["look"]
    else:
        pos, tgt = _interp_keys(s["keys"], u)
    f = s["focus"]
    if f is None or f == "target":
        fd = (tgt - pos).length
    elif isinstance(f, str) and f.startswith("rack:"):
        a, b = map(float, f.split(":")[1:])
        fd = a + (b - a) * _ease(u)
    else:
        fwd = (tgt - pos).normalized()
        fd = max(0.05, (f - pos).dot(fwd))
    return dict(pos=pos, target=tgt, lens=s["lens"], fstop=s["fstop"], focus=fd, shot=s)
