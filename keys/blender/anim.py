"""Bars 1-12 "keys" film: the state of the scene as a pure function of time.

  keys        velocity-shaped press (loud = faster travel, deeper), a felt
              bottom-out bump, held depth, damped release with a small
              overshoot above rest
  music light a hard spot that follows where the music is on the keyboard
              (critically damped spring on the velocity-weighted pitch
              centroid) and opens / brightens with the loudness
  ending      the landing chord's keys rise at RELEASE; the light narrows and
              fades to black after them
"""
import bisect
import math

import bpy
from mathutils import Matrix, Vector

from lib import DURATION, LEAD, load_data

DATA = load_data()
T_RELEASE = DATA["release"] + LEAD           # landing chord keys rise
T_DARK0, T_DARK1 = T_RELEASE + 0.15, T_RELEASE + 1.75
KEY_FRONT_X = -1.37
W = 0.0235
_BLACK = {1: -0.10, 3: 0.10, 6: -0.13, 8: 0.0, 10: 0.13}


def smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


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


KEY_Y = [-key_x_local(k) for k in range(88)]      # world y of each key's centre


# ------------------------------------------------------------------ notes
class Note:
    __slots__ = ("on", "off", "v", "vis_off", "rel", "travel", "press0", "t_full")


KEYS = [[] for _ in range(88)]
for d in DATA["notes"]:
    n = Note()
    n.on, n.off, n.v = d["on"] + LEAD, d["off"] + LEAD, d["v"]
    KEYS[d["p"] - 21].append(n)
for lst in KEYS:
    lst.sort(key=lambda n: n.on)
    for i, n in enumerate(lst):
        nxt = lst[i + 1].on if i + 1 < len(lst) else 1e9
        ioi = nxt - n.on
        n.vis_off = min(n.off, n.on + 0.55 * ioi)       # repeated notes visibly re-press
        n.rel = min(0.065, 0.35 * ioi)
        n.travel = 0.040 - 0.024 * (n.v / 127)          # loud = fast
        n.press0 = n.on - 0.80 * n.travel
        n.t_full = n.on + 0.20 * n.travel
PRESS0 = [[n.press0 for n in lst] for lst in KEYS]


def key_depth_frac(k, t, _nested=False):
    """0 up .. 1 bottomed (>1 felt compression, <0 overshoot above rest)."""
    i = bisect.bisect_right(PRESS0[k], t) - 1
    if i < 0:
        return 0.0
    n = KEYS[k][i]
    start = key_depth_frac(k, n.press0 - 1e-6, True) if (i > 0 and not _nested) else 0.0
    if t < n.t_full:
        u = (t - n.press0) / (n.t_full - n.press0)
        e = u * u * (3 - 2 * u) if u > 0 else 0.0
        return start + (1 - start) * e
    if t < n.vis_off:
        r = t - n.t_full
        bump = 0.075 * (n.v / 127) * (r / 0.006) * math.exp(1 - r / 0.006)   # felt bottom-out
        return 1.0 + bump
    r = t - n.vis_off
    tau = max(0.012, n.rel * 0.38)
    return math.exp(-r / tau) * math.cos(math.pi * r / (2.6 * tau))


def key_depth_m(k, t):
    i = bisect.bisect_right(PRESS0[k], t) - 1
    v = KEYS[k][i].v if i >= 0 else 64
    return key_depth_frac(k, t) * 0.0100 * (0.60 + 0.40 * v / 127)


# ------------------------------------------------------------------ music light
DT = 1 / 240
_ons = sorted(((d["on"] + LEAD, d["p"] - 21, d["v"]) for d in DATA["notes"]))
_on_t = [o[0] for o in _ons]


def _raw(t):
    """(velocity-weighted key centroid, loudness) around time t."""
    i0 = bisect.bisect_left(_on_t, t - 0.6)
    i1 = bisect.bisect_right(_on_t, t + 0.06)
    sw = sp = loud = 0.0
    for on, k, v in _ons[i0:i1]:
        w = (v / 127) ** 2 * math.exp(-0.5 * ((on - t + 0.04) / 0.16) ** 2)
        sw += w
        sp += w * k
        if on <= t + 0.012:
            loud += (v / 127) ** 2 * math.exp(-(t - on) / 0.30)
    return (sp / sw if sw > 1e-6 else None), loud


def _precompute():
    n = int(DURATION / DT) + 2
    cen, loud = [], []
    last = 40.0
    for i in range(n):
        c, l = _raw(i * DT)
        last = c if c is not None else last
        cen.append(last); loud.append(l)
    # critically damped spring toward the centroid (the light has weight)
    w = 2 * math.pi * 1.1
    x, vx = cen[0], 0.0
    pos = []
    for c in cen:
        a = w * w * (c - x) - 2 * w * vx
        vx += a * DT; x += vx * DT
        pos.append(x)
    # loudness: normalise, fast attack / slow release
    ref = sorted(loud)[int(0.96 * len(loud))] or 1.0
    env, out = 0.0, []
    for l in loud:
        l = min(1.2, l / ref)
        k = 1 - math.exp(-DT / (0.025 if l > env else 0.35))
        env += k * (l - env)
        out.append(env)
    return pos, out


LIGHT_POS, LIGHT_LOUD = _precompute()


def _grid(arr, t):
    f = max(0.0, min(len(arr) - 1.001, t / DT))
    i = int(f); u = f - i
    return arr[i] * (1 - u) + arr[i + 1] * u


def light_key(t):
    return _grid(LIGHT_POS, t)


def loudness(t):
    return _grid(LIGHT_LOUD, t)


def key_y_float(kf):
    k0 = int(max(0, min(86, math.floor(kf))))
    u = kf - k0
    return KEY_Y[k0] * (1 - u) + KEY_Y[k0 + 1] * u


def darkness(t):
    """1 = full light .. 0 = black (the ending)."""
    return 1.0 - smooth((t - T_DARK0) / (T_DARK1 - T_DARK0))


# ------------------------------------------------------------------ the reveal
T_RENDER = 2.75            # the first sforzando: the wireframe becomes the render


def wipe_y(t):
    """Everything is its code-generated wireframe until the first sforzando."""
    return 5.0 if t < T_RENDER else -5.0


def build_scale(k, t):
    """Opening: the keys are instantiated one by one, bass to treble, each just
    ahead of the first rising arpeggio (key k appears at 0.9*k/87 s)."""
    t_app = 0.9 * k / 87
    u = (t - t_app) / 0.07
    if u >= 1.0:
        return 1.0
    if u <= 0.0:
        return 0.0
    return u * u * (3 - 2 * u) * (1.0 + 0.12 * math.sin(math.pi * u))


# ------------------------------------------------------------------ scene binding
class Rig:
    """Keys + a fixed, broad key light (no moving pool).  The light only fades
    at the very end, after the fermata chord's keys rise."""

    def __init__(self, scene):
        self.scene = scene
        self.keys = {o["note"]: o for o in scene.objects if o.get("part") == "key"}
        self.rest = {k: o.matrix_basis.copy() for k, o in self.keys.items()}
        self.lights = [(o, o.data.energy) for o in scene.objects
                       if o.type == "LIGHT" and o.name in ("key_light", "top_light")]
        self.back = scene.objects["back_light"]
        self.wipes = [n for m in bpy.data.materials if m.node_tree
                      for n in m.node_tree.nodes if n.name == "U_wipe"]

    def apply(self, t, shot):
        w = wipe_y(t)
        for n in self.wipes:
            n.outputs[0].default_value = w
        for k, o in self.keys.items():
            ang = math.asin(max(-0.2, min(0.2, key_depth_m(k, t) / 0.25)))
            sc = build_scale(k, t) if t < 1.0 else 1.0
            o.matrix_basis = self.rest[k] @ Matrix.Scale(max(sc, 1e-4), 4) @ Matrix.Rotation(ang, 4, "X")
        dk = darkness(t)
        for o, e0 in self.lights:
            o.data.energy = e0 * dk * shot["light"]
        bl = shot.get("back")
        self.back.hide_render = not bl
        if bl:
            pos, aim, watts = bl
            self.back.location = pos
            self.back.rotation_euler = (aim - pos).to_track_quat("-Z", "Y").to_euler()
            self.back.data.energy = watts * dk
