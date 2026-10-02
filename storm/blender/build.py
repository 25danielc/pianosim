"""Build storm/scene.blend from code.   blender -b --factory-startup -P build.py"""
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bpy  # noqa: E402

bpy.ops.wm.read_factory_settings(use_empty=True)

import hall  # noqa: E402
import piano  # noqa: E402
from lib import STORM, FPS, collection  # noqa: E402

t0 = time.time()
sc = bpy.context.scene
sc.name = "storm"
piano_root, _ = piano.build(collection("Piano"))
H = hall.build(collection("Hall"))

# camera
cam_data = bpy.data.cameras.new("cam")
cam_data.sensor_fit = "HORIZONTAL"
cam_data.sensor_width = 36.0
cam_data.clip_start = 0.01
cam_data.clip_end = 400.0
cam_data.dof.use_dof = True
cam_data.dof.aperture_blades = 9
cam_data.dof.aperture_rotation = math.radians(10)
cam = bpy.data.objects.new("cam", cam_data)
sc.collection.objects.link(cam)
sc.camera = cam

# macro fill: small soft cool-white area light, only enabled in macro shots
fl = bpy.data.lights.new("macro_fill", "AREA")
fl.color = (0.81, 0.88, 1.0); fl.energy = 0.0; fl.size = 0.03
fl.shape = "DISK"
flo = bpy.data.objects.new("macro_fill", fl); sc.collection.objects.link(flo)
flo.hide_render = True

# EEVEE light probes (sphere probe for the lacquer, volume probe for GI)
pr = bpy.data.lightprobes.new("probe_sphere", "SPHERE")
pro = bpy.data.objects.new("probe_sphere", pr); sc.collection.objects.link(pro)
pro.location = (0.0, -0.5, 1.6)
pr.influence_distance = 7.0

# ---------------------------------------------------------------- render settings
r = sc.render
r.resolution_x, r.resolution_y, r.resolution_percentage = 1920, 1350, 100
r.fps = FPS
r.use_motion_blur = True
r.motion_blur_shutter = 0.5
r.film_transparent = False
r.image_settings.file_format = "PNG"
r.image_settings.color_depth = "16"
r.image_settings.compression = 15
r.dither_intensity = 0.0
sc.frame_start, sc.frame_end = 0, 2729

vs = sc.view_settings
vs.view_transform = "AgX"
try:
    vs.look = "AgX - Medium High Contrast"
except TypeError:
    try:
        vs.look = "Medium High Contrast"
    except TypeError:
        pass
vs.exposure = 1.4
vs.gamma = 1.0

cy = sc.cycles
cy.device = "GPU"
cy.samples = 128
cy.use_adaptive_sampling = True
cy.adaptive_threshold = 0.03
cy.adaptive_min_samples = 32
cy.use_denoising = True
cy.denoiser = "OPENIMAGEDENOISE"
cy.denoising_input_passes = "RGB_ALBEDO_NORMAL"
cy.denoising_prefilter = "ACCURATE"
cy.max_bounces = 8
cy.diffuse_bounces = 3
cy.glossy_bounces = 4
cy.transmission_bounces = 8
cy.volume_bounces = 0
cy.transparent_max_bounces = 8
cy.sample_clamp_indirect = 4.0
cy.blur_glossy = 0.6
cy.caustics_reflective = False
cy.caustics_refractive = False
cy.use_light_tree = False
cy.volume_step_rate = 1.5
cy.seed = 0
cy.use_animated_seed = True       # per-frame noise pattern; OIDN removes it

ee = sc.eevee
ee.taa_render_samples = 32
ee.use_raytracing = True
ee.ray_tracing_method = "SCREEN"
ee.use_shadows = True
ee.shadow_ray_count = 2
ee.shadow_step_count = 8
ee.volumetric_tile_size = "4"
ee.volumetric_samples = 48
ee.use_volumetric_shadows = True
ee.volumetric_shadow_samples = 32
ee.volumetric_start = 0.05
ee.volumetric_end = 60.0
ee.use_volume_custom_range = True
ee.motion_blur_steps = 1
ee.use_fast_gi = True
ee.fast_gi_method = "GLOBAL_ILLUMINATION"
ee.gi_diffuse_bounces = 2
ee.bokeh_max_size = 200.0
ee.clamp_surface_indirect = 6.0
ee.shadow_pool_size = "1024"

# the sky is only ever seen through the windows: don't importance-sample it as
# a light from every shading point (the moon/lightning suns carry that light)
sc.world.cycles.sampling_method = "NONE"

# per-object motion: strings/hammers need deformation blur (shape keys)
for o in bpy.data.objects:
    if o.type == "MESH" and o.get("part") in ("strings", "hammer"):
        if hasattr(o.cycles, "use_deform_motion"):
            o.cycles.use_deform_motion = True
        if hasattr(o.cycles, "motion_steps"):
            o.cycles.motion_steps = 3 if o["part"] == "strings" else 1

prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "METAL"
prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == "METAL"

out = STORM / "scene.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(out), compress=True)
print(f"BUILD OK {time.time() - t0:.1f}s  objects={len(bpy.data.objects)} -> {out}")
