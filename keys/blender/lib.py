"""Shared helpers for the storm build: paths, data, mesh + material builders.

Coordinate conventions
  piano-local (the "Piano" root's space):  x = across the keyboard (treble +),
      y = keyboard front -> tail, z = up, floor at z = 0, key fronts at y = 0.
  world: the root sits at (-1.37, 0, 0) rotated -90 deg about Z, so
      world = (y_local - 1.37, -x_local, z).  The audience is toward -Y, the
      back wall with the arched windows at +Y, the keyboard toward -X.
"""
import json
import math
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]          # .../pianosim
STORM = ROOT / "keys"
BUILD = ROOT / "build"
FPS = 60
LEAD = 0.25                                          # music starts 0.25 s into the video
DURATION = 24.0
PIANO_ORIGIN = Vector((-1.37, 0.0, 0.0))
PIANO_ROT_Z = -math.pi / 2


def load_data():
    return json.load(open(BUILD / "notes_b14.json"))


def local_to_world(p):
    x, y, z = p
    return Vector((y + PIANO_ORIGIN.x, -x + PIANO_ORIGIN.y, z + PIANO_ORIGIN.z))


def srgb(hexstr):
    """'#RRGGBB' -> linear RGB tuple."""
    h = hexstr.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def mulberry32(seed):
    a = seed & 0xFFFFFFFF
    def rnd():
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return rnd


# ---------------------------------------------------------------- collections
def collection(name, parent=None):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    p = parent or bpy.context.scene.collection
    if c.name not in [x.name for x in p.children]:
        p.children.link(c)
    return c


def link(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)
    return obj


# ---------------------------------------------------------------- meshes
def mesh_from_bmesh(name, bm, mat=None, coll=None, smooth=False):
    me = bpy.data.meshes.new(name)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    if smooth:
        me.shade_smooth()
    ob = bpy.data.objects.new(name, me)
    if mat is not None:
        for m in (mat if isinstance(mat, (list, tuple)) else [mat]):
            me.materials.append(m)
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def bm_box(bm, lo, hi, matrix=None):
    """Axis-aligned box from corner lo to corner hi (optionally transformed)."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    vs = [bm.verts.new(v) for v in [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                                     (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]]
    idx = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    fs = [bm.faces.new([vs[i] for i in f]) for f in idx]
    if matrix is not None:
        bmesh.ops.transform(bm, matrix=matrix, verts=vs)
    return vs, fs


def bm_prism(bm, pts, z0, z1, cap=True, mat_index=0):
    """Extrude a closed CCW 2D polygon from z0 to z1."""
    bot = [bm.verts.new((x, y, z0)) for x, y in pts]
    top = [bm.verts.new((x, y, z1)) for x, y in pts]
    n = len(pts)
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append(bm.faces.new((bot[i], bot[j], top[j], top[i])))
    if cap:
        faces.append(bm.faces.new(list(reversed(bot))))
        faces.append(bm.faces.new(top))
    for f in faces:
        f.material_index = mat_index
    return bot, top, faces


def bm_wall(bm, outer, inner, z0, z1, closed=True, mat_index=0):
    """A wall between two matching polylines (outer/inner), with top + bottom."""
    n = len(outer)
    ob = [bm.verts.new((x, y, z0)) for x, y in outer]
    ot = [bm.verts.new((x, y, z1)) for x, y in outer]
    ib = [bm.verts.new((x, y, z0)) for x, y in inner]
    it = [bm.verts.new((x, y, z1)) for x, y in inner]
    rng = range(n) if closed else range(n - 1)
    fs = []
    for i in rng:
        j = (i + 1) % n
        fs += [bm.faces.new((ob[i], ob[j], ot[j], ot[i])),     # outside
               bm.faces.new((ib[j], ib[i], it[i], it[j])),     # inside
               bm.faces.new((ot[i], ot[j], it[j], it[i])),     # top
               bm.faces.new((ob[j], ob[i], ib[i], ib[j]))]     # bottom
    if not closed:
        fs += [bm.faces.new((ob[0], ot[0], it[0], ib[0])),
               bm.faces.new((ob[-1], ib[-1], it[-1], ot[-1]))]
    for f in fs:
        f.material_index = mat_index
    return fs


def bm_tube(bm, p0, p1, r, seg=8, rings=1, cap=True):
    """Cylinder from p0 to p1 with `rings` length subdivisions (for bending)."""
    p0, p1 = Vector(p0), Vector(p1)
    axis = p1 - p0
    rot = axis.to_track_quat("Z", "Y").to_matrix().to_4x4()
    loops = []
    for k in range(rings + 1):
        c = p0 + axis * (k / rings)
        loop = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            loop.append(bm.verts.new(c + (rot @ Vector((r * math.cos(a), r * math.sin(a), 0)))))
        loops.append(loop)
    for k in range(rings):
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((loops[k][i], loops[k][j], loops[k + 1][j], loops[k + 1][i]))
    if cap:
        bm.faces.new(list(reversed(loops[0])))
        bm.faces.new(loops[-1])
    return loops


def bm_lathe(bm, profile, center=(0, 0, 0), seg=24):
    """Revolve a (radius, z) profile around the Z axis at `center`."""
    cx, cy, cz = center
    rings = []
    for r, z in profile:
        rings.append([bm.verts.new((cx + r * math.cos(2 * math.pi * i / seg),
                                    cy + r * math.sin(2 * math.pi * i / seg), cz + z))
                      for i in range(seg)])
    for k in range(len(rings) - 1):
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((rings[k][i], rings[k][j], rings[k + 1][j], rings[k + 1][i]))
    return rings


def offset_polyline(pts, d, closed=True):
    """Offset a 2D polyline by d along its left normal (inward for CCW)."""
    n = len(pts)
    out = []
    for i in range(n):
        if closed:
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        else:
            a = pts[max(i - 1, 0)]; b = pts[i]; c = pts[min(i + 1, n - 1)]
        t1 = Vector((b[0] - a[0], b[1] - a[1])); t2 = Vector((c[0] - b[0], c[1] - b[1]))
        t1 = t1.normalized() if t1.length > 1e-9 else t2.normalized()
        t2 = t2.normalized() if t2.length > 1e-9 else t1
        t = (t1 + t2).normalized()
        nrm = Vector((-t.y, t.x))
        cosh = max(0.3, nrm.dot(Vector((-t1.y, t1.x))))
        out.append((b[0] + nrm.x * d / cosh, b[1] + nrm.y * d / cosh))
    return out


def add_bevel(ob, width, segments=2, angle=40):
    m = ob.modifiers.new("bevel", "BEVEL")
    m.width = width; m.segments = segments
    m.limit_method = "ANGLE"; m.angle_limit = math.radians(angle)
    m.harden_normals = False
    return m


# ---------------------------------------------------------------- materials
def new_mat(name):
    m = bpy.data.materials.get(name)
    if m:
        bpy.data.materials.remove(m)
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m


def principled(name, base, rough=0.5, metal=0.0, coat=0.0, coat_rough=0.03, spec=0.5,
               sheen=0.0, transmission=0.0, ior=1.5, emission=None, estr=0.0):
    m = new_mat(name)
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*base, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Coat Roughness"].default_value = coat_rough
    b.inputs["Specular IOR Level"].default_value = spec
    b.inputs["Sheen Weight"].default_value = sheen
    b.inputs["Transmission Weight"].default_value = transmission
    b.inputs["IOR"].default_value = ior
    if emission:
        b.inputs["Emission Color"].default_value = (*emission, 1)
        b.inputs["Emission Strength"].default_value = estr
    return m


def node(nt, kind, loc=(0, 0), **inputs):
    n = nt.nodes.new(kind)
    n.location = loc
    for k, v in inputs.items():
        if k in n.inputs:
            n.inputs[k].default_value = v
        else:
            setattr(n, k, v)
    return n


def uniform(nt, name, value=0.0, loc=(-900, 0)):
    """A Value node the per-frame handler drives (registered by its label)."""
    n = nt.nodes.new("ShaderNodeValue")
    n.name = n.label = "U_" + name
    n.outputs[0].default_value = value
    n.location = loc
    return n
