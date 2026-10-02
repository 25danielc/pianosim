"""Deterministic state of the whole film as a function of time.

Everything here is a pure function of (t, render_frame):
  t             continuous video time in seconds (subframes for motion blur)
  render_frame  the integer frame being rendered (lightning, shot choice and
                anything that must not smear across a cut use this)

apply(scene, t, frame) pushes the state into the Blender scene.
"""
import bisect
import math
import zlib

import bpy
from mathutils import Euler, Matrix, Vector

from lib import FPS, load_data, mulberry32

NOTES, EMAP = load_data()
LEAD = EMAP["lead"]
T_EXPLODE = next(a["t"] for a in EMAP["accents"] if abs(a["t"] - EMAP["climax"]["t"]) < 1e-6)
# the piano hangs apart from the bar-33 ff through the bar-37 ff (a kick outward)
# and snaps back together on the first f chord of bar 41
T_KICK = EMAP["reassemble"]["t"]                                    # bar 37 ff
T_REASSEMBLE = next(a["t"] for a in EMAP["accents"] if a["bar"] == 41)
T_SNAP0 = T_REASSEMBLE - 0.40
T_CADENCE = EMAP["cadence_t"]       # spot cuts to black here
T_CLEAR0, T_CLEAR1 = 84.6, 86.6     # clouds part after the ring-out


def smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def smoother(x):
    x = min(1.0, max(0.0, x))
    return x * x * x * (x * (6 * x - 15) + 10)


# ------------------------------------------------------------------ notes per key
class Note:
    __slots__ = ("k", "on", "off", "v", "vis_off", "rel", "fly", "press0", "damp_off")


KEYS = [[] for _ in range(88)]
for n in NOTES["notes"]:
    nn = Note()
    nn.k = n["p"] - 21
    nn.on = n["on"] + LEAD
    nn.off = n["off"] + LEAD
    nn.v = n["v"]
    KEYS[nn.k].append(nn)
PEDAL = [(p["on"] + LEAD, p["off"] + LEAD) for p in NOTES["pedal"]]


def pedal_down(t):
    return any(a <= t < b for a, b in PEDAL)


for lst in KEYS:
    lst.sort(key=lambda n: n.on)
    for i, n in enumerate(lst):
        nxt = lst[i + 1].on if i + 1 < len(lst) else 1e9
        ioi = nxt - n.on
        # a repeated note must visibly come back up before it is struck again
        n.vis_off = min(n.off, n.on + 0.55 * ioi)
        n.rel = min(0.065, 0.35 * ioi)
        n.fly = 0.050 - 0.026 * (n.v / 127)
        n.press0 = n.on - (0.030 - 0.012 * (n.v / 127))
        # the damper falls when the key is up and the pedal is not holding it
        d = n.off
        for a, b in PEDAL:
            if a <= d < b:
                d = b
        n.damp_off = d
KEY_ONS = [[n.press0 for n in lst] for lst in KEYS]
NOTE_ONS = [[n.on for n in lst] for lst in KEYS]
FLY_ONS = [[n.on - n.fly for n in lst] for lst in KEYS]


def _current(k, t):
    """Index of the note governing key k at time t (latest press start <= t)."""
    i = bisect.bisect_right(KEY_ONS[k], t) - 1
    return i


def key_depth_frac(k, t, _depth=0):
    """0 = up .. 1 = fully down (negative = overshoot above rest)."""
    lst = KEYS[k]
    i = _current(k, t)
    if i < 0:
        return 0.0
    n = lst[i]
    start = 0.0
    if i > 0 and _depth == 0:
        start = key_depth_frac(k, n.press0 - 1e-6, 1)
    t_full = n.on + 0.008
    if t < t_full:
        u = (t - n.press0) / (t_full - n.press0)
        return start + (1 - start) * smooth(u)
    if t < n.vis_off:
        return 1.0
    r = t - n.vis_off
    tau = max(0.012, n.rel * 0.38)
    return math.exp(-r / tau) * math.cos(math.pi * r / (2.6 * tau))


def key_depth_m(k, t):
    lst = KEYS[k]
    i = _current(k, t)
    v = lst[i].v if i >= 0 else 64
    return key_depth_frac(k, t) * 0.0098 * (0.55 + 0.45 * v / 120)


def hammer_frac(k, t, _depth=0):
    """0 = rest .. 1 = touching the string."""
    lst = KEYS[k]
    best = bisect.bisect_right(FLY_ONS[k], t) - 1     # latest note whose flight began
    if best < 0:
        return 0.0
    n = lst[best]
    c = 0.55
    if t < n.on:
        h0 = 0.0
        if best > 0 and _depth == 0:
            h0 = hammer_frac(k, n.on - n.fly - 1e-6, 1)
        u = (t - (n.on - n.fly)) / n.fly
        return h0 + (1 - h0) * u * u
    r = t - n.on
    h = c + (1 - c) * math.exp(-r / 0.014)
    if t > n.vis_off:
        h *= math.exp(-(t - n.vis_off) / 0.02)
    return h


def felt_squash(k, t):
    lst = KEYS[k]
    i = bisect.bisect_right(NOTE_ONS[k], t + 0.004) - 1
    if i < 0:
        return 0.0
    n = lst[i]
    r = t - n.on
    if r < -0.004:
        return 0.0
    a = smooth((r + 0.004) / 0.004)
    return a * math.exp(-max(0.0, r) / 0.030) * (0.35 + 0.65 * n.v / 127)


def damper_lift(k, t):
    """0 = resting on the strings .. 1 = lifted."""
    lift = 0.0
    lst = KEYS[k]
    i = _current(k, t)
    for idx in range(max(0, i - 3), min(len(lst), i + 2)):
        n = lst[idx]
        a = smooth((t - (n.on - 0.022)) / 0.018)
        b = 1 - smooth((t - n.vis_off) / 0.05)
        lift = max(lift, a * b)
    for a0, b0 in PEDAL:
        lift = max(lift, smooth((t - a0) / 0.03) * (1 - smooth((t - b0) / 0.06)))
    return lift


def string_amp(k, t):
    """Visible vibration envelope (0..~1)."""
    amp = 0.0
    lst = KEYS[k]
    i = bisect.bisect_right(NOTE_ONS[k], t) - 1
    for idx in range(max(0, i - 2), i + 1):
        n = lst[idx]
        r = t - n.on
        if r < 0:
            continue
        tau = 0.9 if k < 40 else (0.5 if k < 64 else 0.25)
        e = (n.v / 127) * math.exp(-r / tau) * smooth(r / 0.004)
        if t > n.damp_off and k < 69:
            e *= math.exp(-(t - n.damp_off) / 0.035)
        amp += e
    return min(1.2, amp)


def pedal_frac(t):
    p = 0.0
    for a, b in PEDAL:
        p = max(p, smooth((t - a + 0.02) / 0.04) * (1 - smooth((t - b) / 0.06)))
    return p


# ------------------------------------------------------------------ storm & light
_grid = EMAP["loudness"]["t"]
_storm = EMAP["storm"]


def storm(t):
    i = bisect.bisect_right(_grid, t) - 1
    if i < 0:
        return _storm[0]
    if i >= len(_grid) - 1:
        return _storm[-1]
    u = (t - _grid[i]) / (_grid[i + 1] - _grid[i])
    return _storm[i] * (1 - u) + _storm[i + 1] * u


def moon_cover(t):
    """Extra occlusion of the moon beyond the cloud field (story beats)."""
    c = 0.0
    c = max(c, 0.25 * smooth((t - 9.0) / 8.0))                  # clouds reach the moon
    c = max(c, 0.25 + 0.55 * smooth((t - 18.9) / 1.2))          # bar 14 fermata: swallowed
    c = max(c, 0.80 + 0.20 * smooth((t - 29.7) / 6.0))          # act 2: gone
    if t > T_CLEAR0:                                            # ending: clouds part
        c = c * (1 - smoother((t - T_CLEAR0) / (T_CLEAR1 - T_CLEAR0)))
    return c


def clouds(t):
    c = 0.15 + 0.85 * storm(t)
    if t > T_CLEAR0:
        c = c * (1 - 0.8 * smoother((t - T_CLEAR0) / (T_CLEAR1 - T_CLEAR0)))
    return c


def rain(t):
    r = smooth((t - 21.1) / 3.0) * (0.10 + 0.75 * smooth((storm(t) - 0.25) / 0.6))
    if t > T_CADENCE:
        r *= 1 - smooth((t - T_CADENCE - 2.0) / 4.0)
    return r


BIG = {round(T_EXPLODE, 3): 1.6, round(T_KICK, 3): 1.35, round(T_REASSEMBLE, 3): 1.35}
LIGHTNING = []          # (frame0, pattern{offset: level}, azimuth, elevation, sky_x, bolt)
for a in EMAP["accents"]:
    rnd = mulberry32(int(a["t"] * 1000))
    st = storm(a["t"])
    big = BIG.get(round(a["t"], 3), 1.0)
    if abs(a["t"] - 19.18) < 0.05 or abs(a["t"] - 74.14) < 0.05 or abs(a["t"] - 41.11) < 0.05:
        big = 1.25
    level = a["strength"] * (0.30 + 0.70 * st) * big
    near = st > 0.45 or big > 1.0
    pat = {0: 1.0, 1: 0.42, 2: 0.78, 3: 0.12} if near else {0: 0.75, 1: 0.30, 2: 0.08}
    sec = 5 + int(rnd() * 4)
    pat[sec] = max(pat.get(sec, 0), 0.24)
    pat[sec + 1] = max(pat.get(sec + 1, 0), 0.10)
    f0 = int(math.ceil(a["t"] * FPS - 1e-9))
    LIGHTNING.append({
        "f0": f0, "t": a["t"], "pat": {k: v * level for k, v in pat.items()},
        "az": (rnd() - 0.5) * 0.5, "el": math.radians(25 + rnd() * 8),
        "sky_x": (rnd() - 0.5) * 1.2, "bolt": (big > 1.0) and near,
        "bolt_i": int(rnd() * 3), "bolt_x": (rnd() - 0.5) * 50,
    })
# the opening downbeat: a distant flicker inside the clouds only (sky, no sun)
OPEN_FLICKER = {8: 0.10, 9: 0.05, 13: 0.06}


def lightning(frame):
    """(sun level, sky flash level, event dict or None) for an integer frame."""
    best, lvl = None, 0.0
    for e in LIGHTNING:
        off = frame - e["f0"]
        if off in e["pat"] and e["pat"][off] > lvl:
            lvl, best = e["pat"][off], e
    sky = lvl + OPEN_FLICKER.get(frame, 0.0)
    return lvl, sky, best


# ------------------------------------------------------------------ dust
DUST_EVENTS = sorted({round(a["t"], 4): a["strength"] for a in EMAP["accents"]}.items())
_chords = {}
for n in NOTES["notes"]:
    key = round(n["on"] + LEAD, 3)
    _chords[key] = max(_chords.get(key, 0), n["v"])
for tt, v in _chords.items():
    if v >= 104 and all(abs(tt - e[0]) > 0.05 for e in DUST_EVENTS):
        DUST_EVENTS.append((tt, 0.6))
DUST_EVENTS.sort()
DUST_T = [e[0] for e in DUST_EVENTS]


class Dust:
    def __init__(self, obj):
        import numpy as np
        self.np = np
        self.obj = obj
        self.rest = np.array(obj["rest"], dtype=np.float64).reshape(-1, 3)
        n = len(self.rest)
        rnd = mulberry32(99)
        self.h = np.array([0.004 + 0.030 * rnd() ** 2 for _ in range(n)])
        self.resp = np.array([1.0 if rnd() < 0.65 else 0.0 for _ in range(n)])
        self.dx = np.array([(rnd() - 0.5) * 0.012 for _ in range(n)])
        self.dy = np.array([(rnd() - 0.5) * 0.012 for _ in range(n)])
        self.tau = np.array([0.5 + 1.2 * rnd() for _ in range(n)])

    def apply(self, t):
        np = self.np
        z = np.zeros(len(self.rest)); x = np.zeros_like(z); y = np.zeros_like(z)
        i = bisect.bisect_right(DUST_T, t)
        for te, st in DUST_EVENTS[max(0, i - 4):i]:
            r = t - te
            if r > 6.0:
                continue
            up = st * self.resp * (1 - np.exp(-r / 0.022)) * np.exp(-r / self.tau)
            z = np.maximum(z, self.h * up)
            x += self.dx * st * self.resp * (1 - np.exp(-r / 0.3)) * np.exp(-r / 2.5)
            y += self.dy * st * self.resp * (1 - np.exp(-r / 0.3)) * np.exp(-r / 2.5)
        co = self.rest + np.stack([x, y, z], axis=1)
        self.obj.data.vertices.foreach_set("co", co.ravel())
        self.obj.data.update()


# ------------------------------------------------------------------ explosion
EX_HAMMER_Z, EX_STRING_Z, EX_ACT_Y = 0.66, 0.84, -0.25


def explode(t):
    if t < T_EXPLODE:
        return 0.0
    if t < T_SNAP0:
        u = (t - T_EXPLODE) / 2.6
        e = 1 - (1 - min(u, 1.0)) ** 3
        e = e + 0.06 * min(1.0, max(0.0, t - T_EXPLODE - 2.6) / 8.0)
        if t >= T_KICK:
            r = t - T_KICK
            e += 0.10 * (1 - math.exp(-r / 0.03)) * math.exp(-r / 0.45)
        return e
    e0 = explode(T_SNAP0 - 1e-6)
    if t < T_REASSEMBLE:
        u = (t - T_SNAP0) / (T_REASSEMBLE - T_SNAP0)
        return e0 * (1 - u ** 3)
    return 0.0


def explode_settle(t):
    """Tiny downward bump as everything lands (metres)."""
    if t < T_REASSEMBLE:
        return 0.0
    r = t - T_REASSEMBLE
    return -0.004 * math.exp(-r / 0.05) * math.sin(r * 2 * math.pi / 0.12 + math.pi / 2) if r < 0.4 else 0.0


# ------------------------------------------------------------------ scene binding
class Rig:
    """Caches object handles and per-part explosion vectors."""

    def __init__(self, scene):
        self.scene = scene
        objs = [o for o in scene.objects]
        self.parts = [o for o in objs if "part" in o.keys() and o.parent and o.parent.name == "Piano"]
        self.keys = {o["note"]: o for o in self.parts if o["part"] == "key"}
        self.hammers = {o["note"]: o for o in self.parts if o["part"] == "hammer"}
        self.dampers = {o["note"]: o for o in self.parts if o["part"] == "damper"}
        self.strings = {o["note"]: o for o in self.parts if o["part"] == "strings"}
        self.pedals = {o["note"]: o for o in self.parts if o["part"] == "pedal"}
        self.rest = {o.name: o.matrix_basis.copy() for o in self.parts}
        self.ex = {}
        for o in self.parts:
            self.ex[o.name] = self.explode_vector(o)
        self.lid = next(o for o in self.parts if o["part"] == "lid")
        self.hammer_strike = {k: o["strike"] for k, o in self.hammers.items()}
        self.dust = Dust(scene.objects["dust"])
        self.uniforms = []
        for m in bpy.data.materials:
            if m.node_tree:
                for n in m.node_tree.nodes:
                    if n.name.startswith("U_"):
                        self.uniforms.append((n.name[2:], n))
        w = scene.world
        for n in w.node_tree.nodes:
            if n.name.startswith("U_"):
                self.uniforms.append((n.name[2:], n))
        self.spot = scene.objects["spot"]
        self.moon = scene.objects["moonlight"]
        self.light = scene.objects["lightning"]
        self.bolts = [scene.objects[f"bolt_{i}"] for i in range(3)]
        self.spot_energy = self.spot.data.energy

    def explode_vector(self, o):
        """(offset in piano-local metres, euler radians, bob phase)"""
        rnd = mulberry32(zlib.crc32(o.name.encode()) + 17)
        kind = o["part"]
        loc = self.rest[o.name].to_translation()
        ctr = self.center(o)
        sp = 0.55
        if kind in ("key", "hammer", "damper", "strings"):
            k = o["note"]
            phase = k * 0.07
            if kind == "key":
                d = Vector((loc.x * sp, -0.85 - 0.03 * (k % 7) / 7, 0.20 + 0.02 * o.get("black", 0)))
                r = Euler(((rnd() - 0.5) * 0.06, (rnd() - 0.5) * 0.04, (rnd() - 0.5) * 0.05))
            elif kind == "hammer":
                d = Vector((loc.x * sp, EX_ACT_Y, EX_HAMMER_Z)); r = Euler((0, 0, 0))
            elif kind == "strings":
                hx = self.scene.objects["Piano"]["strings_meta"][k][0]
                d = Vector((hx * sp, EX_ACT_Y, EX_STRING_Z)); r = Euler((0, 0, 0))
            else:
                d = Vector((loc.x * sp, EX_ACT_Y, 1.10)); r = Euler((0, 0, 0))
            return d, r, phase
        table = {
            "plate": (Vector((0.10, 0.60, 1.45)), Euler((0.20, -0.12, 0.05))),
            "pins": (Vector((0.10, 0.60, 1.45)), Euler((0.20, -0.12, 0.05))),
            "soundboard": (Vector((0, 0.35, 0.42)), Euler((-0.05, 0.03, 0.0))),
            "dust": (Vector((0, 0.35, 0.42)), Euler((-0.05, 0.03, 0.0))),
            "rim": (Vector((0, 0.25, -0.18)), Euler((0, 0, 0))),
            "bottom": (Vector((0, 0.25, -0.40)), Euler((0, 0, 0))),
            "lid": (Vector((-0.80, 0.95, 1.55)), Euler((0.20, 0.50, 0.08))),
            "stick": (Vector((0.95, 0.30, 1.25)), Euler((0.35, 0.25, 0.45))),
            "keybed": (Vector((0, -0.30, 0.02)), Euler((0, 0, 0))),
            "keyslip": (Vector((0, -0.95, 0.12)), Euler((0.15, 0, 0))),
            "fallboard": (Vector((0, -0.25, 0.60)), Euler((0.35, 0, 0))),
            "desk": (Vector((0, -0.10, 1.05)), Euler((-0.30, 0, 0.05))),
            "lyre": (Vector((0, -0.60, 0.08)), Euler((0.10, 0, 0))),
            "pedal": (Vector((0, -0.78, 0.10)), Euler((0.20, 0, 0))),
        }
        if kind == "cheek":
            s = 1 if ctr.x > 0 else -1
            return Vector((0.55 * s, -0.30, 0.10)), Euler((0, 0, 0.25 * s)), rnd() * 6
        if kind == "leg":
            # legs and their casters move together, outward from the case centre
            dirv = Vector((ctr.x, ctr.y - 1.2, 0)).normalized()
            return Vector((dirv.x * 0.65, dirv.y * 0.55, 0.12)), Euler((dirv.y * 0.22, -dirv.x * 0.22, 0)), 0.0
        d, r = table.get(kind, (Vector((0, 0, 0.3)), Euler((0, 0, 0))))
        return d.copy(), r.copy(), rnd() * 6

    def center(self, o):
        bb = [Vector(c) for c in o.bound_box]
        return self.rest[o.name] @ (sum(bb, Vector()) / 8)

    # ------------------------------------------------------------------
    def set_uniform(self, name, value):
        for n, node in self.uniforms:
            if n == name:
                node.outputs[0].default_value = value

    def apply(self, t, frame):
        e = explode(t)
        settle = explode_settle(t)
        hang = max(0.0, t - T_EXPLODE)
        for o in self.parts:
            if o["part"] == "bench":
                continue
            rest = self.rest[o.name]
            d, r, phase = self.ex[o.name]
            bob = Vector((0, 0, 0))
            if e > 0:
                bob = Vector((0.0, 0.004 * math.sin(hang * 1.3 + phase), 0.008 * math.sin(hang * 1.9 + phase)))
            off = d * e + bob * e + Vector((0, 0, settle))
            rot = Euler((r.x * e, r.y * e, r.z * e)).to_matrix().to_4x4()
            anim = Matrix.Identity(4)
            kind = o["part"]
            extra = Vector((0, 0, 0))
            if kind == "key":
                ang = math.asin(max(-0.2, min(0.2, key_depth_m(o["note"], t) / 0.25)))
                anim = Matrix.Rotation(ang, 4, "X")
            elif kind == "hammer":
                k = o["note"]
                h = hammer_frac(k, t)
                anim = Matrix.Rotation(o["strike"] * h, 4, "X")
                # while exploded the string floats further away: the hammer travels to it
                gap = (EX_STRING_Z - EX_HAMMER_Z) * e
                extra = Vector((0, 0, gap * h))
                sk = o.data.shape_keys.key_blocks.get("squash")
                if sk:
                    sk.value = felt_squash(k, t)
            elif kind == "jack":
                k = o["note"]
                ka = math.asin(max(-0.2, min(0.2, key_depth_m(k, t) / 0.25)))
                b = Vector(o["bot"]); tp = Vector(o["top"])
                # key back end rises as the front dips (pivot at y=0.25, z=0.703)
                rb = b - Vector((0, 0.25, 0.703))
                b = Vector((b.x, 0.25 + rb.y * math.cos(ka) - rb.z * math.sin(ka), 0.703 + rb.y * math.sin(ka) + rb.z * math.cos(ka)))
                hang_ = self.hammer_strike[k] * hammer_frac(k, t)
                rt = tp - Vector((0, 0.30, 0.830))
                tp = Vector((tp.x, 0.30 + rt.y * math.cos(hang_) - rt.z * math.sin(hang_), 0.830 + rt.y * math.sin(hang_) + rt.z * math.cos(hang_)))
                d = tp - b
                if e > 0.01:
                    o.matrix_basis = Matrix.Scale(0.0, 4)
                    continue
                q = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
                o.matrix_basis = Matrix.Translation(b) @ q @ Matrix.Diagonal((1, 1, d.length / o["rest_len"], 1))
                continue
            elif kind == "damper":
                anim = Matrix.Translation((0, 0, 0.009 * damper_lift(o["note"], t)))
            elif kind == "strings":
                k = o["note"]
                a = string_amp(k, t)
                sk = o.data.shape_keys.key_blocks.get("vib")
                if sk:
                    f = 61.0 + 7.0 * (k % 5)
                    sk.value = (1.6 if k < 28 else 1.1) * a * math.sin(2 * math.pi * f * t + k)
            elif kind == "pedal" and o["note"] == 2:
                anim = Matrix.Rotation(math.radians(5.5) * pedal_frac(t), 4, "X")
            base_loc = rest.to_translation()
            base_rot = rest.to_3x3().to_4x4()
            o.matrix_basis = Matrix.Translation(base_loc + off + extra) @ rot @ base_rot @ anim

        self.dust.apply(t)

        # ---- weather + light
        s = storm(t)
        lv, sky, ev = lightning(frame)
        self.set_uniform("time", t)
        self.set_uniform("cloud", clouds(t))
        self.set_uniform("moon_cover", moon_cover(t))
        self.set_uniform("rain", rain(t))
        self.set_uniform("flash", sky)
        self.set_uniform("moon", 1.0)
        if ev:
            self.set_uniform("flash_x", ev["sky_x"])
        mc = moon_cover(t)
        moon_e = 0.40 * (1 - mc) * (1 - 0.7 * smooth((clouds(t) - 0.3) / 0.6))
        if t > T_CLEAR0:
            moon_e = max(moon_e, 2.6 * smoother((t - T_CLEAR0 - 0.4) / 1.6))
        self.moon.data.energy = moon_e
        self.light.data.energy = 45.0 * lv
        if ev:
            az, el = ev["az"], ev["el"]
            dirv = Vector((math.sin(az), -math.cos(az) * math.cos(el), -math.sin(el)))
            self.light.rotation_euler = dirv.to_track_quat("-Z", "Y").to_euler()
        for i, b in enumerate(self.bolts):
            on = bool(ev and ev["bolt"] and ev["bolt_i"] == i and (frame - ev["f0"]) in (0, 2))
            b.hide_render = not on
            if on:
                b.location = (ev["bolt_x"], 140, 75)
        self.set_uniform("bolt", 1.0 if any(not b.hide_render for b in self.bolts) else 0.0)
        # spotlight: cut to black on the cadence chord (frame-exact)
        cut_frame = int(math.ceil(T_CADENCE * FPS - 1e-9))
        self.spot.data.energy = 0.0 if frame >= cut_frame else self.spot_energy
