"""Render the keys film (Cycles, 60 fps, open gate 1920x1350).

  blender -b keys/scene.blend -P keys/blender/render.py -- --from 0 --to 1260 --out keys/frames
  blender -b keys/scene.blend -P keys/blender/render.py -- --times 1.5,4.0 --out keys/look/x
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
ap.add_argument("--from", dest="f_from", type=int, default=0)
ap.add_argument("--to", dest="f_to", type=int, default=int(24.0 * FPS))
ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "frames"))
ap.add_argument("--samples", type=int, default=0)
ap.add_argument("--scale", type=int, default=100)
ap.add_argument("--force", action="store_true")
ap.add_argument("--engine", default="CYCLES")
ap.add_argument("--nohaze", action="store_true")
args = ap.parse_args(argv)

sc = bpy.context.scene
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "METAL"
prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == "METAL"
sc.cycles.device = "GPU"
sc.render.engine = "CYCLES" if args.engine == "CYCLES" else "BLENDER_EEVEE"
if args.samples:
    sc.cycles.samples = args.samples
    sc.eevee.taa_render_samples = args.samples
sc.render.resolution_percentage = args.scale
sc.objects["haze"].hide_render = True
# nothing inside the piano should ever show: no plate bar / tuning pins peeking over the desk
for name in ("plate_front", "tuning_pins", "plate_side", "plate_side.001"):
    sc.objects[name].hide_render = True

rig = anim.Rig(sc)
cam = sc.camera
STATE = {"frame": 0}


def handler(scene, depsgraph=None):
    t = (scene.frame_current + scene.frame_subframe) / FPS
    c = shots.camera(t, STATE["frame"])
    cam.location = c["pos"]
    cam.rotation_euler = (c["target"] - c["pos"]).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = c["lens"]
    cam.data.dof.focus_distance = c["focus"]
    cam.data.dof.aperture_fstop = c["fstop"]
    cam.data.shift_x = c["shift"]
    rig.apply(t, c["shot"])


bpy.app.handlers.frame_change_pre.clear()
bpy.app.handlers.frame_change_pre.append(handler)

if args.times:
    frames = [int(math.ceil(float(x) * FPS - 1e-9)) for x in args.times.split(",")]
elif args.frames:
    frames = [int(x) for x in args.frames.split(",")]
else:
    frames = list(range(args.f_from, args.f_to))
out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
CONVERGE_F0 = int(math.ceil(2.75 * FPS - 1e-9))
CONVERGE_N = 34
BASE_SAMPLES = sc.cycles.samples
t_start = time.time()
for i, f in enumerate(frames):
    path = out / f"f_{f:05d}.png"
    if path.exists() and not args.force:
        continue
    STATE["frame"] = f
    # the first sforzando: the render converges from raw path-tracing noise
    k = f - CONVERGE_F0
    if 0 <= k < CONVERGE_N:
        sc.cycles.samples = max(1, min(64, int(round(2 ** (k / 4.5)))))
        sc.cycles.use_denoising = False
        sc.cycles.use_adaptive_sampling = False
    else:
        sc.cycles.samples = BASE_SAMPLES
        sc.cycles.use_denoising = True
        sc.cycles.use_adaptive_sampling = True
    sc.frame_set(f)
    handler(sc)
    sc.render.filepath = str(path)
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    s = shots.shot_for_frame(f)
    print(f"FRAME {f} t={f / FPS:.3f} shot={s['index']}:{s['name']} {time.time() - t0:.1f}s "
          f"[{i + 1}/{len(frames)}, {(time.time() - t_start) / 60:.1f} min]", flush=True)
