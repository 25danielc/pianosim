"""Concert hall: stage, arched windows (rain glass), curtains, stalls, balcony,
night sky (world shader: moon + storm clouds + lightning), lights and haze.

World coordinates: audience toward -Y, back wall with windows at +Y, Z up,
stage floor at z = 0.  The piano sits around the origin (see lib.py).
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from lib import (add_bevel, bm_box, bm_prism, collection, mesh_from_bmesh, new_mat, node,
                 principled, srgb, uniform, mulberry32)

STAGE_FRONT = -3.6
BACK_Y = 8.0
WALL_T = 0.6
HALL_X = 11.0
HALL_BACK = -27.0
CEIL = 14.0
STALLS_Z = -1.1
WIN_XS = (-6.0, -3.0, 0.0, 3.0, 6.0)
WIN_W = 1.7
WIN_SILL = 1.4
WIN_SPRING = 6.2                  # arch springs here, radius = WIN_W / 2
MOON_DIR = Vector((-0.22, 1.0, 0.25)).normalized()      # direction TO the moon
MOON_EL = math.degrees(math.asin(MOON_DIR.z))


def window_outline(xc, n=24):
    r = WIN_W / 2
    pts = [(xc - r, WIN_SILL), (xc + r, WIN_SILL)]
    for i in range(n + 1):
        a = math.pi * i / n
        pts.append((xc + r * math.cos(a), WIN_SPRING + r * math.sin(a)))
    return pts            # (x, z), CCW seen from the hall (-Y looking +Y)... closed


# ------------------------------------------------------------------ materials
def materials():
    M = {}
    fl = principled("stage_boards", (0.020, 0.013, 0.009), rough=0.2, coat=0.6, coat_rough=0.06)
    nt = fl.node_tree; b = nt.nodes["Principled BSDF"]
    tc = node(nt, "ShaderNodeTexCoord", (-1300, 0))
    # boards run along X: 0.14 m wide, random length offsets via brick texture
    mp = node(nt, "ShaderNodeMapping", (-1100, 0))
    mp.inputs["Scale"].default_value = (1.0, 1.0, 1.0)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    brick = node(nt, "ShaderNodeTexBrick", (-850, 0), offset=0.37, squash=1.0,
                 **{"Scale": 1.0, "Mortar Size": 0.0012, "Brick Width": 1.9, "Row Height": 0.14,
                    "Mortar Smooth": 0.2, "Bias": 0.0})
    brick.inputs["Color1"].default_value = (0.024, 0.015, 0.010, 1)
    brick.inputs["Color2"].default_value = (0.014, 0.009, 0.006, 1)
    brick.inputs["Mortar"].default_value = (0.004, 0.003, 0.002, 1)
    nt.links.new(mp.outputs[0], brick.inputs["Vector"])
    grain = node(nt, "ShaderNodeTexNoise", (-850, -300), Scale=3.0, Detail=10.0, Roughness=0.7)
    gmap = node(nt, "ShaderNodeMapping", (-1050, -300))
    gmap.inputs["Scale"].default_value = (0.4, 18.0, 1.0)
    nt.links.new(tc.outputs["Object"], gmap.inputs["Vector"]); nt.links.new(gmap.outputs[0], grain.inputs["Vector"])
    mix = node(nt, "ShaderNodeMix", (-500, 100), data_type="RGBA", blend_type="MULTIPLY")
    mix.inputs[0].default_value = 0.6
    gr = node(nt, "ShaderNodeMapRange", (-650, -300), **{"From Min": 0.3, "From Max": 0.7, "To Min": 0.7, "To Max": 1.25})
    nt.links.new(grain.outputs["Fac"], gr.inputs["Value"])
    nt.links.new(brick.outputs["Color"], mix.inputs[6]); nt.links.new(gr.outputs[0], mix.inputs[7])
    nt.links.new(mix.outputs[2], b.inputs["Base Color"])
    rr = node(nt, "ShaderNodeMapRange", (-500, -300), **{"From Min": 0.3, "From Max": 0.7, "To Min": 0.12, "To Max": 0.32})
    nt.links.new(grain.outputs["Fac"], rr.inputs["Value"]); nt.links.new(rr.outputs[0], b.inputs["Roughness"])
    bump = node(nt, "ShaderNodeBump", (-300, -450), Strength=0.25, Distance=0.002)
    nt.links.new(brick.outputs["Fac"], bump.inputs["Height"]); nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    M["boards"] = fl

    M["wall"] = principled("wall", (0.016, 0.017, 0.021), rough=0.75)
    M["panel"] = principled("panel", (0.010, 0.009, 0.010), rough=0.35, coat=0.4, coat_rough=0.2)
    M["frame"] = principled("window_frame", (0.010, 0.011, 0.013), rough=0.45, metal=0.3)
    M["seat"] = principled("seat_velvet", tuple(c * 0.55 for c in srgb("#0E1A2E")), rough=1.0, sheen=1.0)
    M["seatwood"] = principled("seat_wood", (0.012, 0.008, 0.006), rough=0.4, coat=0.3)
    M["gilt"] = principled("gilt", (0.36, 0.26, 0.12), rough=0.5, metal=1.0)
    cur = principled("curtain_velvet", tuple(c * 0.75 for c in srgb("#0E1A2E")), rough=1.0, sheen=1.0)
    cur.node_tree.nodes["Principled BSDF"].inputs["Sheen Roughness"].default_value = 0.4
    M["curtain"] = cur
    M["glass"] = rain_glass()
    M["bolt"] = bolt_material()
    return M


def rain_glass():
    """Window glass with procedural rain: beads + downward streaks, density and
    speed driven by U_rain / U_time.  Shadow rays pass straight through so the
    moon and lightning still throw window shadows into the hall."""
    m = new_mat("rain_glass")
    nt = m.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    out = nt.nodes["Material Output"]
    t = uniform(nt, "time", 0.0, (-1700, 300))
    rain = uniform(nt, "rain", 0.0, (-1700, 200))
    tc = node(nt, "ShaderNodeTexCoord", (-1700, 0))
    sep = node(nt, "ShaderNodeSeparateXYZ", (-1500, 0))
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    # beads: static voronoi cells, each cell shows a bead if its random < rain
    bead_v = node(nt, "ShaderNodeCombineXYZ", (-1300, 100))
    nt.links.new(sep.outputs["X"], bead_v.inputs[0]); nt.links.new(sep.outputs["Z"], bead_v.inputs[1])
    vor = node(nt, "ShaderNodeTexVoronoi", (-1100, 100), Scale=70.0, Randomness=1.0)
    nt.links.new(bead_v.outputs[0], vor.inputs["Vector"])
    sepc = node(nt, "ShaderNodeSeparateColor", (-900, 0))
    nt.links.new(vor.outputs["Color"], sepc.inputs[0])
    show = node(nt, "ShaderNodeMath", (-700, 0), operation="LESS_THAN")
    nt.links.new(sepc.outputs[0], show.inputs[0]); nt.links.new(rain.outputs[0], show.inputs[1])
    shape = node(nt, "ShaderNodeMapRange", (-900, 200), **{"From Min": 0.38, "From Max": 0.0, "To Min": 0.0, "To Max": 1.0})
    shape.interpolation_type = "SMOOTHERSTEP"
    nt.links.new(vor.outputs["Distance"], shape.inputs["Value"])
    bead = node(nt, "ShaderNodeMath", (-500, 150), operation="MULTIPLY")
    nt.links.new(shape.outputs[0], bead.inputs[0]); nt.links.new(show.outputs[0], bead.inputs[1])
    # streaks: stretched cells sliding down the glass
    spd = node(nt, "ShaderNodeMath", (-1300, -250), operation="MULTIPLY")
    nt.links.new(t.outputs[0], spd.inputs[0]); spd.inputs[1].default_value = 0.55
    zz = node(nt, "ShaderNodeMath", (-1100, -250), operation="ADD")
    nt.links.new(sep.outputs["Z"], zz.inputs[0]); nt.links.new(spd.outputs[0], zz.inputs[1])
    sv = node(nt, "ShaderNodeCombineXYZ", (-950, -250))
    nt.links.new(sep.outputs["X"], sv.inputs[0]); nt.links.new(zz.outputs[0], sv.inputs[1])
    mp = node(nt, "ShaderNodeMapping", (-800, -250))
    mp.inputs["Scale"].default_value = (90.0, 6.0, 1.0)
    nt.links.new(sv.outputs[0], mp.inputs["Vector"])
    vs = node(nt, "ShaderNodeTexVoronoi", (-600, -250), Scale=1.0, Randomness=1.0)
    nt.links.new(mp.outputs[0], vs.inputs["Vector"])
    sc2 = node(nt, "ShaderNodeSeparateColor", (-400, -350))
    nt.links.new(vs.outputs["Color"], sc2.inputs[0])
    r2 = node(nt, "ShaderNodeMath", (-250, -350), operation="MULTIPLY")
    nt.links.new(rain.outputs[0], r2.inputs[0]); r2.inputs[1].default_value = 0.55
    show2 = node(nt, "ShaderNodeMath", (-100, -350), operation="LESS_THAN")
    nt.links.new(sc2.outputs[0], show2.inputs[0]); nt.links.new(r2.outputs[0], show2.inputs[1])
    sshape = node(nt, "ShaderNodeMapRange", (-400, -150), **{"From Min": 0.30, "From Max": 0.0, "To Min": 0.0, "To Max": 1.0})
    sshape.interpolation_type = "SMOOTHERSTEP"
    nt.links.new(vs.outputs["Distance"], sshape.inputs["Value"])
    streak = node(nt, "ShaderNodeMath", (-100, -150), operation="MULTIPLY")
    nt.links.new(sshape.outputs[0], streak.inputs[0]); nt.links.new(show2.outputs[0], streak.inputs[1])
    h = node(nt, "ShaderNodeMath", (50, 0), operation="MAXIMUM")
    nt.links.new(bead.outputs[0], h.inputs[0]); nt.links.new(streak.outputs[0], h.inputs[1])
    bump = node(nt, "ShaderNodeBump", (250, 0), Strength=1.0, Distance=0.0015)
    nt.links.new(h.outputs[0], bump.inputs["Height"])
    glass = node(nt, "ShaderNodeBsdfPrincipled", (450, 100))
    glass.inputs["Base Color"].default_value = (0.9, 0.93, 0.96, 1)
    glass.inputs["Transmission Weight"].default_value = 1.0
    glass.inputs["Roughness"].default_value = 0.02
    glass.inputs["IOR"].default_value = 1.33
    nt.links.new(bump.outputs["Normal"], glass.inputs["Normal"])
    tr = node(nt, "ShaderNodeBsdfTransparent", (450, -200))
    lp = node(nt, "ShaderNodeLightPath", (450, 400))
    mix = node(nt, "ShaderNodeMixShader", (700, 0))
    nt.links.new(lp.outputs["Is Shadow Ray"], mix.inputs[0])
    nt.links.new(glass.outputs[0], mix.inputs[1]); nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    for attr, val in (("use_raytrace_refraction", True), ("thickness_mode", "SLAB"),
                      ("surface_render_method", "DITHERED"), ("use_transparent_shadow", True)):
        if hasattr(m, attr):
            setattr(m, attr, val)
    return m


def bolt_material():
    m = new_mat("bolt")
    nt = m.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    em = node(nt, "ShaderNodeEmission", (0, 0))
    em.inputs["Color"].default_value = (0.85, 0.9, 1.0, 1)
    s = uniform(nt, "bolt", 0.0, (-300, 0))
    k = node(nt, "ShaderNodeMath", (-150, -100), operation="MULTIPLY")
    nt.links.new(s.outputs[0], k.inputs[0]); k.inputs[1].default_value = 400.0
    nt.links.new(k.outputs[0], em.inputs["Strength"])
    nt.links.new(em.outputs[0], nt.nodes["Material Output"].inputs["Surface"])
    return m


# ------------------------------------------------------------------ world (sky)
def world():
    w = bpy.data.worlds.get("night") or bpy.data.worlds.new("night")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = node(nt, "ShaderNodeOutputWorld", (1800, 0))
    t = uniform(nt, "time", 0.0, (-1800, 600))
    cloud = uniform(nt, "cloud", 0.1, (-1800, 500))       # 0 clear .. 1 overcast
    cover = uniform(nt, "moon_cover", 0.0, (-1800, 400))  # extra occlusion of the moon
    flash = uniform(nt, "flash", 0.0, (-1800, 300))       # lightning in the clouds
    fx = uniform(nt, "flash_x", 0.0, (-1800, 200))        # where in the sky (uv x)
    moonk = uniform(nt, "moon", 1.0, (-1800, 100))        # moon brightness multiplier
    tc = node(nt, "ShaderNodeTexCoord", (-1800, -100))
    dirn = node(nt, "ShaderNodeVectorMath", (-1600, -100), operation="NORMALIZE")
    nt.links.new(tc.outputs["Generated"], dirn.inputs[0])
    sep = node(nt, "ShaderNodeSeparateXYZ", (-1400, -100))
    nt.links.new(dirn.outputs[0], sep.inputs[0])
    # cloud-plane uv = (x, z) / max(y, .05)  (we look out toward +Y)
    ymax = node(nt, "ShaderNodeMath", (-1250, -250), operation="MAXIMUM")
    nt.links.new(sep.outputs["Y"], ymax.inputs[0]); ymax.inputs[1].default_value = 0.05
    u = node(nt, "ShaderNodeMath", (-1100, -100), operation="DIVIDE")
    nt.links.new(sep.outputs["X"], u.inputs[0]); nt.links.new(ymax.outputs[0], u.inputs[1])
    v = node(nt, "ShaderNodeMath", (-1100, -250), operation="DIVIDE")
    nt.links.new(sep.outputs["Z"], v.inputs[0]); nt.links.new(ymax.outputs[0], v.inputs[1])
    drift = node(nt, "ShaderNodeMath", (-1100, 50), operation="MULTIPLY")
    nt.links.new(t.outputs[0], drift.inputs[0]); drift.inputs[1].default_value = 0.035
    ud = node(nt, "ShaderNodeMath", (-950, -100), operation="ADD")
    nt.links.new(u.outputs[0], ud.inputs[0]); nt.links.new(drift.outputs[0], ud.inputs[1])
    uv = node(nt, "ShaderNodeCombineXYZ", (-800, -150))
    nt.links.new(ud.outputs[0], uv.inputs[0]); nt.links.new(v.outputs[0], uv.inputs[1])
    tw = node(nt, "ShaderNodeMath", (-800, 50), operation="MULTIPLY")
    nt.links.new(t.outputs[0], tw.inputs[0]); tw.inputs[1].default_value = 0.02
    nz = node(nt, "ShaderNodeTexNoise", (-600, -150), noise_dimensions="4D", Scale=1.3, Detail=10.0,
              Roughness=0.62, Distortion=0.4)
    nt.links.new(uv.outputs[0], nz.inputs["Vector"]); nt.links.new(tw.outputs[0], nz.inputs["W"])
    # coverage threshold falls as the storm grows
    lo = node(nt, "ShaderNodeMath", (-600, 150), operation="MULTIPLY_ADD")
    nt.links.new(cloud.outputs[0], lo.inputs[0]); lo.inputs[1].default_value = -0.30; lo.inputs[2].default_value = 0.66
    hi = node(nt, "ShaderNodeMath", (-450, 150), operation="ADD")
    nt.links.new(lo.outputs[0], hi.inputs[0]); hi.inputs[1].default_value = 0.16
    cm = node(nt, "ShaderNodeMapRange", (-300, -100), interpolation_type="SMOOTHSTEP")
    nt.links.new(nz.outputs["Fac"], cm.inputs["Value"])
    nt.links.new(lo.outputs[0], cm.inputs["From Min"]); nt.links.new(hi.outputs[0], cm.inputs["From Max"])
    # moon
    md = node(nt, "ShaderNodeVectorMath", (-1400, 300), operation="DOT_PRODUCT")
    md.inputs[1].default_value = tuple(MOON_DIR)
    nt.links.new(dirn.outputs[0], md.inputs[0])
    disc = node(nt, "ShaderNodeMapRange", (-1150, 400), interpolation_type="SMOOTHSTEP",
                **{"From Min": math.cos(math.radians(0.80)), "From Max": math.cos(math.radians(0.70))})
    nt.links.new(md.outputs["Value"], disc.inputs["Value"])
    halo1 = node(nt, "ShaderNodeMath", (-1150, 250), operation="POWER")
    clamp0 = node(nt, "ShaderNodeMath", (-1300, 250), operation="MAXIMUM")
    nt.links.new(md.outputs["Value"], clamp0.inputs[0]); clamp0.inputs[1].default_value = 0.0
    nt.links.new(clamp0.outputs[0], halo1.inputs[0]); halo1.inputs[1].default_value = 900.0
    halo2 = node(nt, "ShaderNodeMath", (-1150, 150), operation="POWER")
    nt.links.new(clamp0.outputs[0], halo2.inputs[0]); halo2.inputs[1].default_value = 9.0
    # mare texture on the disc
    mare = node(nt, "ShaderNodeTexNoise", (-1150, 600), Scale=900.0, Detail=4.0)
    nt.links.new(dirn.outputs[0], mare.inputs["Vector"])
    mr = node(nt, "ShaderNodeMapRange", (-950, 600), **{"From Min": 0.35, "From Max": 0.65, "To Min": 0.72, "To Max": 1.0})
    nt.links.new(mare.outputs["Fac"], mr.inputs["Value"])
    discm = node(nt, "ShaderNodeMath", (-800, 450), operation="MULTIPLY")
    nt.links.new(disc.outputs[0], discm.inputs[0]); nt.links.new(mr.outputs[0], discm.inputs[1])
    # moon visibility = (1 - 0.97*cloud mask) * (1 - cover)
    vis1 = node(nt, "ShaderNodeMath", (-150, 300), operation="MULTIPLY_ADD")
    nt.links.new(cm.outputs[0], vis1.inputs[0]); vis1.inputs[1].default_value = -0.97; vis1.inputs[2].default_value = 1.0
    ncov = node(nt, "ShaderNodeMath", (-150, 450), operation="SUBTRACT")
    ncov.inputs[0].default_value = 1.0; nt.links.new(cover.outputs[0], ncov.inputs[1])
    vis = node(nt, "ShaderNodeMath", (0, 400), operation="MULTIPLY")
    nt.links.new(vis1.outputs[0], vis.inputs[0]); nt.links.new(ncov.outputs[0], vis.inputs[1])
    vism = node(nt, "ShaderNodeMath", (150, 400), operation="MULTIPLY")
    nt.links.new(vis.outputs[0], vism.inputs[0]); nt.links.new(moonk.outputs[0], vism.inputs[1])
    moonc = srgb("#CFE0FF")
    # moon + halo radiance
    mrad = node(nt, "ShaderNodeMath", (300, 500), operation="MULTIPLY_ADD")
    nt.links.new(discm.outputs[0], mrad.inputs[0]); mrad.inputs[1].default_value = 40.0
    h1 = node(nt, "ShaderNodeMath", (150, 250), operation="MULTIPLY")
    nt.links.new(halo1.outputs[0], h1.inputs[0]); h1.inputs[1].default_value = 1.2
    h2 = node(nt, "ShaderNodeMath", (300, 250), operation="MULTIPLY_ADD")
    nt.links.new(halo2.outputs[0], h2.inputs[0]); h2.inputs[1].default_value = 0.012; nt.links.new(h1.outputs[0], h2.inputs[2])
    nt.links.new(h2.outputs[0], mrad.inputs[2])
    mtot = node(nt, "ShaderNodeMath", (450, 450), operation="MULTIPLY")
    nt.links.new(mrad.outputs[0], mtot.inputs[0]); nt.links.new(vism.outputs[0], mtot.inputs[1])
    # sky gradient (midnight near the horizon -> black overhead)
    grad = node(nt, "ShaderNodeMapRange", (-900, -500), **{"From Min": 0.0, "From Max": 0.6, "To Min": 1.0, "To Max": 0.0})
    nt.links.new(sep.outputs["Z"], grad.inputs["Value"])
    skyc = node(nt, "ShaderNodeMix", (-600, -500), data_type="RGBA")
    skyc.inputs[6].default_value = (0.0016, 0.0024, 0.0050, 1)
    skyc.inputs[7].default_value = (*[c * 1.3 for c in srgb("#0E1A2E")], 1)
    nt.links.new(grad.outputs[0], skyc.inputs[0])
    # cloud colour: dark, silver-lit near the moon, white-blue in a flash
    lit = node(nt, "ShaderNodeMath", (-150, 50), operation="MULTIPLY")
    nt.links.new(halo2.outputs[0], lit.inputs[0]); lit.inputs[1].default_value = 0.06
    litm = node(nt, "ShaderNodeMath", (0, 50), operation="MULTIPLY")
    nt.links.new(lit.outputs[0], litm.inputs[0]); nt.links.new(moonk.outputs[0], litm.inputs[1])
    # flash pattern: brightest around flash_x, modulated by cloud density
    fdx = node(nt, "ShaderNodeMath", (-450, -700), operation="SUBTRACT")
    nt.links.new(u.outputs[0], fdx.inputs[0]); nt.links.new(fx.outputs[0], fdx.inputs[1])
    fsq = node(nt, "ShaderNodeMath", (-300, -700), operation="MULTIPLY")
    nt.links.new(fdx.outputs[0], fsq.inputs[0]); nt.links.new(fdx.outputs[0], fsq.inputs[1])
    fex = node(nt, "ShaderNodeMath", (-150, -700), operation="MULTIPLY")
    nt.links.new(fsq.outputs[0], fex.inputs[0]); fex.inputs[1].default_value = -1.2
    fexp = node(nt, "ShaderNodeMath", (0, -700), operation="EXPONENT")
    nt.links.new(fex.outputs[0], fexp.inputs[0])
    fl0 = node(nt, "ShaderNodeMath", (150, -700), operation="MULTIPLY_ADD")
    nt.links.new(fexp.outputs[0], fl0.inputs[0]); fl0.inputs[1].default_value = 0.85; fl0.inputs[2].default_value = 0.15
    fl1 = node(nt, "ShaderNodeMath", (300, -700), operation="MULTIPLY")
    nt.links.new(fl0.outputs[0], fl1.inputs[0]); nt.links.new(flash.outputs[0], fl1.inputs[1])
    fl2 = node(nt, "ShaderNodeMath", (450, -700), operation="MULTIPLY")
    nt.links.new(fl1.outputs[0], fl2.inputs[0]); fl2.inputs[1].default_value = 6.0
    cbright = node(nt, "ShaderNodeMath", (600, -300), operation="ADD")
    nt.links.new(litm.outputs[0], cbright.inputs[0]); nt.links.new(fl2.outputs[0], cbright.inputs[1])
    cbase = node(nt, "ShaderNodeMath", (750, -300), operation="ADD")
    nt.links.new(cbright.outputs[0], cbase.inputs[0]); cbase.inputs[1].default_value = 0.0050
    ccol = node(nt, "ShaderNodeMix", (900, -300), data_type="RGBA", blend_type="MULTIPLY")
    ccol.inputs[0].default_value = 1.0
    ccol.inputs[6].default_value = (*moonc, 1)
    cval = node(nt, "ShaderNodeCombineColor", (750, -450))
    for i in range(3):
        nt.links.new(cbase.outputs[0], cval.inputs[i])
    nt.links.new(cval.outputs[0], ccol.inputs[7])
    # the clear sky also flashes a little
    skyfl = node(nt, "ShaderNodeMix", (600, -550), data_type="RGBA", blend_type="ADD")
    nt.links.new(skyc.outputs[2], skyfl.inputs[6])
    f3 = node(nt, "ShaderNodeMath", (450, -850), operation="MULTIPLY")
    nt.links.new(fl1.outputs[0], f3.inputs[0]); f3.inputs[1].default_value = 0.4
    nt.links.new(f3.outputs[0], skyfl.inputs[0]); skyfl.inputs[7].default_value = (*moonc, 1)
    # composite: sky / clouds by mask, + moon
    comp = node(nt, "ShaderNodeMix", (1100, -300), data_type="RGBA")
    nt.links.new(cm.outputs[0], comp.inputs[0])
    nt.links.new(skyfl.outputs[2], comp.inputs[6]); nt.links.new(ccol.outputs[2], comp.inputs[7])
    madd = node(nt, "ShaderNodeMix", (1300, 0), data_type="RGBA", blend_type="ADD")
    madd.inputs[0].default_value = 1.0
    nt.links.new(comp.outputs[2], madd.inputs[6])
    mcol = node(nt, "ShaderNodeMix", (1100, 300), data_type="RGBA", blend_type="MULTIPLY")
    mcol.inputs[0].default_value = 1.0; mcol.inputs[6].default_value = (*moonc, 1)
    mv = node(nt, "ShaderNodeCombineColor", (950, 450))
    for i in range(3):
        nt.links.new(mtot.outputs[0], mv.inputs[i])
    nt.links.new(mv.outputs[0], mcol.inputs[7])
    nt.links.new(mcol.outputs[2], madd.inputs[7])
    # camera rays see the full sky; everything else gets a dimmed copy (the
    # moon / lightning suns carry the real illumination; avoids noise)
    bg = node(nt, "ShaderNodeBackground", (1500, 0))
    nt.links.new(madd.outputs[2], bg.inputs["Color"])
    lp = node(nt, "ShaderNodeLightPath", (1300, 300))
    st = node(nt, "ShaderNodeMapRange", (1450, 300), **{"From Min": 0, "From Max": 1, "To Min": 0.25, "To Max": 1.0})
    nt.links.new(lp.outputs["Is Camera Ray"], st.inputs["Value"])
    nt.links.new(st.outputs[0], bg.inputs["Strength"])
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    return w


# ------------------------------------------------------------------ geometry
def build(coll=None):
    coll = coll or collection("Hall")
    M = materials()
    world()

    # stage floor + front lip
    bm = bmesh.new()
    bm_box(bm, (-HALL_X, STAGE_FRONT, STALLS_Z), (HALL_X, BACK_Y, 0.0))
    ob = mesh_from_bmesh("stage", bm, M["boards"], coll); add_bevel(ob, 0.01, 2)

    # back wall with arched window openings (boolean) + pilasters
    bm = bmesh.new()
    bm_box(bm, (-HALL_X, BACK_Y, STALLS_Z), (HALL_X, BACK_Y + WALL_T, CEIL))
    wall = mesh_from_bmesh("back_wall", bm, M["wall"], coll)
    cut_objs = []
    for xc in WIN_XS:
        pts = window_outline(xc)
        bm = bmesh.new()
        vf = [bm.verts.new((x, BACK_Y - 0.5, z)) for x, z in pts]
        vb = [bm.verts.new((x, BACK_Y + WALL_T + 0.5, z)) for x, z in pts]
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((vf[i], vf[j], vb[j], vb[i]))
        bm.faces.new(list(reversed(vf))); bm.faces.new(vb)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        cut_objs.append(mesh_from_bmesh("wcut", bm, None, coll))
    for c in cut_objs:
        m = wall.modifiers.new("cut", "BOOLEAN"); m.object = c; m.operation = "DIFFERENCE"; m.solver = "EXACT"
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(wall.evaluated_get(dg))
    wall.modifiers.clear(); old = wall.data; wall.data = me; bpy.data.meshes.remove(old)
    for c in cut_objs:
        bpy.data.objects.remove(c)

    bm = bmesh.new()
    for x in [-7.5, -4.5, -1.5, 1.5, 4.5, 7.5]:
        bm_box(bm, (x - 0.32, BACK_Y - 0.16, 0.0), (x + 0.32, BACK_Y, 9.2))
        bm_box(bm, (x - 0.40, BACK_Y - 0.22, 9.2), (x + 0.40, BACK_Y, 9.45))
        bm_box(bm, (x - 0.40, BACK_Y - 0.22, 0.0), (x + 0.40, BACK_Y, 0.35))
    bm_box(bm, (-HALL_X, BACK_Y - 0.25, 9.45), (HALL_X, BACK_Y, 9.75))      # cornice
    bm_box(bm, (-HALL_X, BACK_Y - 0.12, 0.0), (HALL_X, BACK_Y, 0.9))         # wainscot
    ob = mesh_from_bmesh("pilasters", bm, M["panel"], coll); add_bevel(ob, 0.015, 2)

    # window frames: outer frame, 2 mullions, transoms, arch ribs; glass slab
    for xc in WIN_XS:
        r = WIN_W / 2
        bm = bmesh.new()
        yc = BACK_Y + WALL_T * 0.5
        d0, d1 = yc - 0.05, yc + 0.05
        s = 0.035
        for xm in (xc - r / 3 * 1.0, xc + r / 3 * 1.0):
            bm_box(bm, (xm - s, d0, WIN_SILL), (xm + s, d1, WIN_SPRING + math.sqrt(max(0, r * r - (xm - xc) ** 2))))
        for z in (2.6, 3.8, 5.0, WIN_SPRING):
            bm_box(bm, (xc - r, d0, z - s), (xc + r, d1, z + s))
        for i in range(1, 4):
            a = math.pi * i / 4
            p = Matrix.Translation((xc, yc, WIN_SPRING)) @ Matrix.Rotation(-(a - math.pi / 2), 4, "Y")
            bm_box(bm, (-s, -0.05, 0.0), (s, 0.05, r), matrix=p)
        # outer frame band following the opening
        pts = window_outline(xc, 32)
        for (x0, z0), (x1, z1) in zip(pts, pts[1:] + pts[:1]):
            L = math.hypot(x1 - x0, z1 - z0)
            if L < 1e-6:
                continue
            ang = math.atan2(z1 - z0, x1 - x0)
            p = Matrix.Translation((x0, yc, z0)) @ Matrix.Rotation(-ang, 4, "Y")
            bm_box(bm, (0, -0.06, -0.05), (L, 0.06, 0.05), matrix=p)
        ob = mesh_from_bmesh(f"window_frame_{xc:+.0f}", bm, M["frame"], coll)
        # glass: 8 mm slab inside the frame plane
        pts = window_outline(xc, 32)
        bm = bmesh.new()
        vf = [bm.verts.new((x, yc - 0.004, z)) for x, z in pts]
        vb = [bm.verts.new((x, yc + 0.004, z)) for x, z in pts]
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((vf[i], vf[j], vb[j], vb[i]))
        bm.faces.new(list(reversed(vf))); bm.faces.new(vb)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        g = mesh_from_bmesh(f"glass_{xc:+.0f}", bm, M["glass"], coll)
        g["part"] = "glass"

    # side walls, front wall, ceiling (closed box so only windows admit light)
    bm = bmesh.new()
    for s in (-1, 1):
        bm_box(bm, (s * HALL_X - (0.5 if s > 0 else 0) + (0 if s > 0 else -0.5), HALL_BACK, STALLS_Z - 2),
               (s * HALL_X + (0.5 if s > 0 else 0), BACK_Y + WALL_T, CEIL + 0.5))
    bm_box(bm, (-HALL_X - 0.5, HALL_BACK - 0.5, STALLS_Z - 2), (HALL_X + 0.5, HALL_BACK, CEIL + 0.5))
    bm_box(bm, (-HALL_X - 0.5, HALL_BACK - 0.5, CEIL), (HALL_X + 0.5, BACK_Y + WALL_T, CEIL + 0.5))
    ob = mesh_from_bmesh("walls", bm, M["wall"], coll)
    # side-wall panelling: tall dark panels that catch lightning
    bm = bmesh.new()
    for s in (-1, 1):
        for y in [6.0, 3.0, 0.0, -3.0]:
            bm_box(bm, (s * HALL_X - 0.12 * (s > 0) - 0.0, y - 1.1, 0.4), (s * HALL_X + 0.12 * (s < 0), y + 1.1, 6.5))
    ob = mesh_from_bmesh("side_panels", bm, M["panel"], coll); add_bevel(ob, 0.02, 2)

    # stalls: raked floor + seats
    bm = bmesh.new()
    rows = []
    y = STAGE_FRONT - 1.6
    i = 0
    while y > HALL_BACK + 1.5:
        z = STALLS_Z + max(0.0, (STAGE_FRONT - 1.6 - y)) * 0.11
        rows.append((y, z))
        bm_box(bm, (-HALL_X, y - 0.95, STALLS_Z - 1.5), (HALL_X, y, z))
        y -= 0.95; i += 1
    bm_box(bm, (-HALL_X, STAGE_FRONT - 1.6, STALLS_Z - 1.5), (HALL_X, STAGE_FRONT, STALLS_Z))
    ob = mesh_from_bmesh("stalls_floor", bm, M["wall"], coll)
    rnd = mulberry32(7)
    bmv = bmesh.new(); bmw = bmesh.new()
    def seat(bmv, bmw, x, y, z, facing=1):
        # facing +1 -> seat looks toward +Y (the stage)
        f = facing
        bm_box(bmv, (x - 0.24, y - 0.24, z + 0.40), (x + 0.24, y + 0.20, z + 0.50))          # cushion
        bm_box(bmv, (x - 0.24, y - 0.30, z + 0.45), (x + 0.24, y - 0.22, z + 0.98))          # back
        bm_box(bmw, (x - 0.28, y - 0.30, z + 0.0), (x - 0.25, y + 0.18, z + 0.66))           # arm/standard
    for (ry, rz) in rows[:-1]:
        x = -9.6
        while x <= 9.6:
            if abs(x) > 0.75 and abs(abs(x) - 6.6) > 0.5:
                seat(bmv, bmw, x, ry - 0.45, rz)
            x += 0.56
    # balcony
    BAL_Y, BAL_Z = -15.0, 4.2
    bal_front = [(x, BAL_Y + 3.0 * (abs(x) / HALL_X) ** 2) for x in [-HALL_X + i * (2 * HALL_X / 40) for i in range(41)]]
    bmb = bmesh.new()
    for (x0, y0), (x1, y1) in zip(bal_front, bal_front[1:]):
        vs = [bmb.verts.new(p) for p in [(x0, y0, BAL_Z - 0.6), (x1, y1, BAL_Z - 0.6), (x1, y1, BAL_Z + 1.0), (x0, y0, BAL_Z + 1.0),
                                         (x0, y0 - 0.25, BAL_Z - 0.6), (x1, y1 - 0.25, BAL_Z - 0.6), (x1, y1 - 0.25, BAL_Z + 1.0), (x0, y0 - 0.25, BAL_Z + 1.0)]]
        for f in [(0, 1, 2, 3), (5, 4, 7, 6), (3, 2, 6, 7), (4, 5, 1, 0)]:
            bmb.faces.new([vs[i] for i in f])
    bmesh.ops.recalc_face_normals(bmb, faces=bmb.faces)
    ob = mesh_from_bmesh("balcony_front", bmb, M["panel"], coll)
    bmg = bmesh.new()
    for (x0, y0), (x1, y1) in zip(bal_front, bal_front[1:]):
        L = math.hypot(x1 - x0, y1 - y0); ang = math.atan2(y1 - y0, x1 - x0)
        p = Matrix.Translation((x0, y0 + 0.02, BAL_Z + 1.0)) @ Matrix.Rotation(ang, 4, "Z")
        bm_box(bmg, (0, -0.04, 0.0), (L, 0.04, 0.05), matrix=p)
        p2 = Matrix.Translation((x0, y0 + 0.01, BAL_Z + 0.25)) @ Matrix.Rotation(ang, 4, "Z")
        bm_box(bmg, (0, -0.02, 0.0), (L, 0.02, 0.025), matrix=p2)
    ob = mesh_from_bmesh("balcony_gilt", bmg, M["gilt"], coll)
    bm2 = bmesh.new()
    tiers = []
    for i in range(9):
        yb = BAL_Y - 0.6 - i * 0.95
        zb = BAL_Z + i * 0.38
        tiers.append((yb, zb))
        bm_box(bm2, (-HALL_X, yb - 0.95, BAL_Z - 0.6), (HALL_X, yb + 3.2 if i == 0 else yb, zb))
    ob = mesh_from_bmesh("balcony_floor", bm2, M["wall"], coll)
    for (ty, tz) in tiers[1:]:
        x = -9.8
        while x <= 9.8:
            if abs(x) > 0.75:
                seat(bmv, bmw, x, ty - 0.45, tz)
            x += 0.56
    mesh_from_bmesh("seats", bmv, M["seat"], coll)
    mesh_from_bmesh("seat_frames", bmw, M["seatwood"], coll)

    # curtains: two pleated drapes per window (cloth-ready grids, pinned top row)
    curtains = []
    for xc in WIN_XS:
        for side in (-1, 1):
            xin = xc + side * (WIN_W / 2 - 0.30)
            xout = xc + side * (WIN_W / 2 + 0.75)
            x0, x1 = sorted((xin, xout))
            nx, nz = 36, 70
            bm = bmesh.new()
            rows_v = []
            for iz in range(nz + 1):
                z = 9.0 - 9.0 * iz / nz + 0.05
                row = []
                for ix in range(nx + 1):
                    x = x0 + (x1 - x0) * ix / nx
                    y = BACK_Y - 0.45 - 0.07 * math.sin(ix / nx * 2 * math.pi * 6)
                    row.append(bm.verts.new((x, y, z)))
                rows_v.append(row)
            for iz in range(nz):
                for ix in range(nx):
                    bm.faces.new((rows_v[iz][ix], rows_v[iz][ix + 1], rows_v[iz + 1][ix + 1], rows_v[iz + 1][ix]))
            ob = mesh_from_bmesh(f"curtain_{xc:+.0f}_{'L' if side < 0 else 'R'}", bm, M["curtain"], coll, smooth=True)
            vg = ob.vertex_groups.new(name="pin")
            vg.add([v.index for v in ob.data.vertices if v.co.z > 9.0 - 1e-3], 1.0, "REPLACE")
            sol = ob.modifiers.new("solid", "SOLIDIFY"); sol.thickness = 0.012
            ob["part"] = "curtain"
            curtains.append(ob)
        bm = bmesh.new()   # curtain rod
        from lib import bm_tube
        bm_tube(bm, (xc - WIN_W / 2 - 0.9, BACK_Y - 0.45, 9.08), (xc + WIN_W / 2 + 0.9, BACK_Y - 0.45, 9.08), 0.025, seg=12)
        mesh_from_bmesh(f"rod_{xc:+.0f}", bm, M["gilt"], coll, smooth=True)

    # lightning bolt meshes (emissive, far outside, only visible on big strikes)
    bolts = []
    for bi in range(3):
        rnd = mulberry32(101 + bi)
        bm = bmesh.new()
        def branch(p, d, length, width, depth):
            pts = [p]
            seg = 22
            cur = Vector(p)
            for s in range(seg):
                jitter = Vector(((rnd() - 0.5) * 0.9, (rnd() - 0.5) * 0.3, 0))
                cur = cur + (d + jitter).normalized() * (length / seg)
                pts.append(cur.copy())
                if depth < 2 and rnd() < 0.12:
                    nd = (d + Vector(((rnd() - 0.5) * 2.2, 0, 0))).normalized()
                    branch(cur.copy(), nd, length * 0.35, width * 0.55, depth + 1)
            from lib import bm_tube as tube
            for a, b in zip(pts, pts[1:]):
                tube(bm, a, b, width, seg=5)
        branch((0, 0, 0), Vector((0, 0, -1)), 45.0, 0.12, 0)
        ob = mesh_from_bmesh(f"bolt_{bi}", bm, M["bolt"], coll)
        ob.location = (0, 120, 60)
        ob.visible_shadow = False
        ob.hide_render = True
        ob["part"] = "bolt"
        bolts.append(ob)

    # haze: a volume box over the stage (spot beam + window shafts)
    bm = bmesh.new()
    bm_box(bm, (-9.5, STAGE_FRONT - 3.0, 0.0), (9.5, BACK_Y - 0.05, 12.5))
    haze = mesh_from_bmesh("haze", bm, None, coll)
    hm = new_mat("haze")
    nt = hm.node_tree; nt.nodes.remove(nt.nodes["Principled BSDF"])
    dens = uniform(nt, "haze", 0.0065, (-700, 200))
    tc = node(nt, "ShaderNodeTexCoord", (-900, -100))
    nz = node(nt, "ShaderNodeTexNoise", (-700, -100), Scale=0.35, Detail=3.0, noise_dimensions="4D")
    tt = uniform(nt, "time", 0.0, (-900, -300))
    tw = node(nt, "ShaderNodeMath", (-750, -300), operation="MULTIPLY")
    nt.links.new(tt.outputs[0], tw.inputs[0]); tw.inputs[1].default_value = 0.03
    nt.links.new(tw.outputs[0], nz.inputs["W"])
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    nr = node(nt, "ShaderNodeMapRange", (-500, -100), **{"From Min": 0.3, "From Max": 0.7, "To Min": 0.55, "To Max": 1.45})
    nt.links.new(nz.outputs["Fac"], nr.inputs["Value"])
    # homogeneous density: Cycles samples it analytically instead of ray-marching
    dm = node(nt, "ShaderNodeMath", (-300, 100), operation="MULTIPLY")
    nt.links.new(dens.outputs[0], dm.inputs[0]); dm.inputs[1].default_value = 1.0
    pv = node(nt, "ShaderNodeVolumePrincipled", (0, 0))
    pv.inputs["Color"].default_value = (0.9, 0.93, 1.0, 1)
    pv.inputs["Anisotropy"].default_value = 0.55
    nt.links.new(dm.outputs[0], pv.inputs["Density"])
    nt.links.new(pv.outputs[0], nt.nodes["Material Output"].inputs["Volume"])
    haze.data.materials.append(hm)
    haze["part"] = "haze"

    # ---------------------------------------------------------------- lights
    moonc = srgb("#CFE0FF")
    sp = bpy.data.lights.new("spot", "SPOT")
    sp.energy = 9000.0; sp.color = moonc
    sp.spot_size = math.radians(33); sp.spot_blend = 0.10
    sp.shadow_soft_size = 0.05
    if hasattr(sp, "volume_factor"):
        sp.volume_factor = 1.0
    spo = bpy.data.objects.new("spot", sp); coll.objects.link(spo)
    spo.location = (0.0, -0.6, 10.5)
    spo.rotation_euler = (Vector((0.0, 0.0, 0.9)) - spo.location).to_track_quat("-Z", "Y").to_euler()

    mn = bpy.data.lights.new("moonlight", "SUN")
    mn.energy = 0.25; mn.color = moonc; mn.angle = math.radians(0.6)
    mno = bpy.data.objects.new("moonlight", mn); coll.objects.link(mno)
    mno.rotation_euler = (-MOON_DIR).to_track_quat("-Z", "Y").to_euler()

    lt = bpy.data.lights.new("lightning", "SUN")
    lt.energy = 0.0; lt.color = (0.88, 0.92, 1.0); lt.angle = math.radians(0.35)
    lto = bpy.data.objects.new("lightning", lt); coll.objects.link(lto)
    lto.rotation_euler = (Vector((0.15, -1.0, -0.55))).to_track_quat("-Z", "Y").to_euler()

    return {"curtains": curtains, "bolts": bolts, "spot": spo, "moon": mno, "lightning": lto, "haze": haze}
