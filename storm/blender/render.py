"""Render frames of the storm film.

  blender -b storm/scene.blend -P storm/blender/render.py -- --times 3.8,41.15 --out storm/look
  blender -b storm/scene.blend -P storm/blender/render.py -- --from 0 --to 300 --out storm/frames

Each frame: the handler sets the whole scene from (t, frame) for every
motion-blur subframe; the shot of the integer frame picks camera + engine.
Existing frames are skipped (resumable).
"""
import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bpy  # noqa: E402

import anim  # noqa: E402
import shots  # noqa: E402
from lib import FPS  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--times", default="")
ap.add_argument("--frames", default="")
ap.add_argument("--from", dest="f_from", type=int, default=None)
ap.add_argument("--to", dest="f_to", type=int, default=None)
ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "frames"))
ap.add_argument("--engine", default="")          # force CYCLES / EEVEE
ap.add_argument("--samples", type=int, default=0)
ap.add_argument("--scale", type=int, default=100)
ap.add_argument("--prefix", default="f")
ap.add_argument("--force", action="store_true")
ap.add_argument("--noblur", action="store_true")
ap.add_argument("--nodof", action="store_true")
ap.add_argument("--preview", action="store_true")
args = ap.parse_args(argv)

sc = bpy.context.scene
# GPU device selection lives in user preferences, not in the .blend: set it here
_prefs = bpy.context.preferences.addons["cycles"].preferences
_prefs.compute_device_type = "METAL"
_prefs.get_devices()
for _d in _prefs.devices:
    _d.use = _d.type == "METAL"
print("CYCLES DEVICES:", [(_d.name, _d.type) for _d in _prefs.devices if _d.use], flush=True)
sc.cycles.device = "GPU"
rig = anim.Rig(sc)
cam = sc.camera
STATE = {"frame": 0}
FILL = sc.objects["macro_fill"]
BASE_EXPOSURE = sc.view_settings.exposure

CYCLES_SAMPLES = {"macro": 128, "explode": 96, "fly_through": 96}
if "--preview" in sys.argv:
    CYCLES_SAMPLES = {"macro": 64, "explode": 48, "fly_through": 48}


def set_camera(t, frame):
    c = shots.camera(t, frame)
    cam.location = c["pos"]
    cam.rotation_euler = (c["target"] - c["pos"]).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = c["lens"]
    cam.data.dof.focus_distance = c["focus"]
    cam.data.dof.aperture_fstop = c["fstop"]
    cam.data.clip_start = 0.002 if c["lens"] >= 100 else 0.03
    cam.data.dof.use_dof = not args.nodof
    sh = c["shot"]
    if sh["fill"]:
        off, watts, size = sh["fill"]
        FILL.hide_render = False
        FILL.location = c["target"] + off
        FILL.rotation_euler = (c["target"] - FILL.location).to_track_quat("-Z", "Y").to_euler()
        FILL.data.energy = watts
        FILL.data.size = size
    else:
        FILL.hide_render = True
    sc.view_settings.exposure = BASE_EXPOSURE + sh["exposure"]
    sc.render.motion_blur_shutter = sh["shutter"]
    return sh


def handler(scene, depsgraph=None):
    t = (scene.frame_current + scene.frame_subframe) / FPS
    rig.apply(t, STATE["frame"])
    set_camera(t, STATE["frame"])


bpy.app.handlers.frame_change_pre.clear()
bpy.app.handlers.frame_change_pre.append(handler)

frames = []
if args.times:
    frames = [int(math.ceil(float(x) * FPS - 1e-9)) for x in args.times.split(",")]
elif args.frames:
    frames = [int(x) for x in args.frames.split(",")]
else:
    frames = list(range(args.f_from or 0, (args.f_to if args.f_to is not None else 2730)))

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
sc.render.resolution_percentage = args.scale
if args.noblur:
    sc.render.use_motion_blur = False

ALL_HIDE = sorted({n for sh in shots.S for n in sh["hide"]})
t_start = time.time()
for i, f in enumerate(frames):
    path = out / f"{args.prefix}_{f:05d}.png"
    if path.exists() and not args.force:
        continue
    STATE["frame"] = f
    s = shots.shot_for_frame(f)
    eng = args.engine or s["engine"]
    sc.render.engine = "CYCLES" if eng == "CYCLES" else "BLENDER_EEVEE"
    if eng == "CYCLES":
        key = "macro" if s["name"].startswith("macro") else s["name"]
        sc.cycles.samples = args.samples or CYCLES_SAMPLES.get(key, 128)
    elif args.samples:
        sc.eevee.taa_render_samples = args.samples
    for name in ALL_HIDE:
        sc.objects[name].hide_render = name in s["hide"]
    sc.frame_set(f)
    handler(sc)
    sc.render.filepath = str(path)
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    dt = time.time() - t0
    print(f"FRAME {f} t={f / FPS:.3f} shot={s['index']}:{s['name']} {eng} {dt:.1f}s "
          f"[{i + 1}/{len(frames)}, elapsed {(time.time() - t_start) / 60:.1f} min]", flush=True)
