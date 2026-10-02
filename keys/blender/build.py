"""Build keys/scene.blend: the piano in a black void, lit by the music light.
   blender -b --factory-startup -P keys/blender/build.py"""
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bmesh  # noqa: E402
import bpy  # noqa: E402

bpy.ops.wm.read_factory_settings(use_empty=True)

import piano  # noqa: E402
from lib import FPS, STORM, bm_box, collection, mesh_from_bmesh, new_mat, node, srgb  # noqa: E402

t0 = time.time()
sc = bpy.context.scene
sc.name = "keys"
root, M = piano.build(collection("Piano"))

# ---------------------------------------------------------------- the reveal
# every material gets a wipe: where world y < U_wipe the surface becomes its
# bare wireframe (the triangles the code generated), self-lit, on black
def add_reveal(mat):
    nt = mat.node_tree
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    link = next((l for l in nt.links if l.to_node == out and l.to_socket.name == "Surface"), None)
    if link is None:
        return
    src = link.from_socket
    wipe = nt.nodes.new("ShaderNodeValue"); wipe.name = wipe.label = "U_wipe"
    wipe.outputs[0].default_value = -5.0
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sep.inputs[0])
    d = nt.nodes.new("ShaderNodeMath"); d.operation = "SUBTRACT"
    nt.links.new(wipe.outputs[0], d.inputs[0]); nt.links.new(sep.outputs["Y"], d.inputs[1])
    mask = nt.nodes.new("ShaderNodeMapRange"); mask.interpolation_type = "SMOOTHSTEP"
    mask.inputs["From Min"].default_value = -0.004; mask.inputs["From Max"].default_value = 0.004
    nt.links.new(d.outputs[0], mask.inputs["Value"])
    # a thin bright seam right at the wipe front, like a render pass sweeping by
    seam = nt.nodes.new("ShaderNodeMapRange"); seam.interpolation_type = "SMOOTHSTEP"
    absd = nt.nodes.new("ShaderNodeMath"); absd.operation = "ABSOLUTE"
    nt.links.new(d.outputs[0], absd.inputs[0])
    seam.inputs["From Min"].default_value = 0.012; seam.inputs["From Max"].default_value = 0.0
    nt.links.new(absd.outputs[0], seam.inputs["Value"])
    wf = nt.nodes.new("ShaderNodeWireframe"); wf.use_pixel_size = True
    wf.inputs["Size"].default_value = 1.15
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*srgb("#CFE0FF"), 1); em.inputs["Strength"].default_value = 1.6
    blk = nt.nodes.new("ShaderNodeBsdfDiffuse"); blk.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1)
    wire = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(wf.outputs[0], wire.inputs[0]); nt.links.new(blk.outputs[0], wire.inputs[1]); nt.links.new(em.outputs[0], wire.inputs[2])
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(mask.outputs[0], mix.inputs[0]); nt.links.new(src, mix.inputs[1]); nt.links.new(wire.outputs[0], mix.inputs[2])
    sem = nt.nodes.new("ShaderNodeEmission")
    sem.inputs["Color"].default_value = (*srgb("#CFE0FF"), 1); sem.inputs["Strength"].default_value = 6.0
    smix = nt.nodes.new("ShaderNodeMixShader")
    sk = nt.nodes.new("ShaderNodeMath"); sk.operation = "MULTIPLY"
    nt.links.new(seam.outputs[0], sk.inputs[0]); sk.inputs[1].default_value = 0.85
    nt.links.new(sk.outputs[0], smix.inputs[0]); nt.links.new(mix.outputs[0], smix.inputs[1]); nt.links.new(sem.outputs[0], smix.inputs[2])
    nt.links.new(smix.outputs[0], out.inputs["Surface"])


for mat in list(bpy.data.materials):
    if mat.use_nodes and mat.name not in ("haze",):
        add_reveal(mat)

# ---------------------------------------------------------------- the void
# camera rays see black; reflections see a faint, soft cool band so the
# lacquer and the fallboard still read as glossy
w = bpy.data.worlds.new("void"); sc.world = w; w.use_nodes = True
nt = w.node_tree
for n in list(nt.nodes):
    nt.nodes.remove(n)
out = node(nt, "ShaderNodeOutputWorld", (900, 0))
tc = node(nt, "ShaderNodeTexCoord", (-900, 0))
sep = node(nt, "ShaderNodeSeparateXYZ", (-700, 0))
nt.links.new(tc.outputs["Generated"], sep.inputs[0])
band = node(nt, "ShaderNodeMapRange", (-500, 0), interpolation_type="SMOOTHSTEP",
            **{"From Min": -0.05, "From Max": 0.35, "To Min": 0.0, "To Max": 1.0})
nt.links.new(sep.outputs["Z"], band.inputs["Value"])
fall = node(nt, "ShaderNodeMapRange", (-500, -200), interpolation_type="SMOOTHSTEP",
            **{"From Min": 0.75, "From Max": 0.35, "To Min": 0.0, "To Max": 1.0})
nt.links.new(sep.outputs["Z"], fall.inputs["Value"])
m = node(nt, "ShaderNodeMath", (-300, 0), operation="MULTIPLY")
nt.links.new(band.outputs[0], m.inputs[0]); nt.links.new(fall.outputs[0], m.inputs[1])
k = node(nt, "ShaderNodeMath", (-150, 0), operation="MULTIPLY")
nt.links.new(m.outputs[0], k.inputs[0]); k.inputs[1].default_value = 0.035
lp = node(nt, "ShaderNodeLightPath", (-150, 250))
nc = node(nt, "ShaderNodeMath", (0, 200), operation="SUBTRACT")
nc.inputs[0].default_value = 1.0
nt.links.new(lp.outputs["Is Camera Ray"], nc.inputs[1])
st = node(nt, "ShaderNodeMath", (150, 100), operation="MULTIPLY")
nt.links.new(k.outputs[0], st.inputs[0]); nt.links.new(nc.outputs[0], st.inputs[1])
bg = node(nt, "ShaderNodeBackground", (500, 0))
bg.inputs["Color"].default_value = (*srgb("#CFE0FF"), 1)
nt.links.new(st.outputs[0], bg.inputs["Strength"])
nt.links.new(bg.outputs[0], out.inputs["Surface"])

# haze around the keyboard so the music light's beam is visible
bm = bmesh.new()
bm_box(bm, (-2.6, -1.3, 0.55), (-0.85, 1.3, 2.2))
haze = mesh_from_bmesh("haze", bm, None, sc.collection)
hm = new_mat("haze"); hnt = hm.node_tree; hnt.nodes.remove(hnt.nodes["Principled BSDF"])
pv = node(hnt, "ShaderNodeVolumePrincipled", (0, 0))
pv.inputs["Density"].default_value = 0.035
pv.inputs["Anisotropy"].default_value = 0.6
pv.inputs["Color"].default_value = (0.92, 0.95, 1.0, 1)
hnt.links.new(pv.outputs[0], hnt.nodes["Material Output"].inputs["Volume"])
haze.data.materials.append(hm)
haze.hide_render = True          # off: the void reads cleaner without it

# ---------------------------------------------------------------- lights
moon = srgb("#CFE0FF")
# a fixed, broad soft key light above the player's side: every key in frame
# stays visible; the void around it stays black
from mathutils import Vector
kl = bpy.data.lights.new("key_light", "AREA")
kl.shape = "RECTANGLE"; kl.size = 1.5; kl.size_y = 0.45
kl.energy = 120.0; kl.color = moon
spo = bpy.data.objects.new("key_light", kl); sc.collection.objects.link(spo)
spo.location = (-1.95, 0.0, 1.55)
spo.rotation_euler = (Vector((-1.30, 0.0, 0.72)) - spo.location).to_track_quat("-Z", "Y").to_euler()
# a dim top light over the fallboard for gloss on the key edges
tl = bpy.data.lights.new("top_light", "AREA")
tl.shape = "RECTANGLE"; tl.size = 1.4; tl.size_y = 0.12
tl.energy = 25.0; tl.color = moon
tlo = bpy.data.objects.new("top_light", tl); sc.collection.objects.link(tlo)
tlo.location = (-1.12, 0.0, 1.25)
tlo.rotation_euler = (Vector((-1.36, 0.0, 0.73)) - tlo.location).to_track_quat("-Z", "Y").to_euler()
tlo.visible_camera = False; tlo.visible_glossy = False

bl = bpy.data.lights.new("back_light", "AREA")
bl.shape = "RECTANGLE"; bl.size = 0.55; bl.size_y = 0.018
bl.energy = 0.0; bl.color = moon
blo = bpy.data.objects.new("back_light", bl); sc.collection.objects.link(blo)
blo.hide_render = True
for o in (spo, blo):
    o.visible_camera = False
    o.visible_glossy = False

# camera
cd = bpy.data.cameras.new("cam")
cd.sensor_fit = "HORIZONTAL"; cd.sensor_width = 36.0
cd.clip_start = 0.01; cd.clip_end = 50.0
cd.dof.use_dof = True; cd.dof.aperture_blades = 9; cd.dof.aperture_rotation = math.radians(10)
cam = bpy.data.objects.new("cam", cd); sc.collection.objects.link(cam); sc.camera = cam

# ---------------------------------------------------------------- render settings
r = sc.render
r.engine = "CYCLES"
r.resolution_x, r.resolution_y, r.resolution_percentage = 1920, 1350, 100
r.fps = FPS
r.use_motion_blur = True
r.motion_blur_shutter = 0.5
r.image_settings.file_format = "PNG"
r.image_settings.color_depth = "16"
r.image_settings.compression = 15
sc.frame_start, sc.frame_end = 0, int(24.0 * FPS) - 1
vs = sc.view_settings
vs.view_transform = "AgX"
try:
    vs.look = "AgX - Medium High Contrast"
except TypeError:
    pass
vs.exposure = 0.0

cy = sc.cycles
cy.device = "GPU"
cy.samples = 128
cy.use_adaptive_sampling = True
cy.adaptive_threshold = 0.025
cy.adaptive_min_samples = 32
cy.use_denoising = True
cy.denoiser = "OPENIMAGEDENOISE"
cy.denoising_input_passes = "RGB_ALBEDO_NORMAL"
cy.denoising_prefilter = "ACCURATE"
cy.max_bounces = 8; cy.diffuse_bounces = 3; cy.glossy_bounces = 4
cy.transmission_bounces = 4; cy.volume_bounces = 0; cy.transparent_max_bounces = 8
cy.sample_clamp_indirect = 4.0
cy.blur_glossy = 0.5
cy.caustics_reflective = False; cy.caustics_refractive = False
cy.use_light_tree = False
cy.seed = 0; cy.use_animated_seed = True

prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "METAL"; prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == "METAL"

outp = STORM / "scene.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(outp), compress=True)
print(f"BUILD OK {time.time() - t0:.1f}s objects={len(bpy.data.objects)} -> {outp}")
