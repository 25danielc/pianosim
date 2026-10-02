"""Procedural concert grand (Steinway D proportions: 2.74 m x 1.57 m).

Every moving part is its own object parented to the "Piano" root, tagged with
custom properties the animation reads:
  obj["part"]  key | hammer | damper | strings | lid | stick | plate | rim | ...
  obj["note"]  0..87 for per-note parts (MIDI pitch - 21)
  obj["pivot"] (y, z) of the hinge for parts that rotate
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from lib import (add_bevel, bm_box, bm_lathe, bm_prism, bm_tube, bm_wall, collection,
                 mesh_from_bmesh, new_mat, node, offset_polyline, principled, srgb,
                 PIANO_ORIGIN, PIANO_ROT_Z)

# ------------------------------------------------------------------ dimensions
W = 0.0235                     # white key pitch
KB_X0 = -26 * W                # keyboard left edge (52 white keys centred)
CASE_X = 0.785                 # half case width
KEY_TOP = 0.725
KEY_BOT = 0.703
KEY_BACK = 0.40
KEY_PIVOT_Y = 0.25
RIM_Z0, RIM_Z1 = 0.62, 1.00
STRING_Z = 0.915
STRIKE_Y = 0.43                # hammer head centre line
HAMMER_PIVOT = (0.30, 0.830)   # (y, z) of the hammer flange
HAMMER_HEAD_Z = 0.830          # base of the head molding at rest
DAMPER_Y = 0.50
AGRAFFE_Y = 0.38
LID_OPEN = math.radians(42)
N_DAMPERS = 69                 # keys 0..68 have dampers (top 19 notes don't)
JACK_Y = 0.36                  # where the jack meets key back and hammer shank
JACK_BOT_Z = 0.725
JACK_TOP_Z = 0.8268

BLACK_PC = {1: -0.10, 3: 0.10, 6: -0.13, 8: 0.0, 10: 0.13}   # offset in units of W


def key_layout():
    """[(k, is_black, x_center, (x_left, x_right) of the full-width part)]"""
    out, wi = [], 0
    for k in range(88):
        pc = (k + 21) % 12
        if pc in BLACK_PC:
            xc = KB_X0 + wi * W + BLACK_PC[pc] * W
            out.append((k, True, xc, (xc - 0.00685, xc + 0.00685)))
        else:
            xl = KB_X0 + wi * W
            out.append((k, False, xl + W / 2, (xl + 0.0005, xl + W - 0.0005)))
            wi += 1
    return out


def rim_outline(n=160):
    """Outer case outline (spine front -> around the tail -> treble front), CW."""
    ctrl = [(0.785, 0.22), (0.785, 0.50), (0.745, 0.86), (0.60, 1.25), (0.40, 1.70),
            (0.21, 2.10), (0.05, 2.42), (-0.16, 2.64), (-0.43, 2.745), (-0.66, 2.72), (-0.785, 2.60)]
    # Catmull-Rom through the bentside + tail control points
    def cr(p0, p1, p2, p3, t):
        return tuple(0.5 * ((2 * p1[i]) + (-p0[i] + p2[i]) * t + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * t * t
                            + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * t ** 3) for i in range(2))
    pts = [ctrl[0]] + ctrl + [ctrl[-1]]
    bent = []
    for i in range(1, len(pts) - 2):
        for s in range(12):
            bent.append(cr(pts[i - 1], pts[i], pts[i + 1], pts[i + 2], s / 12))
    bent.append(ctrl[-1])
    spine = [(-0.785, 0.22 + i * (2.60 - 0.22) / 18) for i in range(18)]   # front -> back
    return spine + list(reversed(bent))


def x_right(y, outline=None):
    """Bentside x at a given y (outer)."""
    pts = outline or rim_outline()
    best = None
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 > -0.7 and min(y0, y1) <= y <= max(y0, y1) and y1 != y0:
            x = x0 + (x1 - x0) * (y - y0) / (y1 - y0)
            best = x if best is None else max(best, x)
    return best if best is not None else -0.785


# ------------------------------------------------------------------ materials
def materials():
    M = {}
    lac = principled("lacquer", (0.0028, 0.0028, 0.0032), rough=0.22, coat=1.0, coat_rough=0.015)
    nt = lac.node_tree
    # faint orange-peel on the clearcoat so reflections read as real lacquer
    tc = node(nt, "ShaderNodeTexCoord", (-900, -300))
    nz = node(nt, "ShaderNodeTexNoise", (-700, -300), Scale=900.0, Detail=2.0)
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    bump = node(nt, "ShaderNodeBump", (-400, -300), Strength=0.012, Distance=0.0005)
    nt.links.new(nz.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], nt.nodes["Principled BSDF"].inputs["Coat Normal"])
    M["lacquer"] = lac

    iv = principled("ivory", tuple(c * 0.80 for c in srgb("#F2EDE3")), rough=0.30, coat=0.25, coat_rough=0.12)
    nt = iv.node_tree; b = nt.nodes["Principled BSDF"]
    b.inputs["Subsurface Weight"].default_value = 0.12
    b.inputs["Subsurface Radius"].default_value = (0.002, 0.0015, 0.001)
    oi = node(nt, "ShaderNodeObjectInfo", (-1100, 200))
    tc = node(nt, "ShaderNodeTexCoord", (-1100, -100))
    wear = node(nt, "ShaderNodeTexNoise", (-900, -100), Scale=60.0, Detail=6.0)
    nt.links.new(tc.outputs["Object"], wear.inputs["Vector"])
    ramp = node(nt, "ShaderNodeMapRange", (-700, 200), **{"From Min": 0.0, "From Max": 1.0, "To Min": 0.0, "To Max": 1.0})
    nt.links.new(oi.outputs["Random"], ramp.inputs["Value"])
    mix = node(nt, "ShaderNodeMix", (-450, 250), data_type="RGBA")
    mix.inputs[6].default_value = (*[c * 0.80 for c in srgb("#F2EDE3")], 1)
    mix.inputs[7].default_value = (*[c * 0.70 for c in srgb("#E9DCC4")], 1)   # yellowed
    nt.links.new(ramp.outputs[0], mix.inputs[0])
    nt.links.new(mix.outputs[2], b.inputs["Base Color"])
    rr = node(nt, "ShaderNodeMapRange", (-600, -100), **{"From Min": 0.3, "From Max": 0.7, "To Min": 0.24, "To Max": 0.40})
    nt.links.new(wear.outputs["Fac"], rr.inputs["Value"])
    nt.links.new(rr.outputs[0], b.inputs["Roughness"])
    M["ivory"] = iv

    M["ebony"] = principled("ebony", (0.010, 0.009, 0.0085), rough=0.34, coat=0.35, coat_rough=0.2)
    felt = principled("felt", tuple(c * 0.86 for c in srgb("#F2EDE3")), rough=1.0, spec=0.2, sheen=1.0)
    felt.node_tree.nodes["Principled BSDF"].inputs["Sheen Roughness"].default_value = 0.35
    nt = felt.node_tree
    tc = node(nt, "ShaderNodeTexCoord", (-900, -300))
    nz = node(nt, "ShaderNodeTexNoise", (-700, -300), Scale=2500.0, Detail=4.0)
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    bump = node(nt, "ShaderNodeBump", (-400, -300), Strength=0.5, Distance=0.0003)
    nt.links.new(nz.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], nt.nodes["Principled BSDF"].inputs["Normal"])
    M["felt"] = felt
    M["blackfelt"] = principled("blackfelt", (0.012, 0.012, 0.014), rough=1.0, spec=0.1, sheen=0.6)
    M["maple"] = principled("maple", (0.30, 0.21, 0.13), rough=0.45, coat=0.2)
    M["darkwood"] = principled("darkwood", (0.010, 0.0075, 0.006), rough=0.45, coat=0.15, coat_rough=0.3)
    sb = principled("spruce", (0.36, 0.25, 0.13), rough=0.5, coat=0.5, coat_rough=0.1)
    nt = sb.node_tree
    tc = node(nt, "ShaderNodeTexCoord", (-1000, 0))
    wave = node(nt, "ShaderNodeTexWave", (-800, 0), wave_type="BANDS", bands_direction="X",
                Scale=40.0, Distortion=3.0, Detail=3.0)
    nt.links.new(tc.outputs["Object"], wave.inputs["Vector"])
    mix = node(nt, "ShaderNodeMix", (-450, 100), data_type="RGBA")
    mix.inputs[6].default_value = (0.36, 0.25, 0.13, 1); mix.inputs[7].default_value = (0.27, 0.17, 0.08, 1)
    nt.links.new(wave.outputs["Fac"], mix.inputs[0])
    nt.links.new(mix.outputs[2], nt.nodes["Principled BSDF"].inputs["Base Color"])
    M["spruce"] = sb
    gold = principled("plate", (0.42, 0.27, 0.085), rough=0.36, metal=0.92, coat=0.35, coat_rough=0.12)
    nt = gold.node_tree
    tc = node(nt, "ShaderNodeTexCoord", (-900, -300))
    nz = node(nt, "ShaderNodeTexNoise", (-700, -300), Scale=300.0, Detail=8.0)
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    nz.inputs["Scale"].default_value = 1400.0
    rr = node(nt, "ShaderNodeMapRange", (-450, -300), **{"From Min": 0.3, "From Max": 0.7, "To Min": 0.33, "To Max": 0.41})
    nt.links.new(nz.outputs["Fac"], rr.inputs["Value"])
    nt.links.new(rr.outputs[0], nt.nodes["Principled BSDF"].inputs["Roughness"])
    M["plate"] = gold
    M["steel"] = principled("steel", (0.86, 0.87, 0.89), rough=0.16, metal=1.0)
    M["copper"] = principled("wound", (0.72, 0.47, 0.30), rough=0.28, metal=1.0)
    M["brass"] = principled("brass", (0.80, 0.60, 0.30), rough=0.2, metal=1.0)
    M["velvet"] = principled("benchtop", tuple(c * 0.5 for c in srgb("#0E1A2E")), rough=1.0, sheen=1.0)
    return M


# ------------------------------------------------------------------ helpers
def part(ob, kind, root, note=None, pivot=None, group=None):
    ob["part"] = kind
    if note is not None:
        ob["note"] = note
    if pivot is not None:
        ob["pivot"] = pivot
    ob["group"] = group or kind
    ob.parent = root
    return ob


def origin_to(ob, p):
    """Move the object's origin to local point p without moving the geometry."""
    p = Vector(p)
    ob.data.transform(Matrix.Translation(-p))
    ob.location = p


# ------------------------------------------------------------------ build
def build(coll=None):
    coll = coll or collection("Piano")
    M = materials()
    root = bpy.data.objects.new("Piano", None)
    coll.objects.link(root)
    root.location = PIANO_ORIGIN
    root.rotation_euler = (0, 0, PIANO_ROT_Z)

    outline = rim_outline()
    layout = key_layout()

    # --- keys ----------------------------------------------------------------
    blacks = {k: (xl, xr) for k, b, xc, (xl, xr) in layout if b}
    for k, is_black, xc, (xl, xr) in layout:
        bm = bmesh.new()
        if is_black:
            y0, y1, z0, z1 = 0.052, KEY_BACK, KEY_BOT, KEY_TOP + 0.012
            hw, tw = 0.00685, 0.0050
            vs = [bm.verts.new(v) for v in [
                (xc - hw, y0, z0), (xc + hw, y0, z0), (xc + hw, y1, z0), (xc - hw, y1, z0),
                (xc - tw, y0 + 0.009, z1), (xc + tw, y0 + 0.009, z1), (xc + tw, y1, z1), (xc - tw, y1, z1)]]
            for f in [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]:
                bm.faces.new([vs[i] for i in f])
            ob = mesh_from_bmesh(f"key_{k:02d}", bm, M["ebony"], coll)
            add_bevel(ob, 0.0007, 2)
        else:
            sl, sr = xl, xr
            if k - 1 in blacks:
                sl = blacks[k - 1][1] + 0.0008
            if k + 1 in blacks:
                sr = blacks[k + 1][0] - 0.0008
            yh = 0.050 if (k - 1 in blacks or k + 1 in blacks) else KEY_BACK
            pts = [(xl, 0.0), (xr, 0.0), (xr, yh)]
            if yh < KEY_BACK:
                pts += [(sr, yh), (sr, KEY_BACK), (sl, KEY_BACK), (sl, yh)]
            else:
                pts += [(xr, KEY_BACK), (xl, KEY_BACK)]
            pts += [(xl, yh)] if yh < KEY_BACK else []
            # de-duplicate collinear joins
            clean = []
            for p in pts:
                if not clean or (abs(p[0] - clean[-1][0]) > 1e-7 or abs(p[1] - clean[-1][1]) > 1e-7):
                    clean.append(p)
            if abs(clean[0][0] - clean[-1][0]) < 1e-7 and abs(clean[0][1] - clean[-1][1]) < 1e-7:
                clean.pop()
            bm_prism(bm, clean, KEY_BOT, KEY_TOP)
            ob = mesh_from_bmesh(f"key_{k:02d}", bm, M["ivory"], coll)
            add_bevel(ob, 0.0009, 2)
        origin_to(ob, (xc, KEY_PIVOT_Y, KEY_BOT))
        part(ob, "key", root, note=k, pivot=(KEY_PIVOT_Y, KEY_BOT))
        ob["black"] = int(is_black)

    # --- keyboard furniture: keybed, key slip, cheek blocks, fallboard --------
    bm = bmesh.new()
    bm_box(bm, (-CASE_X, -0.014, 0.640), (CASE_X, 0.46, 0.690))            # keybed
    ob = mesh_from_bmesh("keybed", bm, M["lacquer"], coll); add_bevel(ob, 0.003)
    part(ob, "keybed", root, group="case")
    bm = bmesh.new()
    bm_box(bm, (KB_X0 - 0.002, -0.016, 0.688), (-KB_X0 + 0.002, -0.002, 0.712))  # key slip
    ob = mesh_from_bmesh("keyslip", bm, M["lacquer"], coll); add_bevel(ob, 0.002)
    part(ob, "keyslip", root, group="case")
    for s in (-1, 1):
        bm = bmesh.new()
        x0, x1 = sorted((s * (abs(KB_X0) + 0.003), s * CASE_X))
        pts = [(-0.014, 0.0), (0.225, 0.0), (0.225, 0.17), (0.10, 0.17), (0.02, 0.14), (-0.014, 0.10)]
        # profile in (y, z-rel) extruded across x
        vsA = [bm.verts.new((x0, y, 0.69 + z)) for y, z in pts]
        vsB = [bm.verts.new((x1, y, 0.69 + z)) for y, z in pts]
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((vsA[i], vsA[j], vsB[j], vsB[i]))
        bm.faces.new(list(reversed(vsA))); bm.faces.new(vsB)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        ob = mesh_from_bmesh(f"cheek_{'L' if s < 0 else 'R'}", bm, M["lacquer"], coll); add_bevel(ob, 0.004, 3)
        part(ob, "cheek", root, group="case")
    bm = bmesh.new()   # fallboard (open, folded back behind the keys)
    prof = [(0.152, 0.0), (0.27, 0.0), (0.27, 0.105), (0.20, 0.110), (0.152, 0.040)]
    vsA = [bm.verts.new((KB_X0 - 0.002, y, 0.725 + z)) for y, z in prof]
    vsB = [bm.verts.new((-KB_X0 + 0.002, y, 0.725 + z)) for y, z in prof]
    for i in range(len(prof)):
        j = (i + 1) % len(prof)
        bm.faces.new((vsA[i], vsA[j], vsB[j], vsB[i]))
    bm.faces.new(list(reversed(vsA))); bm.faces.new(vsB)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = mesh_from_bmesh("fallboard", bm, M["lacquer"], coll); add_bevel(ob, 0.003, 3)
    part(ob, "fallboard", root, group="case")

    # --- music desk: a lacquered panel standing behind the fallboard ------------
    bm = bmesh.new()
    tilt = Matrix.Translation((0, 0.205, 0.835)) @ Matrix.Rotation(math.radians(-12), 4, "X")
    bm_box(bm, (-0.47, -0.012, 0.0), (0.47, 0.0, 0.30), matrix=tilt)          # panel
    bm_box(bm, (-0.47, -0.045, -0.004), (0.47, 0.0, 0.016), matrix=tilt)      # ledge
    ob = mesh_from_bmesh("music_desk", bm, M["lacquer"], coll); add_bevel(ob, 0.003, 3)
    part(ob, "desk", root, group="case")

    # --- rim, case bottom ------------------------------------------------------
    # inward offset: the spine (x = -0.785) must move toward +x
    sgn = -1.0 if offset_polyline(outline, -0.055, closed=False)[5][0] > outline[5][0] else 1.0
    inner = offset_polyline(outline, sgn * 0.055, closed=False)
    bm = bmesh.new()
    bm_wall(bm, outline, inner, RIM_Z0, RIM_Z1, closed=False)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    rim = mesh_from_bmesh("rim", bm, M["lacquer"], coll, smooth=False)
    add_bevel(rim, 0.006, 3, angle=50)
    part(rim, "rim", root)
    bm = bmesh.new()
    bm_prism(bm, list(reversed(outline)), RIM_Z0, RIM_Z0 + 0.02)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = mesh_from_bmesh("case_bottom", bm, M["lacquer"], coll)
    part(ob, "bottom", root, group="rim")

    # --- soundboard -------------------------------------------------------------
    sb_poly = [p for p in inner if p[1] >= 0.42]
    sb_poly = [(inner[0][0], 0.42)] + sb_poly + [(inner[-1][0], 0.42)]
    bm = bmesh.new()
    bm_prism(bm, list(reversed(sb_poly)), 0.795, 0.805)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = mesh_from_bmesh("soundboard", bm, M["spruce"], coll)
    part(ob, "soundboard", root)

    # --- plate: front bar (pin block) + main body with openings -----------------
    plate_in = offset_polyline(inner, sgn * 0.03, closed=False)
    body = [p for p in plate_in if p[1] >= 0.53]
    body = [(plate_in[0][0], 0.53)] + body + [(plate_in[-1][0], 0.53)]
    bm = bmesh.new()
    bm_prism(bm, list(reversed(body)), 0.866, 0.884)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    plate = mesh_from_bmesh("plate", bm, M["plate"], coll)
    # openings between the struts (capsules) + the classic row of round holes
    cutters = []
    def capsule(x0, y0, x1, y1, r, n=10):
        a = math.atan2(y1 - y0, x1 - x0)
        pts = []
        for i in range(n + 1):
            t = a - math.pi / 2 + math.pi * i / n
            pts.append((x1 + r * math.cos(t), y1 + r * math.sin(t)))
        for i in range(n + 1):
            t = a + math.pi / 2 + math.pi * i / n
            pts.append((x0 + r * math.cos(t), y0 + r * math.sin(t)))
        return pts
    openings = [(-0.62, 0.78, -0.58, 2.30, 0.07), (-0.36, 0.78, -0.28, 2.32, 0.075),
                (-0.07, 0.78, 0.00, 2.05, 0.075), (0.20, 0.78, 0.22, 1.62, 0.07),
                (0.46, 0.78, 0.44, 1.22, 0.06)]
    for (x0, y0, x1, y1, r) in openings:
        bm = bmesh.new()
        bm_prism(bm, capsule(x0, y0, x1, y1, r), 0.84, 0.91)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        cutters.append(mesh_from_bmesh("cut", bm, None, coll))
    for i, x in enumerate([-0.49, -0.22, 0.08, 0.33, 0.58]):
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=0.032, radius2=0.032, depth=0.1,
                              matrix=Matrix.Translation((x, 0.625, 0.875)))
        cutters.append(mesh_from_bmesh("cut", bm, None, coll))
    for c in cutters:
        m = plate.modifiers.new("cut", "BOOLEAN"); m.object = c; m.operation = "DIFFERENCE"; m.solver = "EXACT"
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(plate.evaluated_get(dg))
    plate.modifiers.clear(); old = plate.data; plate.data = me; bpy.data.meshes.remove(old)
    for c in cutters:
        bpy.data.objects.remove(c)
    add_bevel(plate, 0.003, 2)
    part(plate, "plate", root)
    bm = bmesh.new()
    bm_box(bm, (-0.74, 0.17, 0.866), (0.74, 0.385, 0.888))
    ob = mesh_from_bmesh("plate_front", bm, M["plate"], coll); add_bevel(ob, 0.004, 2)
    part(ob, "plate", root, group="plate")
    # side frames joining the front bar to the body across the action gap
    for x0, x1 in ((-0.74, -0.70), (0.68, 0.74)):
        bm = bmesh.new(); bm_box(bm, (x0, 0.38, 0.866), (x1, 0.54, 0.888))
        ob = mesh_from_bmesh("plate_side", bm, M["plate"], coll); add_bevel(ob, 0.003, 2)
        part(ob, "plate", root, group="plate")

    # --- strings, tuning pins, hammers, dampers ---------------------------------
    strings_meta = []
    for k in range(88):
        n_str = 1 if k < 8 else (2 if k < 28 else 3)
        wound = k < 28
        r = 0.0024 - 0.0011 * (k / 27) if wound else 0.00072 - 0.0003 * ((k - 28) / 59)
        if k < 20:           # overstrung bass: fan diagonally over the tenor
            p0 = Vector((-0.705 + 0.0145 * k, 0.24, STRING_Z + 0.012))
            p1 = Vector((-0.46 + 0.012 * k, 2.50 - 0.032 * k, STRING_Z + 0.012))
        else:
            xs = -0.395 + (k - 20) * (1.045 / 67)
            L = min(0.052 * 2 ** ((87 - k) / 12 * 0.94), 1.55)
            ymax = 2.25
            # keep the hitch end inside the bentside
            for yy in [0.4 + i * 0.01 for i in range(200)]:
                if x_right(yy, outline) - 0.10 < xs:
                    ymax = yy
                    break
            p0 = Vector((xs, 0.24 + 0.035 * (k % 3), STRING_Z))
            p1 = Vector((xs, min(AGRAFFE_Y + L + 0.06, ymax), STRING_Z))
        d = (p1 - p0).normalized()
        side = Vector((d.y, -d.x, 0))
        gap = 0.0026 if wound else 0.0021
        bm = bmesh.new()
        tubes = []
        for s in range(n_str):
            off = side * (gap * (s - (n_str - 1) / 2))
            tubes.append(bm_tube(bm, p0 + off, p1 + off, r, seg=6, rings=24, cap=False))
        mat = M["copper"] if wound else M["steel"]
        ob = mesh_from_bmesh(f"strings_{k:02d}", bm, mat, coll, smooth=True)
        part(ob, "strings", root, note=k)
        # vibration shape key: half-sine bow over the speaking length (1 mm)
        ob.shape_key_add(name="Basis")
        sk = ob.shape_key_add(name="vib")
        y_ag = AGRAFFE_Y
        for v, kv in zip(ob.data.vertices, sk.data):
            co = v.co
            u = (co.y - y_ag) / max(1e-6, (p1.y - y_ag))
            if 0.0 < u < 1.0:
                kv.co = co + Vector((0.4, 0, 1.0)).normalized() * 0.001 * math.sin(math.pi * u)
        sk.slider_min, sk.slider_max = -10, 10
        # where the hammer strikes / damper sits on this string group
        def at_y(yy):
            t = (yy - p0.y) / (p1.y - p0.y)
            return p0.x + t * (p1.x - p0.x), p0.z
        hx, hz = at_y(STRIKE_Y)
        dx, dz = at_y(DAMPER_Y)
        width = gap * (n_str - 1) + 2 * r
        strings_meta.append({"k": k, "hx": hx, "hz": hz, "dx": dx, "dz": dz, "r": r, "width": width,
                             "p0": tuple(p0), "p1": tuple(p1)})
    # tuning pins + agraffes (static; one object)
    bm = bmesh.new()
    for m in strings_meta:
        n_str = 1 if m["k"] < 8 else (2 if m["k"] < 28 else 3)
        p0 = Vector(m["p0"])
        for s in range(n_str):
            x = p0.x + 0.0026 * (s - (n_str - 1) / 2)
            bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.0035, radius2=0.0035, depth=0.03,
                                  matrix=Matrix.Translation((x, p0.y, 0.895)))
    ob = mesh_from_bmesh("tuning_pins", bm, M["steel"], coll, smooth=True)
    part(ob, "pins", root, group="plate")

    hammer_meta = []
    xs_sorted = [m["hx"] for m in strings_meta]
    for m in strings_meta:
        k = m["k"]
        nb = [abs(xs_sorted[j] - m["hx"]) for j in (k - 1, k + 1) if 0 <= j < 88]
        spacing = min(nb) if nb else 0.013
        w = max(0.008, min(0.019, spacing - 0.0016, m["width"] + 0.004))
        bm = bmesh.new()
        prof = [(-0.012, 0.0), (0.012, 0.0), (0.0115, 0.010)]
        # felt: smooth teardrop (flat sides, rounded crown)
        felt_prof = []
        for i in range(25):
            th = math.pi * i / 24
            sy = math.cos(th)
            felt_prof.append((0.0118 * sy * (1 - 0.18 * math.sin(th) ** 2),
                              0.0095 + 0.029 * math.sin(th) ** 0.72))
        hx = m["hx"]; hy = STRIKE_Y; hz = HAMMER_HEAD_Z
        # molding (wood) as a prism across x
        def prism_x(prof2, mat_index):
            A = [bm.verts.new((hx - w / 2, hy + y, hz + z)) for y, z in prof2]
            B = [bm.verts.new((hx + w / 2, hy + y, hz + z)) for y, z in prof2]
            n = len(prof2)
            for i in range(n):
                j = (i + 1) % n
                f = bm.faces.new((A[i], A[j], B[j], B[i])); f.material_index = mat_index
                f.smooth = n > 8 and i < n - 1
            f = bm.faces.new(list(reversed(A))); f.material_index = mat_index
            f = bm.faces.new(B); f.material_index = mat_index
        prism_x([(-0.012, 0.0), (0.012, 0.0), (0.0115, 0.010), (-0.0115, 0.010)], 0)
        prism_x(felt_prof, 1)
        # shank
        bm_tube(bm, (hx, HAMMER_PIVOT[0], HAMMER_PIVOT[1] + 0.002), (hx, hy, hz + 0.002), 0.0032, seg=8)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        ob = mesh_from_bmesh(f"hammer_{k:02d}", bm, [M["maple"], M["felt"]], coll)
        add_bevel(ob, 0.0006, 2, angle=60)
        origin_to(ob, (hx, HAMMER_PIVOT[0], HAMMER_PIVOT[1]))
        part(ob, "hammer", root, note=k, pivot=HAMMER_PIVOT)
        # felt squash shape key: the crown flattens ~1.6 mm and bulges slightly
        ob.shape_key_add(name="Basis")
        sk = ob.shape_key_add(name="squash")
        for v, kv in zip(ob.data.vertices, sk.data):
            co = v.co.copy()
            hz_rel = co.z - (hz - HAMMER_PIVOT[1])
            if hz_rel > 0.02 and abs(co.y - (hy - HAMMER_PIVOT[0])) < 0.013:
                f = (hz_rel - 0.02) / 0.0185
                co.z -= 0.0016 * f
                co.y += 0.0007 * f * (1 if co.y > (hy - HAMMER_PIVOT[0]) else -1)
            kv.co = co
        # strike angle: rotate the felt crown up until it touches the string bottom
        crown = Vector((0, hy - HAMMER_PIVOT[0], hz + 0.0385 - HAMMER_PIVOT[1]))
        target = m["hz"] - m["r"] - HAMMER_PIVOT[1]
        a = math.asin(max(-1, min(1, target / crown.length))) - math.atan2(crown.z, crown.y)
        ob["strike"] = a
        hammer_meta.append(a)

    # --- jacks: a slim post from each key's back end up to its hammer shank, so
    # side views show the key -> hammer linkage (driven by anim.py)
    key_x = {k: xc for k, _b, xc, _r in layout}
    for m in strings_meta:
        k = m["k"]
        L = JACK_TOP_Z - JACK_BOT_Z
        bm = bmesh.new()
        bm_box(bm, (-0.0022, -0.003, 0.0), (0.0022, 0.003, L - 0.004))
        for f in bm.faces:
            f.material_index = 0
        cap_v, cap_f = bm_box(bm, (-0.0035, -0.0045, L - 0.004), (0.0035, 0.0045, L))
        for f in cap_f:
            f.material_index = 1
        ob = mesh_from_bmesh(f"jack_{k:02d}", bm, [M["maple"], M["felt"]], coll)
        part(ob, "jack", root, note=k)
        ob["bot"] = (key_x[k], JACK_Y, JACK_BOT_Z)
        ob["top"] = (m["hx"], JACK_Y, JACK_TOP_Z)
        ob["rest_len"] = L

    for m in strings_meta:
        k = m["k"]
        if k >= N_DAMPERS:
            continue
        w = max(0.008, min(m["width"] + 0.005, 0.022))
        bm = bmesh.new()
        z0 = m["dz"] + m["r"]
        bm_box(bm, (m["dx"] - w / 2, DAMPER_Y - 0.018, z0), (m["dx"] + w / 2, DAMPER_Y + 0.018, z0 + 0.006))
        for f in bm.faces:
            f.material_index = 1
        bm_box(bm, (m["dx"] - w / 2 + 0.0004, DAMPER_Y - 0.017, z0 + 0.006), (m["dx"] + w / 2 - 0.0004, DAMPER_Y + 0.017, z0 + 0.027))
        bm_tube(bm, (m["dx"], DAMPER_Y, z0 + 0.010), (m["dx"], DAMPER_Y, z0 - 0.022), 0.0010, seg=6)
        ob = mesh_from_bmesh(f"damper_{k:02d}", bm, [M["darkwood"], M["blackfelt"]], coll)
        add_bevel(ob, 0.0008, 1)
        origin_to(ob, (m["dx"], DAMPER_Y, z0))
        part(ob, "damper", root, note=k)

    # --- lid + prop stick ---------------------------------------------------------
    lid_poly = [p for p in outline if p[1] >= 0.40]
    lid_poly = [(-CASE_X, 0.40)] + lid_poly + [(CASE_X, 0.40)]
    bm = bmesh.new()
    bm_prism(bm, list(reversed(lid_poly)), 0.0, 0.024)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(0, 0, RIM_Z1 + 0.001))
    lid = mesh_from_bmesh("lid", bm, M["lacquer"], coll); add_bevel(lid, 0.005, 3)
    origin_to(lid, (-CASE_X, 0.0, RIM_Z1 + 0.001))
    lid.rotation_euler = (0, -LID_OPEN, 0)
    part(lid, "lid", root)
    lid["open"] = LID_OPEN
    d = 1.30
    top = Vector((-CASE_X + d * math.cos(LID_OPEN), 1.05, RIM_Z1 + d * math.sin(LID_OPEN)))
    bot = Vector((0.62, 1.05, RIM_Z1))
    bm = bmesh.new()
    bm_tube(bm, bot, top, 0.011, seg=12)
    ob = mesh_from_bmesh("prop_stick", bm, M["lacquer"], coll, smooth=True)
    part(ob, "stick", root)

    # --- legs, lyre, pedals ----------------------------------------------------------
    leg_prof = [(0.0, 0.0), (0.030, 0.0), (0.034, 0.012), (0.030, 0.07), (0.038, 0.075), (0.038, 0.085),
                (0.033, 0.09), (0.040, 0.30), (0.050, 0.52), (0.062, 0.54), (0.062, 0.565), (0.052, 0.57),
                (0.055, 0.64), (0.0, 0.64)]
    for i, (x, y) in enumerate([(-0.66, 0.30), (0.66, 0.30), (-0.42, 2.38)]):
        bm = bmesh.new()
        bm_lathe(bm, leg_prof[1:-1], center=(x, y, 0.0), seg=32)
        bmesh.ops.contextual_create(bm, geom=[v for v in bm.verts if abs(v.co.z - leg_prof[1][1]) < 1e-6])
        bmesh.ops.contextual_create(bm, geom=[v for v in bm.verts if abs(v.co.z - leg_prof[-2][1]) < 1e-6])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        ob = mesh_from_bmesh(f"leg_{i}", bm, M["lacquer"], coll, smooth=True)
        part(ob, "leg", root)
        bm = bmesh.new()   # brass caster
        bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=0.032, radius2=0.032, depth=0.02,
                              matrix=Matrix.Translation((x, y, 0.035)) @ Matrix.Rotation(math.pi / 2, 4, "Y"))
        bm_box(bm, (x - 0.014, y - 0.02, 0.045), (x + 0.014, y + 0.02, 0.075))
        ob = mesh_from_bmesh(f"caster_{i}", bm, M["brass"], coll, smooth=True)
        part(ob, "leg", root, group=f"leg_{i}")
    bm = bmesh.new()   # lyre: two posts + pedal box
    for x in (-0.09, 0.09):
        bm_box(bm, (x - 0.018, 0.30, 0.14), (x + 0.018, 0.34, 0.64))
    bm_box(bm, (-0.17, 0.27, 0.05), (0.17, 0.37, 0.145))
    ob = mesh_from_bmesh("lyre", bm, M["lacquer"], coll); add_bevel(ob, 0.006, 3)
    part(ob, "lyre", root)
    for i, x in enumerate((-0.07, 0.0, 0.07)):
        bm = bmesh.new()
        # slim lever widening to a rounded paddle
        pts = [(0.0065, 0.0), (0.0075, -0.05), (0.0130, -0.092)] + \
              [(0.0155 * math.cos(a), -0.118 + 0.0155 * math.sin(a)) for a in [-math.pi * i / 12 for i in range(1, 12)]] + \
              [(-0.0130, -0.092), (-0.0075, -0.05), (-0.0065, 0.0)]
        bm_prism(bm, [(x + px, 0.30 + py) for px, py in pts], 0.084, 0.093)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        ob = mesh_from_bmesh(f"pedal_{i}", bm, M["brass"], coll); add_bevel(ob, 0.0028, 4)
        origin_to(ob, (x, 0.30, 0.09))
        part(ob, "pedal", root, note=i, pivot=(0.30, 0.09))

    # --- bench (not part of the explosion) --------------------------------------------
    bm = bmesh.new()
    bm_box(bm, (-0.30, -0.78, 0.44), (0.30, -0.42, 0.50))
    for x in (-0.27, 0.27):
        bm_box(bm, (x - 0.025, -0.76, 0.0), (x + 0.025, -0.44, 0.44))
    ob = mesh_from_bmesh("bench", bm, M["lacquer"], coll); add_bevel(ob, 0.006, 3)
    ob.parent = root; ob["part"] = "bench"
    bm = bmesh.new()
    bm_box(bm, (-0.29, -0.77, 0.50), (0.29, -0.43, 0.535))
    ob = mesh_from_bmesh("bench_top", bm, M["velvet"], coll); add_bevel(ob, 0.012, 4)
    ob.parent = root; ob["part"] = "bench"

    # --- soundboard dust: points instanced as tiny spheres (moved by anim.py)
    from lib import mulberry32
    rnd = mulberry32(4242)
    pts, sizes = [], []
    while len(pts) < 900:
        if len(pts) < 550:      # dense where the dust macro looks
            x = -0.13 + 0.17 * rnd(); y = 1.36 + 0.22 * rnd()
        else:
            x = -0.20 + 0.32 * rnd(); y = 0.95 + 1.0 * rnd()
        pts.append((x, y, 0.8055 + 0.0006 * rnd()))
        sizes.append(0.00012 + 0.00040 * rnd() ** 3)
    me = bpy.data.meshes.new("dust")
    me.from_pydata(pts, [], [])
    a = me.attributes.new("size", "FLOAT", "POINT")
    a.data.foreach_set("value", sizes)
    dust = bpy.data.objects.new("dust", me)
    coll.objects.link(dust)
    ng = bpy.data.node_groups.new("dust_instances", "GeometryNodeTree")
    ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi = ng.nodes.new("NodeGroupInput"); go = ng.nodes.new("NodeGroupOutput")
    ico = ng.nodes.new("GeometryNodeMeshIcoSphere"); ico.inputs["Radius"].default_value = 1.0
    ico.inputs["Subdivisions"].default_value = 1
    nat = ng.nodes.new("GeometryNodeInputNamedAttribute"); nat.data_type = "FLOAT"
    nat.inputs["Name"].default_value = "size"
    iop = ng.nodes.new("GeometryNodeInstanceOnPoints")
    sm = ng.nodes.new("GeometryNodeSetMaterial")
    M["dust"] = principled("dust", (0.85, 0.84, 0.82), rough=0.6, sheen=1.0)
    M["dust"].node_tree.nodes["Principled BSDF"].inputs["Subsurface Weight"].default_value = 0.5
    sm.inputs["Material"].default_value = M["dust"]
    ng.links.new(gi.outputs[0], iop.inputs["Points"])
    ng.links.new(ico.outputs["Mesh"], iop.inputs["Instance"])
    ng.links.new(nat.outputs[0], iop.inputs["Scale"])
    ng.links.new(iop.outputs[0], sm.inputs["Geometry"])
    ng.links.new(sm.outputs[0], go.inputs[0])
    mod = dust.modifiers.new("inst", "NODES"); mod.node_group = ng
    part(dust, "dust", root)
    dust["rest"] = [c for p in pts for c in p]

    root["strings_meta"] = [[m["hx"], m["hz"], m["r"]] for m in strings_meta]
    return root, M
