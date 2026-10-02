"""Bars 1-12 keys film: five shots, cut on phrase landings.

  1  0.00-2.75   hook      low macro along the keys, the first wave runs away from us
  2  2.75-5.96   ride      slide along the keys, landing on the bar-4 sforzando chord
  3  5.96-8.82   skyline   key-top height, 135 mm, backlit: every press notches the skyline
  4  8.82-11.68  mirror    tight pianist's view; the fallboard mirrors every key
  5  11.68-21.0  finale    macro on the bar-9 chords, a slow pull to the landing chord,
                           keys rise and the light dies

Camera keys are [(u, pos, target)] in world space; u in 0..1 over the shot.
Segments ease in/out (smoothstep) so arrivals land on their chord.
"""
import bisect
import math

from mathutils import Vector

from lib import FPS, LEAD

V = Vector
KEY_FRONT_X = -1.37
W = 0.0235
_BLACK = {1: -0.10, 3: 0.10, 6: -0.13, 8: 0.0, 10: 0.13}


def key_y(p):
    """world y of the key for MIDI pitch p"""
    k = p - 21
    wi = 0
    for j in range(k + 1):
        pc = (j + 21) % 12
        if pc in _BLACK:
            if j == k:
                return -(-26 * W + wi * W + _BLACK[pc] * W)
        else:
            if j == k:
                return -(-26 * W + wi * W + W / 2)
            wi += 1


B = 4 * 60 / 168
bar = lambda b: (b - 1) * B + LEAD
S = []


def shot(t0, t1, name, lens, fstop, keys, focus=None, light=1.0, back=None, crop45=0.5, follow=None, shift=0.0):
    """focus: None (target) | Vector | "light" (focus rides the music light's pool)
    follow: camera rides the music light: dict(offset=..., look=..., weight=0..1)"""
    S.append(dict(t0=t0, t1=t1, name=name, lens=lens, fstop=fstop, keys=keys, focus=focus,
                  light=light, back=back, crop45=crop45, follow=follow, shift=shift))


SF4 = 5.607                                     # bar-4 sforzando (video time)
y_sf4 = key_y(76)                               # middle of its right-hand chord (68-80)
y_b9 = key_y(78)                                # bar-9 right-hand chord (72-84)
y_land = key_y(62)                              # bar-13 downbeat chord (56-68)
y_ferm = key_y(44)                              # the fermata chord (32-44-56)

# 1 the code plays the piano: wireframe keys (built key by key) on the right,
#   the live source + note log on the left (overlay); lens shift makes room
shot(0.0, 2.75, "code_wire", 40, 5.6, [
    (0.0, V((-1.70, -0.30, 0.815)), V((-1.26, 0.08, 0.724))),
    (1.0, V((-1.69, -0.20, 0.810)), V((-1.26, 0.08, 0.724)))], shift=-0.22)
# 2 slide along the keys, landing on the bar-4 sforzando
u_arr = (SF4 - 2.75) / (bar(5) - 2.75)
shot(2.75, bar(5), "ride", 50, 2.8, [
    (0.0, V((-1.76, key_y(52) - 0.10, 0.835)), V((-1.30, key_y(52), 0.731))),
    (u_arr, V((-1.75, y_sf4 - 0.10, 0.830)), V((-1.30, y_sf4, 0.731))),
    (1.0, V((-1.745, y_sf4 - 0.11, 0.828)), V((-1.30, y_sf4 - 0.01, 0.731)))])
# 3 key-top height, long lens, keys lit + a backlit edge
y_sky = key_y(73)
shot(bar(5), bar(7), "skyline", 135, 4.0, [
    (0.0, V((-2.32, y_sky + 0.02, 0.745)), V((-1.37, y_sky, 0.729))),
    (1.0, V((-2.28, y_sky + 0.01, 0.744)), V((-1.37, y_sky - 0.01, 0.729)))],
    back=(V((-1.255, y_sky, 0.795)), V((-1.60, y_sky, 0.735)), 6.0))
# 4 the pianist's view; the fallboard mirrors the keys
y_mir = key_y(66)
shot(bar(7), bar(9), "mirror", 40, 4.0, [
    (0.0, V((-1.82, y_mir + 0.03, 0.99)), V((-1.25, y_mir, 0.752))),
    (1.0, V((-1.77, y_mir + 0.02, 0.965)), V((-1.25, y_mir, 0.752)))])
# 5 macro on the bar-9 chords, pulling back along the descending line
shot(bar(9), bar(13), "chords", 85, 3.2, [
    (0.0, V((-1.70, y_b9 - 0.06, 0.790)), V((-1.31, y_b9, 0.729))),
    (1.0, V((-2.10, y_land - 0.05, 0.92)), V((-1.31, y_land, 0.735)))])
# 6 bars 13-14: the fermata chord slams, holds, the keys rise, the light dies
shot(bar(13), 24.0, "fermata", 40, 2.8, [
    (0.0, V((-1.80, y_ferm - 0.26, 0.845)), V((-1.28, y_ferm + 0.02, 0.722))),
    (1.0, V((-1.72, y_ferm - 0.22, 0.825)), V((-1.28, y_ferm + 0.02, 0.722)))])

for i, s in enumerate(S):
    s["index"] = i + 1
    s["f0"] = int(math.ceil(s["t0"] * FPS - 1e-9))
    s["f1"] = int(math.ceil(s["t1"] * FPS - 1e-9))
STARTS = [s["f0"] for s in S]


def shot_for_frame(frame):
    return S[max(0, bisect.bisect_right(STARTS, frame) - 1)]


def _seg(keys, u):
    us = [k[0] for k in keys]
    u = min(1.0, max(0.0, u))
    i = max(0, min(len(keys) - 2, bisect.bisect_right(us, u) - 1))
    v = (u - us[i]) / (us[i + 1] - us[i])
    # two-key shots keep moving (mixed linear/eased); multi-key shots ease into each key
    e = (0.55 * v + 0.45 * v * v * (3 - 2 * v)) if len(keys) == 2 else v * v * (3 - 2 * v)
    return keys[i][1].lerp(keys[i + 1][1], e), keys[i][2].lerp(keys[i + 1][2], e)


def camera(t, frame):
    s = shot_for_frame(frame)
    u = (t - s["t0"]) / (s["t1"] - s["t0"])
    pos, tgt = _seg(s["keys"], u)
    fwd = (tgt - pos).normalized()
    if s["focus"] is None:
        fd = (tgt - pos).length
    else:
        fd = max(0.05, (s["focus"] - pos).dot(fwd))
    return dict(pos=pos, target=tgt, lens=s["lens"], fstop=s["fstop"], focus=fd, shot=s, shift=s.get("shift", 0.0))
