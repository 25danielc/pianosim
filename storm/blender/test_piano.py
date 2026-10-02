import sys, math, time
sys.path.insert(0, "/Users/danielchen/projects/pianosim/storm/blender")
import bpy
from mathutils import Vector
bpy.ops.wm.read_factory_settings(use_empty=True)
import piano, lib
t0 = time.time()
root, M = piano.build()
print("built in", round(time.time() - t0, 1), "s; objects:", len(bpy.data.objects))
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"; sc.eevee.taa_render_samples = 32
sc.render.resolution_x, sc.render.resolution_y = 1280, 900
sc.view_settings.view_transform = "AgX"
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.06, 0.08, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
bpy.ops.object.light_add(type="AREA", location=(0, -3, 6)); L = bpy.context.object; L.data.energy = 3000; L.data.size = 4
bpy.ops.mesh.primitive_plane_add(size=20); fl = bpy.context.object
bpy.ops.object.camera_add(); cam = bpy.context.object; sc.camera = cam
for name, loc, tgt, lens in [("3q", (-2.6, -3.6, 2.6), (0, 0, 0.8), 28), ("top", (-0.6, -0.15, 3.0), (-0.6, -0.15, 0.8), 24),
                             ("keys", (-2.0, -0.9, 1.05), (-1.3, -0.1, 0.75), 35)]:
    cam.location = Vector(loc); cam.data.lens = lens
    cam.rotation_euler = (Vector(tgt) - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = f"/Users/danielchen/projects/pianosim/storm/look/test_{name}.png"
    bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath="/Users/danielchen/projects/pianosim/storm/look/test_piano.blend")
