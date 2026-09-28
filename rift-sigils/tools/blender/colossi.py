# Blender generator for the hero colossi of Печати Разлома (Blender 5.1).
# Run it inside Blender, for example through the Blender Lab MCP add-on:
#   import sys; sys.path.insert(0, '<repo>/rift-sigils/tools/blender'); import colossi; colossi.build('RS-C001', '<repo>/rift-sigils/assets/colossi')
# Each build gets its own scene: joints are empties (rest rotation = identity), every armour piece is a mesh object
# named p_* parented to a joint, so the game can fly the pieces in and out. Clips `idle` and `attack` animate the joints.
# Modelled in game units: Z up, facing -Y (the glTF exporter turns that into +Y up, facing +Z), origin between the feet.
import math
import re

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

V = Vector
TAU = math.tau
FPS = 24


def lin(h):
    def c(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return (c((h >> 16) & 255), c((h >> 8) & 255), c(h & 255), 1.0)


def material(name, color, metallic=0.0, roughness=0.5, emission=None, strength=0.0, double=False):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:  # node trees are always on in newer versions
        pass
    bsdf = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = lin(color)
    bsdf.inputs['Metallic'].default_value = metallic
    bsdf.inputs['Roughness'].default_value = roughness
    if emission is not None:
        bsdf.inputs['Emission Color'].default_value = lin(emission)
        bsdf.inputs['Emission Strength'].default_value = strength
    m.use_backface_culling = not double
    m.diffuse_color = lin(color)
    m.metallic = metallic
    m.roughness = roughness
    return m


class Mats:
    def __init__(self, prefix, spec):
        for k, v in spec.items():
            setattr(self, k, material(f'{prefix} {k}', **v))


# ---------------------------------------------------------------- curves

def catmull(ctrl, u):
    """Uniform Catmull-Rom through ctrl, u in [0, len-1]."""
    n = len(ctrl)
    u = max(0.0, min(n - 1.0, u))
    i = min(int(u), n - 2)
    t = u - i
    p1, p2 = ctrl[i], ctrl[i + 1]
    p0 = ctrl[i - 1] if i > 0 else p1 + (p1 - p2)
    p3 = ctrl[i + 2] if i + 2 < n else p2 + (p2 - p1)
    t2, t3 = t * t, t * t * t
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)


def lerp(a, b, t):
    return a + (b - a) * t


class Path:
    """A tube centre line with elliptical radii (rx along the hint side, ry across)."""

    def __init__(self, ctrl, radii, hint=(1, 0, 0)):
        self.ctrl = [V(c) for c in ctrl]
        self.radii = [r if isinstance(r, (tuple, list)) else (r, r) for r in radii]
        self.hint = V(hint)
        self.n = len(self.ctrl)

    def point(self, u):
        return catmull(self.ctrl, u)

    def tangent(self, u):
        e = 0.01
        d = self.point(min(self.n - 1, u + e)) - self.point(max(0, u - e))
        return d.normalized()

    def radius(self, u):
        u = max(0.0, min(self.n - 1.0, u))
        i = min(int(u), self.n - 2)
        t = u - i
        a, b = self.radii[i], self.radii[i + 1]
        return lerp(a[0], b[0], t), lerp(a[1], b[1], t)

    def frame(self, u):
        t = self.tangent(u)
        h = self.hint
        x = h - t * h.dot(t)
        if x.length < 1e-4:
            x = V((0, 0, 1)) - t * t.z
        x.normalize()
        y = t.cross(x)
        return t, x, y

    def surf(self, u, ang, off=0.0):
        p = self.point(u)
        t, x, y = self.frame(u)
        rx, ry = self.radius(u)
        pos = p + x * ((rx + off) * math.cos(ang)) + y * ((ry + off) * math.sin(ang))
        nrm = (x * (math.cos(ang) / max(rx, 1e-3)) + y * (math.sin(ang) / max(ry, 1e-3))).normalized()
        return pos, nrm, t

    def surf_dir(self, u, d, off=0.0):
        t, x, y = self.frame(u)
        d = V(d)
        return self.surf(u, math.atan2(d.dot(y), d.dot(x)), off)


# ---------------------------------------------------------------- rig and parts

class Rig:
    def __init__(self, cid):
        self.cid = cid
        old = bpy.data.scenes.get(cid)
        if old:
            for o in list(old.objects):
                bpy.data.objects.remove(o, do_unlink=True)
            bpy.data.scenes.remove(old)
        for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.actions):
            for x in list(coll):
                if x.users == 0:
                    coll.remove(x)
        self.scene = bpy.data.scenes.new(cid)
        self.scene.render.fps = FPS
        self.jw = {}
        self.joints = {}
        self.root = bpy.data.objects.new(cid, None)
        self.scene.collection.objects.link(self.root)
        self.parts = []

    def joint(self, name, at, parent=None):
        e = bpy.data.objects.new(name, None)
        e.empty_display_type = 'PLAIN_AXES'
        e.empty_display_size = 0.35
        self.scene.collection.objects.link(e)
        at = V(at)
        e.parent = self.joints[parent] if parent else self.root
        e.location = at - (self.jw[parent] if parent else V())
        e.rotation_mode = 'XYZ'
        self.jw[name] = at
        self.joints[name] = e
        return e

    def part(self, name, joint):
        p = Part(self, name, joint)
        self.parts.append(p)
        return p

    def finish(self):
        objs = [p.finish() for p in self.parts]
        return [o for o in objs if o]


class Part:
    def __init__(self, rig, name, joint):
        self.rig, self.name, self.joint = rig, name, joint
        self.bm = bmesh.new()
        self.mats = []

    def mi(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def transform(self, m):
        bmesh.ops.transform(self.bm, matrix=m, verts=self.bm.verts)

    def finish(self):
        bm = self.bm
        if not bm.verts:
            bm.free()
            return None
        lo = V((min(v.co.x for v in bm.verts), min(v.co.y for v in bm.verts), min(v.co.z for v in bm.verts)))
        hi = V((max(v.co.x for v in bm.verts), max(v.co.y for v in bm.verts), max(v.co.z for v in bm.verts)))
        c = (lo + hi) / 2
        for v in bm.verts:
            v.co -= c
        me = bpy.data.meshes.new(f'm_{self.name}')
        bm.to_mesh(me)
        bm.free()
        for m in self.mats:
            me.materials.append(m)
        ob = bpy.data.objects.new(f'p_{self.name}', me)
        self.rig.scene.collection.objects.link(ob)
        ob.parent = self.rig.joints[self.joint]
        ob.location = c - self.rig.jw[self.joint]
        return ob


# ---------------------------------------------------------------- geometry

def _faces(pt, mat, faces, smooth=False):
    mi = pt.mi(mat)
    for f in faces:
        f.material_index = mi
        f.smooth = smooth
    return faces


def loft(pt, mat, secs, cap=True, smooth=False, closed=False, recalc=True):
    bm = pt.bm
    rings = [[bm.verts.new(s)] if isinstance(s, Vector) else [bm.verts.new(q) for q in s] for s in secs]
    faces = []
    pairs = list(zip(rings, rings[1:]))
    if closed:
        pairs.append((rings[-1], rings[0]))
    for a, b in pairs:
        if len(a) == 1 and len(b) == 1:
            continue
        if len(a) == 1:
            for k in range(len(b)):
                faces.append(bm.faces.new((a[0], b[k], b[(k + 1) % len(b)])))
        elif len(b) == 1:
            for k in range(len(a)):
                faces.append(bm.faces.new((a[k], a[(k + 1) % len(a)], b[0])))
        else:
            n = len(a)
            for k in range(n):
                faces.append(bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k])))
    if cap and not closed:
        if len(rings[0]) > 2:
            faces.append(bm.faces.new(rings[0]))
        if len(rings[-1]) > 2:
            faces.append(bm.faces.new(list(reversed(rings[-1]))))
    _faces(pt, mat, faces, smooth)
    if recalc:
        bmesh.ops.recalc_face_normals(bm, faces=faces)
    return faces


def tube(pt, mat, path, u0=None, u1=None, rings=10, sides=8, roll=0.0, smooth=False, off=0.0, cap=True):
    if not isinstance(path, Path):
        raise TypeError('tube needs a Path')
    u0 = 0.0 if u0 is None else u0
    u1 = path.n - 1.0 if u1 is None else u1
    secs = []
    for i in range(rings):
        u = lerp(u0, u1, i / (rings - 1))
        p = path.point(u)
        t, x, y = path.frame(u)
        rx, ry = path.radius(u)
        rx, ry = rx + off, ry + off
        if max(rx, ry) < 1e-3:
            secs.append(p)
            continue
        secs.append([p + x * (rx * math.cos(roll + TAU * k / sides)) + y * (ry * math.sin(roll + TAU * k / sides)) for k in range(sides)])
    return loft(pt, mat, secs, cap=cap, smooth=smooth)


def line(pt, mat, pts, r, sides=5, rings=None, taper=None, hint=(0, 0, 1), roll=0.0):
    """A thin tube through points: glow seams, fingers, trims."""
    pts = [V(p) for p in pts]
    radii = taper if taper else [r] * len(pts)
    path = Path(pts, radii, hint)
    return tube(pt, mat, path, rings=rings or max(2, len(pts) * 2), sides=sides, roll=roll)


def ring_loop(pt, mat, pts, r, sides=5):
    """A closed thin tube through a loop of points."""
    pts = [V(p) for p in pts]
    n = len(pts)
    secs = []
    for i in range(n):
        p = pts[i]
        t = (pts[(i + 1) % n] - pts[i - 1]).normalized()
        c = sum(pts, V()) / n
        x = (p - c) - t * (p - c).dot(t)
        x.normalize()
        y = t.cross(x)
        secs.append([p + x * (r * math.cos(TAU * k / sides)) + y * (r * math.sin(TAU * k / sides)) for k in range(sides)])
    return loft(pt, mat, secs, closed=True)


def spike(pt, mat, base, tip, r, sides=4, bend=(0, 0, 0), roll=0.785, rings=5):
    base, tip = V(base), V(tip)
    d = (tip - base).normalized()
    hint = V((0, 0, 1)) if abs(d.z) < 0.8 else V((1, 0, 0))
    mid = (base + tip) / 2 + V(bend)
    path = Path([base, mid, tip], [r, r * 0.55, 0.0], hint)
    return tube(pt, mat, path, rings=rings, sides=sides, roll=roll)


SHAPES = {
    'hex': None,
    'kite': [(0, -0.5), (0.5, 0.12), (0.3, 0.5), (-0.3, 0.5), (-0.5, 0.12)],
    'shield': [(0, -0.5), (0.5, -0.12), (0.5, 0.5), (-0.5, 0.5), (-0.5, -0.12)],
    'scale': [(0, -0.5), (0.42, -0.2), (0.5, 0.22), (0.3, 0.5), (-0.3, 0.5), (-0.5, 0.22), (-0.42, -0.2)],
    'diamond': [(0, -0.5), (0.5, 0), (0, 0.5), (-0.5, 0)],
    'fin': [(-0.5, -0.5), (0.5, -0.5), (0.3, 0.1), (-0.35, 0.5), (-0.45, 0.0)],
}


def plate(pt, mat, c, n, up, w, h, t=0.14, shape='hex', taper=0.28, bend=0.0, bendv=0.0, bev=None, edge=None):
    """An armour plate: outline extruded along n with a faceted chamfer (optionally in another material)."""
    c, n = V(c), V(n).normalized()
    up = V(up)
    u = (up - n * up.dot(n)).normalized()
    r = u.cross(n)
    if shape == 'hex' or shape is None:
        k = min(w, h) * taper
        o = [(-w / 2 + k, -h / 2), (w / 2 - k, -h / 2), (w / 2, -h / 2 + k), (w / 2, h / 2 - k),
             (w / 2 - k, h / 2), (-w / 2 + k, h / 2), (-w / 2, h / 2 - k), (-w / 2, -h / 2 + k)]
    else:
        o = [(x * w, y * h) for x, y in (SHAPES[shape] if isinstance(shape, str) else shape)]
    b = bev if bev is not None else min(w, h) * 0.13
    sx, sy = max(0.05, (w / 2 - b) / (w / 2)), max(0.05, (h / 2 - b) / (h / 2))

    def P(x, y, z):
        zz = z - bend * (w / 2) * (2 * x / w) ** 2 - bendv * (h / 2) * (2 * y / h) ** 2
        return c + r * x + u * y + n * zz

    bm = pt.bm
    r0 = [bm.verts.new(P(x, y, 0)) for x, y in o]
    r1 = [bm.verts.new(P(x, y, t * 0.45)) for x, y in o]
    r2 = [bm.verts.new(P(x * sx, y * sy, t)) for x, y in o]
    m = len(o)
    body = [bm.faces.new(list(reversed(r0)))]
    body += [bm.faces.new((r0[i], r0[(i + 1) % m], r1[(i + 1) % m], r1[i])) for i in range(m)]
    cham = [bm.faces.new((r1[i], r1[(i + 1) % m], r2[(i + 1) % m], r2[i])) for i in range(m)]
    top = [bm.faces.new(r2)]
    _faces(pt, mat, body + top)
    _faces(pt, edge or mat, cham + body[1:] if edge else cham)
    bmesh.ops.recalc_face_normals(bm, faces=body + cham + top)
    return c + n * t


def gem(pt, mat, c, r, scale=(1, 1, 1), rot=(0, 0, 0), subdiv=1):
    ret = bmesh.ops.create_icosphere(pt.bm, subdivisions=subdiv, radius=r, matrix=Matrix.LocRotScale(V(c), Euler(rot), V(scale)))
    faces = list({f for v in ret['verts'] for f in v.link_faces})
    _faces(pt, mat, faces)
    return faces


def sheet(pt, rows, mat_of=None, mat=None):
    """An open quad grid (double-sided materials). mat_of(i, j) picks a material per quad."""
    bm = pt.bm
    vs = [[bm.verts.new(p) for p in row] for row in rows]
    faces = []
    for i in range(len(rows) - 1):
        for j in range(len(rows[0]) - 1):
            f = bm.faces.new((vs[i][j], vs[i][j + 1], vs[i + 1][j + 1], vs[i + 1][j]))
            f.material_index = pt.mi(mat_of(i, j) if mat_of else mat)
            f.smooth = False
            faces.append(f)
    return faces


def shell(pt, rows, thick, out_hint, mat_out, mat_in, mat_edge=None):
    """A thick cloth panel: the outer grid, the same grid pushed inward, and the rim between them."""
    nr, nc = len(rows), len(rows[0])
    outer = [[V(p) for p in row] for row in rows]
    inner = []
    for i in range(nr):
        row = []
        for j in range(nc):
            a = outer[min(i + 1, nr - 1)][j] - outer[max(i - 1, 0)][j]
            b = outer[i][min(j + 1, nc - 1)] - outer[i][max(j - 1, 0)]
            nrm = a.cross(b).normalized()
            if nrm.dot(V(out_hint)) < 0:
                nrm = -nrm
            row.append(outer[i][j] - nrm * thick)
        inner.append(row)
    bm = pt.bm
    vo = [[bm.verts.new(p) for p in row] for row in outer]
    vi = [[bm.verts.new(p) for p in row] for row in inner]
    fo, fi, fe = [], [], []
    for i in range(nr - 1):
        for j in range(nc - 1):
            fo.append(bm.faces.new((vo[i][j], vo[i][j + 1], vo[i + 1][j + 1], vo[i + 1][j])))
            fi.append(bm.faces.new((vi[i + 1][j], vi[i + 1][j + 1], vi[i][j + 1], vi[i][j])))
    rim = [(0, j) for j in range(nc)] + [(i, nc - 1) for i in range(1, nr)] + [(nr - 1, j) for j in range(nc - 2, -1, -1)] + [(i, 0) for i in range(nr - 2, 0, -1)]
    for k in range(len(rim)):
        (i0, j0), (i1, j1) = rim[k], rim[(k + 1) % len(rim)]
        fe.append(bm.faces.new((vo[i0][j0], vo[i1][j1], vi[i1][j1], vi[i0][j0])))
    _faces(pt, mat_out, fo)
    _faces(pt, mat_in, fi)
    _faces(pt, mat_edge or mat_out, fe)
    bmesh.ops.recalc_face_normals(bm, faces=fo + fi + fe)
    # the recalculation may flip the whole shell: make sure the outer grid faces out
    if fo[len(fo) // 2].normal.dot(V(out_hint)) < 0:
        bmesh.ops.reverse_faces(bm, faces=fo + fi + fe)
    return fo


def rot_about(pivot, axis, ang):
    pivot = V(pivot)
    return Matrix.Translation(pivot) @ Matrix.Rotation(ang, 4, axis) @ Matrix.Translation(-pivot)


# ---------------------------------------------------------------- animation

def bake_clip(rig, name, frames, fn):
    """fn(joint, frame) -> {'rot': (x, y, z), 'loc': (dx, dy, dz), 'scale': s} or None. One NLA track per clip."""
    for jn, ob in rig.joints.items():
        keys = [(f, fn(jn, f)) for f in frames]
        if all(k is None for _, k in keys):
            continue
        base = ob.location.copy()
        ob.animation_data_create()
        ob.animation_data.action = None
        for f, k in keys:
            k = k or {}
            ob.rotation_euler = k.get('rot', (0, 0, 0))
            ob.location = base + V(k.get('loc', (0, 0, 0)))
            s = k.get('scale', 1.0)
            ob.scale = (s, s, s)
            for dp in ('rotation_euler', 'location', 'scale'):
                ob.keyframe_insert(dp, frame=f)
        act = ob.animation_data.action
        act.name = f'{name}.{jn}'
        act.use_fake_user = False
        track = ob.animation_data.nla_tracks.new()
        track.name = name
        track.strips.new(name, int(frames[0]), act)
        ob.animation_data.action = None
        ob.location, ob.rotation_euler, ob.scale = base, (0, 0, 0), (1, 1, 1)


def loop_frames(seconds, step=3):
    n = int(seconds * FPS)
    return [1 + i for i in range(0, n + 1, step)] + ([1 + n] if n % step else [])


# ---------------------------------------------------------------- RS-C001 «Пепельный виверн»

def wyvern(rig):
    M = Mats('C001', {
        'Armor': dict(color=0xd02a1e, metallic=0.35, roughness=0.26),
        'ArmorDeep': dict(color=0x7e1512, metallic=0.4, roughness=0.3),
        'Gold': dict(color=0xf2c14e, metallic=0.9, roughness=0.22),
        'Bone': dict(color=0xfff0cf, metallic=0.05, roughness=0.32),
        'Under': dict(color=0x1c1417, metallic=0.5, roughness=0.3),
        'Membrane': dict(color=0x8e1712, metallic=0.1, roughness=0.45, double=True),
        'MembraneHot': dict(color=0xe8521c, metallic=0.1, roughness=0.4, double=True),
        'Glow': dict(color=0xff5a26, emission=0xff5a26, strength=4.0),
        'GlowCore': dict(color=0xff8a2a, emission=0xff8a2a, strength=6.0),
    })
    J = rig.joint
    J('pelvis', (0, 0.9, 3.5))
    J('torso', (0, -0.1, 6.2), 'pelvis')
    J('neck1', (0, -0.5, 7.5), 'torso')
    J('neck2', (0, -1.55, 9.0), 'neck1')
    HS, HC, JAW = 1.15, V((0, -2.7, 9.8)), V((0, -3.0, 9.5))
    J('head', HC, 'neck2')
    J('jaw', HC + (JAW - HC) * HS, 'head')
    J('tail1', (0, 1.5, 2.9), 'pelvis')
    J('tail2', (0.15, 3.6, 1.15), 'tail1')
    J('tail3', (1.4, 5.8, 0.36), 'tail2')
    for s, sd in ((1, 'L'), (-1, 'R')):
        J(f'leg_{sd}', (s * 1.05, 0.7, 3.4))
        J(f'wing_{sd}', (s * 1.2, 0.3, 7.25), 'torso')
        J(f'elbow_{sd}', (s * 2.9, 1.05, 8.8), f'wing_{sd}')
        J(f'wrist_{sd}', (s * 4.4, 1.75, 10.7), f'elbow_{sd}')
    P = rig.part
    FRONT, BACK = -math.pi / 2, math.pi / 2

    # ---- torso: black under-armour, red back plates with gold spikes, cream belly scutes with glowing seams
    T = Path([(0, 1.55, 2.6), (0, 1.0, 3.5), (0, 0.45, 4.6), (0, 0.0, 5.6), (0, -0.3, 6.5), (0, -0.45, 7.3), (0, -0.55, 7.9)],
             [(0.9, 0.85), (1.25, 1.15), (1.4, 1.25), (1.45, 1.3), (1.35, 1.2), (1.0, 0.92), (0.75, 0.7)])
    tube(P('belly', 'pelvis'), M.Under, T, 0, 3.3, rings=9, sides=10)
    tube(P('chest_core', 'torso'), M.Under, T, 3.1, 6, rings=7, sides=10)
    for k, (lo, hi, jn) in enumerate(((0.3, 2.7, 'pelvis'), (3.05, 5.2, 'torso'))):
        pt = P(f'back{k}', jn)
        for i in range(4):
            u = lerp(lo, hi, i / 3)
            rx, ry = T.radius(u)
            pos, nrm, tan = T.surf(u, BACK, -0.1)
            top = plate(pt, M.Armor, pos, nrm, tan, rx * 2.3, 1.2, t=0.28, shape='scale', bend=0.8, edge=M.ArmorDeep)
            if i % 2 == 0 or k:
                spike(pt, M.Gold, top - nrm * 0.05, top + nrm * (0.95 - k * 0.1 - i * 0.05) + tan * 0.75, 0.2, bend=nrm * 0.12)
    for s, sd in ((1, 'L'), (-1, 'R')):
        for k, (us, jn) in enumerate((((0.55, 1.25, 1.95, 2.6), 'pelvis'), ((3.2, 3.95, 4.7), 'torso'))):
            pt = P(f'flank{k}_{sd}', jn)
            for u in us:
                rx, _ = T.radius(u)
                pos, nrm, tan = T.surf(u, (0.1 if s > 0 else math.pi - 0.1), -0.08)
                plate(pt, M.Armor, pos, nrm, tan, rx * 1.15, 0.95, t=0.22, shape='scale', bend=0.55, edge=M.Gold if u in (1.25, 3.95) else M.ArmorDeep)
    pt = P('scutes', 'pelvis')
    for i, u in enumerate((0.35, 0.8, 1.25, 1.7, 2.15, 2.6)):
        rx, _ = T.radius(u)
        pos, nrm, tan = T.surf(u, FRONT, -0.05)
        plate(pt, M.Bone, pos, nrm, tan, rx * 1.65, 0.54, t=0.16, taper=0.3, bend=0.6, edge=M.Gold)
        if i:
            um = u - 0.225
            line(pt, M.Glow, [T.surf(um, FRONT + a, 0.02)[0] for a in (-0.75, -0.4, 0, 0.4, 0.75)], 0.045, sides=4)
    # chest: red plate, gold hex frame, the glowing core (the HUD anchors the G card here)
    pt = P('chest_plate', 'torso')
    u = 3.55
    pos, nrm, tan = T.surf(u, FRONT, -0.1)
    top = plate(pt, M.Armor, pos, nrm, tan, 2.1, 1.75, t=0.28, bend=0.45, edge=M.Gold)
    side = tan.cross(nrm).normalized()
    core = top + nrm * 0.12
    gem(pt, M.GlowCore, core, 0.36, scale=(1.25, 0.8, 1.45), subdiv=1)
    ring_loop(pt, M.Gold, [core + side * (0.55 * math.cos(a)) + tan * (0.66 * math.sin(a)) - nrm * 0.02 for a in [TAU * i / 6 + TAU / 12 for i in range(6)]], 0.09, sides=5)
    for sx in (-1, 1):
        for sy in (-1, 1):
            a = core + side * (0.5 * sx) + tan * (0.45 * sy)
            b = core + side * (0.95 * sx) + tan * (0.8 * sy) - nrm * 0.12
            line(pt, M.Glow, [a, b], 0.04, sides=4)
    J('chest', core, 'torso')
    pt = P('pecs', 'torso')
    for s in (1, -1):
        pos, nrm, tan = T.surf(4.35, FRONT + s * 0.62, -0.05)
        plate(pt, M.Armor, pos, nrm, tan, 1.05, 0.95, t=0.2, shape='kite', bend=0.3, edge=M.Gold)

    # ---- neck
    N = Path([(0, -0.45, 7.1), (0, -0.8, 8.2), (0, -1.55, 9.0), (0, -2.3, 9.5), (0, -2.85, 9.75)], [0.85, 0.72, 0.62, 0.55, 0.5])
    tube(P('neck_lo', 'neck1'), M.Under, N, 0, 2.15, rings=8, sides=8)
    tube(P('neck_hi', 'neck2'), M.Under, N, 1.95, 4, rings=7, sides=8)
    for k, (us, jn) in enumerate((((0.3, 0.95, 1.6), 'neck1'), ((2.2, 2.85, 3.45), 'neck2'))):
        pt = P(f'neck_plates{k}', jn)
        for i, u in enumerate(us):
            rx, _ = N.radius(u)
            pos, nrm, tan = N.surf(u, BACK, -0.08)
            top = plate(pt, M.Armor, pos, nrm, tan, rx * 2.5, 0.9, t=0.22, shape='scale', bend=0.8, edge=M.ArmorDeep)
            for sa in (0.25, math.pi - 0.25):
                p2, n2, t2 = N.surf(u + 0.3, sa, -0.06)
                plate(pt, M.Armor, p2, n2, t2, rx * 1.1, 0.7, t=0.16, shape='scale', bend=0.5, edge=M.Gold)
            sz = 0.75 - (k * 3 + i) * 0.07
            spike(pt, M.Gold, top - nrm * 0.04, top + nrm * sz + tan * sz * 0.8, 0.14)
            pos, nrm, tan = N.surf(u + 0.25, FRONT, -0.03)
            plate(pt, M.Bone, pos, nrm, tan, rx * 1.3, 0.48, t=0.12, bend=0.5, edge=M.Gold)
            if i:
                line(pt, M.Glow, [N.surf(u, FRONT + a, 0.02)[0] for a in (-0.6, 0, 0.6)], 0.035, sides=4)

    # ---- head: faceted skull, open jaw with a fire-lit throat, cream horns, gold brows
    def hsec(y, w, zt, zb):
        h = zt - zb
        return [V((x, y, z)) for x, z in ((0.75 * w, zb), (w, zb + 0.35 * h), (0.85 * w, zb + 0.72 * h), (0.38 * w, zt),
                                            (-0.38 * w, zt), (-0.85 * w, zb + 0.72 * h), (-w, zb + 0.35 * h), (-0.75 * w, zb))]
    pt = P('skull', 'head')
    loft(pt, M.Armor, [hsec(-2.45, 0.55, 10.2, 9.55), hsec(-2.95, 0.74, 10.42, 9.48), hsec(-3.5, 0.7, 10.32, 9.48),
                       hsec(-4.1, 0.54, 10.08, 9.5), hsec(-4.7, 0.43, 9.92, 9.5), hsec(-5.2, 0.3, 9.8, 9.52), V((0, -5.5, 9.63))])
    plate(pt, M.Gold, (0, -4.3, 9.98), (0, -0.2, 1), (0, -1, 0.2), 0.42, 1.6, t=0.08, shape='kite')
    spike(pt, M.Gold, (0, -4.85, 9.9), (0, -5.05, 10.35), 0.1, sides=4)
    widths = [(-3.5, 0.7), (-4.1, 0.54), (-4.7, 0.43), (-5.2, 0.3)]

    def width_at(y):
        for (y0, w0), (y1, w1) in zip(widths, widths[1:]):
            if y1 <= y <= y0:
                return lerp(w0, w1, (y - y0) / (y1 - y0))
        return widths[-1][1]
    for s in (1, -1):
        plate(pt, M.Gold, (s * 0.46, -3.45, 10.28), (s * 0.55, -0.45, 0.7), (0, -1, 0.15), 0.5, 0.95, t=0.12, shape='kite')
        plate(pt, M.GlowCore, (s * 0.64, -3.78, 10.02), (s, -0.35, 0.25), (0, -1, 0.3), 0.14, 0.46, t=0.05, shape='kite')
        plate(pt, M.Armor, (s * 0.7, -3.15, 9.72), (s, 0.05, 0.1), (0, -1, 0.35), 0.62, 0.95, t=0.1, shape='shield', edge=M.Gold)
        for i in range(5):
            y = -3.4 - i * 0.4
            x = s * width_at(y) * 0.7
            spike(pt, M.Bone, (x, y, 9.54), (x * 0.97, y - 0.05, 9.15 - (0.12 if i == 3 else 0)), 0.075, sides=3, rings=3)
    pt = P('horns', 'head')
    for s in (1, -1):
        tube(pt, M.Bone, Path([(s * 0.4, -2.8, 10.2), (s * 0.62, -2.2, 10.62), (s * 0.85, -1.45, 10.98), (s * 0.98, -0.7, 11.55), (s * 0.92, -0.25, 12.05)],
                              [0.25, 0.2, 0.15, 0.08, 0.0], (1, 0, 0)), rings=10, sides=6)
        tube(pt, M.Gold, Path([(s * 0.6, -3.0, 9.95), (s * 1.05, -2.55, 9.95), (s * 1.38, -2.05, 10.28)], [0.14, 0.08, 0.0], (0, 0, 1)), rings=5, sides=5)
    for i in range(3):
        b = V((0, -3.25 + i * 0.36, 10.4 - i * 0.07))
        spike(pt, M.Gold, b, b + V((0, 0.45, 0.4)) * (1 - i * 0.2), 0.1, sides=4)
    pt = P('jaw', 'jaw')
    loft(pt, M.Under, [hsec(-2.85, 0.52, 9.5, 9.08), hsec(-3.6, 0.47, 9.48, 9.12), hsec(-4.4, 0.36, 9.46, 9.22), hsec(-5.05, 0.24, 9.45, 9.3), V((0, -5.3, 9.4))])
    for s in (1, -1):
        plate(pt, M.Armor, (s * 0.46, -3.8, 9.27), (s, 0, -0.2), (0, -1, 0.1), 0.35, 1.5, t=0.08, shape='kite', edge=M.Gold)
        for i in range(4):
            y = -3.55 - i * 0.42
            x = s * width_at(y) * 0.62
            spike(pt, M.Bone, (x, y, 9.45), (x, y - 0.04, 9.72), 0.065, sides=3, rings=3)
    gem(pt, M.GlowCore, (0, -3.45, 9.46), 0.3, scale=(0.9, 1.6, 0.25), subdiv=1)
    pt.transform(rot_about(JAW, 'X', 0.3))
    grow = Matrix.Translation(HC) @ Matrix.Scale(HS, 4) @ Matrix.Translation(-HC)
    for p in rig.parts[-3:]:
        p.transform(grow)

    # ---- legs: digitigrade, red thigh plates, cream claws
    for s, sd in ((1, 'L'), (-1, 'R')):
        jn = f'leg_{sd}'
        TH = Path([(s * 1.0, 0.75, 3.6), (s * 1.25, 0.15, 2.85), (s * 1.38, -0.45, 2.2)], [0.82, 0.7, 0.48])
        pt = P(f'thigh_{sd}', jn)
        tube(pt, M.Under, TH, rings=6, sides=8)
        pos, nrm, tan = TH.surf_dir(0.8, (s, 0.1, 0.15), -0.1)
        top = plate(pt, M.Armor, pos, nrm, tan, 1.35, 1.8, t=0.26, shape='shield', bend=0.55, edge=M.Gold)
        spike(pt, M.Gold, top - nrm * 0.05, top + nrm * 0.55 + V((0, 0.55, 0.35)), 0.16)
        pos, nrm, tan = TH.surf_dir(0.9, (0, 1, 0.1), -0.08)
        plate(pt, M.Armor, pos, nrm, tan, 1.2, 1.5, t=0.22, shape='scale', bend=0.6, edge=M.ArmorDeep)
        pos, nrm, tan = TH.surf_dir(0.8, (-s, -0.1, 0.1), -0.08)
        plate(pt, M.ArmorDeep, pos, nrm, tan, 0.9, 1.3, t=0.16, shape='scale', bend=0.5)
        SH = Path([(s * 1.38, -0.45, 2.2), (s * 1.36, 0.1, 1.55), (s * 1.32, 0.55, 0.95)], [0.44, 0.38, 0.32])
        pt = P(f'shin_{sd}', jn)
        tube(pt, M.Armor, SH, rings=5, sides=6)
        pos, nrm, tan = TH.surf_dir(2.0, (0, -1, 0.2), -0.06)
        plate(pt, M.Gold, pos, nrm, V((0, 0, 1)), 0.7, 0.85, t=0.14, shape='kite')
        spike(pt, M.Bone, pos + nrm * 0.1, pos + nrm * 0.55 + V((0, 0, 0.25)), 0.11)
        for i in range(2):
            pos, nrm, tan = SH.surf_dir(0.6 + i * 0.8, (0, 1, 0))
            spike(pt, M.Gold, pos - nrm * 0.05, pos + nrm * 0.45 - tan * 0.2, 0.1)
        MT = Path([(s * 1.32, 0.55, 0.95), (s * 1.31, 0.2, 0.55), (s * 1.3, -0.12, 0.25)], [0.3, 0.27, 0.26])
        pt = P(f'foot_{sd}', jn)
        tube(pt, M.Under, MT, rings=4, sides=6)
        pos, nrm, tan = MT.surf_dir(1.0, (0, -1, 0))
        plate(pt, M.Armor, pos, nrm, V((0, 0, 1)), 0.5, 0.75, t=0.12, shape='kite', edge=M.Gold)
        for d in (-0.3, 0.0, 0.3):
            TO = Path([(s * 1.3 + d * 0.5, -0.1, 0.22), (s * 1.3 + d * 1.3, -0.65, 0.2), (s * 1.3 + d * 1.8, -1.05, 0.16)], [0.17, 0.14, 0.11])
            tube(pt, M.Under, TO, rings=4, sides=5)
            pos, nrm, tan = TO.surf_dir(1.0, (0, 0, 1))
            plate(pt, M.Armor, pos, nrm, V((0, -1, 0)), 0.3, 0.5, t=0.08, shape='kite')
            tip = TO.point(2)
            spike(pt, M.Bone, tip + V((0, 0.05, 0)), tip + V((d * 0.3, -0.55, -0.14)), 0.1, bend=(0, 0, 0.05))
        spike(pt, M.Bone, (s * 1.32, 0.6, 0.9), (s * 1.35, 1.1, 0.5), 0.1)

    # ---- tail: segments on three joints, red plates, a gold-edged flame blade at the tip
    TL = Path([(0, 1.45, 3.1), (0, 2.4, 2.0), (0.15, 3.6, 1.15), (0.6, 4.8, 0.55), (1.4, 5.8, 0.36), (2.5, 6.4, 0.34), (3.6, 6.5, 0.46), (4.4, 6.2, 0.6)],
              [0.95, 0.8, 0.62, 0.48, 0.36, 0.26, 0.16, 0.05], (0, 0, 1))
    for k, (u0, u1, jn) in enumerate(((0, 2.1, 'tail1'), (1.95, 4.1, 'tail2'), (3.95, 7, 'tail3'))):
        pt = P(f'tail{k}', jn)
        tube(pt, M.Under, TL, u0, u1, rings=7, sides=8)
        u, i = u0 + 0.3, 0
        while u < min(u1, 6.3):
            rx, _ = TL.radius(u)
            pos, nrm, tan = TL.surf(u, 0, -0.08)
            top = plate(pt, M.Armor, pos, nrm, tan, rx * 2.5, 0.6 + rx * 0.55, t=0.2, shape='scale', bend=0.8, edge=M.ArmorDeep)
            if i % 2 == 0:
                spike(pt, M.Gold, top - nrm * 0.04, top + nrm * (0.25 + rx * 0.6) + tan * (0.2 + rx * 0.5), 0.07 + rx * 0.12)
            u, i = u + 0.45, i + 1
    pt = P('tail_blade', 'tail3')
    tip, tan = TL.point(6.6), TL.tangent(6.6)
    for a in (-0.55, 0, 0.55):
        d = (tan + V((0, 0, 1)).cross(tan) * a).normalized()
        c = tip + d * 0.75
        plate(pt, M.Armor, c, V((0, 0, 1)), d, 0.55 if a else 0.75, 1.5 if a else 1.9, t=0.1, shape='kite', edge=M.Gold)
    line(pt, M.Glow, [tip + tan * 0.2 + V((0, 0, 0.12)), tip + tan * 1.4 + V((0, 0, 0.1))], 0.045, sides=4)

    # ---- wings: armoured arm, gold fingers with glowing seams, faceted membranes that heat up toward the edge
    for s, sd in ((1, 'L'), (-1, 'R')):
        sh, el, wr = rig.jw[f'wing_{sd}'], rig.jw[f'elbow_{sd}'], rig.jw[f'wrist_{sd}']
        pt = P(f'arm_{sd}', f'wing_{sd}')
        tube(pt, M.Armor, Path([sh - V((s * 0.15, 0, 0.1)), (sh + el) / 2 + V((0, 0, 0.1)), el], [0.44, 0.35, 0.3], (0, -1, 0)), rings=6, sides=6)
        plate(pt, M.Armor, sh + V((s * 0.35, -0.05, 0.55)), (s * 0.55, 0, 0.85), (s, 0.1, -0.2), 1.3, 1.45, t=0.26, shape='hex', bend=0.5, edge=M.Gold)
        spike(pt, M.Gold, sh + V((s * 0.6, 0.2, 0.85)), sh + V((s * 1.1, 0.75, 1.75)), 0.16)
        spike(pt, M.Gold, el + V((0, 0.15, 0)), el + V((s * 0.25, 1.15, -0.5)), 0.17)
        pt = P(f'forearm_{sd}', f'elbow_{sd}')
        tube(pt, M.Armor, Path([el, (el + wr) / 2 + V((0, -0.05, 0.08)), wr], [0.3, 0.27, 0.24], (0, -1, 0)), rings=5, sides=6)
        gem(pt, M.Gold, wr, 0.34, subdiv=1)
        spike(pt, M.Bone, wr + V((s * 0.1, -0.2, 0.2)), wr + V((s * 0.4, -0.7, 1.0)), 0.13, bend=(0, -0.15, 0.1))
        tips = [V((s * 8.0, 2.5, 11.1)), V((s * 8.3, 3.7, 8.4)), V((s * 7.1, 4.5, 5.7)), V((s * 4.9, 4.1, 3.9))]
        fingers = [Path([wr, lerp(wr, t, 0.5) + V((0, 0.3, 0.25)), t], [0.17, 0.12, 0.045], (0, 1, 0)) for t in tips]
        pt = P(f'fingers_{sd}', f'wrist_{sd}')
        for i, F in enumerate(fingers):
            tube(pt, M.Gold, F, 0.05, 2, rings=6, sides=5)
            if i < 3:
                nxt = fingers[i + 1]
                line(pt, M.Glow, [lerp(F.point(u), nxt.point(u), 0.07 / max(0.3, (F.point(u) - nxt.point(u)).length)) for u in (0.3, 0.9, 1.5, 1.9)], 0.045, sides=4)

        def panel(name, jn, A, B, nu=6, nv=4, scallop=0.9, billow=0.28, u0=0.06):
            rows = []
            for i in range(nu + 1):
                uu = lerp(u0, 1.0, i / nu)
                a, b = A(uu), B(uu)
                nrm = (b - a).cross(A(min(1, uu + 0.05)) - A(max(0, uu - 0.05))).normalized()
                row = []
                for j in range(nv + 1):
                    v = j / nv
                    p = lerp(a, b, v)
                    p += nrm * (billow * math.sin(math.pi * v) * math.sin(math.pi * uu) * s)
                    p -= (p - wr).normalized() * (scallop * math.sin(math.pi * v) * uu ** 3)
                    row.append(p)
                rows.append(row)
            sheet(P(name, jn), rows, mat_of=lambda i, j: M.MembraneHot if i >= nu - 2 else M.Membrane)
        for i in range(3):
            A, B = fingers[i], fingers[i + 1]
            panel(f'web{i}_{sd}', f'wrist_{sd}', lambda u, A=A: A.point(u * 2), lambda u, B=B: B.point(u * 2), scallop=0.85 - i * 0.1)
        body = V((s * 1.15, 1.35, 4.4))
        arm = Path([wr, el + V((0, 0.12, 0)), sh + V((0, 0.2, 0))], [0, 0, 0])
        F = fingers[3]
        rows = []
        nu, nv = 6, 5
        for i in range(nu + 1):
            u = i / nu
            a, b = arm.point(u * 2), lerp(F.point(2), body, u)
            b = b - (b - a).normalized() * (0.75 * math.sin(math.pi * u))
            rows.append([lerp(a, b, j / nv) + V((0, 0.18 * math.sin(math.pi * j / nv), 0)) for j in range(nv + 1)])
        sheet(P(f'web3_{sd}', f'elbow_{sd}'), rows, mat_of=lambda i, j: M.MembraneHot if j >= nv - 1 else M.Membrane)

    objs = rig.finish()

    # ---- clips: breathing idle with a slow wing beat; attack rears back, flares the wings and snaps forward
    def idle(jn, f):
        t = TAU * (f - 1) / (4 * FPS)
        side = 1 if jn.endswith('_L') else -1
        if jn == 'torso':
            return {'rot': (0.03 * math.sin(t), 0, 0.02 * math.sin(t + 1)), 'scale': 1 + 0.015 * math.sin(2 * t)}
        if jn == 'pelvis':
            return {'loc': (0, 0, 0.05 * math.sin(2 * t))}
        if jn == 'neck1':
            return {'rot': (0.05 * math.sin(t + 0.6), 0, 0.06 * math.sin(t))}
        if jn == 'neck2':
            return {'rot': (0.06 * math.sin(t + 1.2), 0, 0.06 * math.sin(t + 0.5))}
        if jn == 'head':
            return {'rot': (-0.06 * math.sin(t + 1.8), 0.04 * math.sin(t), 0.1 * math.sin(t + 1))}
        if jn == 'jaw':
            return {'rot': (0.07 * max(0.0, math.sin(2 * t)), 0, 0)}
        if jn.startswith('wing_'):
            return {'rot': (0, side * 0.13 * math.sin(2 * t), 0)}
        if jn.startswith('elbow_'):
            return {'rot': (0, side * 0.07 * math.sin(2 * t - 0.8), 0)}
        if jn.startswith('wrist_'):
            return {'rot': (0, side * 0.09 * math.sin(2 * t - 1.6), 0)}
        if jn.startswith('tail'):
            k = int(jn[-1])
            return {'rot': (0, 0, (0.04 + 0.04 * k) * math.sin(t - 0.7 * k))}
        return None

    def attack(jn, f):
        x = (f - 1) / FPS  # seconds, 0..1.5

        def env(*pts):
            for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
                if t0 <= x <= t1:
                    k = (x - t0) / (t1 - t0)
                    return lerp(v0, v1, k * k * (3 - 2 * k))
            return pts[-1][1]
        side = 1 if jn.endswith('_L') else -1
        if jn == 'torso':
            return {'rot': (env((0, 0), (0.5, -0.2), (0.78, 0.3), (1.5, 0)), 0, 0)}
        if jn == 'neck1':
            return {'rot': (env((0, 0), (0.5, -0.25), (0.78, 0.35), (1.5, 0)), 0, 0)}
        if jn == 'neck2':
            return {'rot': (env((0, 0), (0.5, -0.2), (0.78, 0.3), (1.5, 0)), 0, 0)}
        if jn == 'head':
            return {'rot': (env((0, 0), (0.5, -0.25), (0.78, 0.25), (1.5, 0)), 0, 0)}
        if jn == 'jaw':
            return {'rot': (env((0, 0), (0.5, 0.15), (0.78, 0.5), (1.1, 0.3), (1.5, 0)), 0, 0)}
        if jn.startswith('wing_'):
            return {'rot': (0, side * env((0, 0), (0.5, -0.4), (0.8, 0.3), (1.5, 0)), 0)}
        if jn.startswith('elbow_'):
            return {'rot': (0, side * env((0, 0), (0.5, -0.2), (0.85, 0.2), (1.5, 0)), 0)}
        if jn.startswith('tail'):
            k = int(jn[-1])
            return {'rot': (0, 0, env((0, 0), (0.5, 0.15 * k), (0.9, -0.2 * k), (1.5, 0)))}
        if jn == 'pelvis':
            return {'loc': (0, env((0, 0), (0.5, 0.3), (0.78, -0.5), (1.5, 0)), 0)}
        return None

    bake_clip(rig, 'idle', loop_frames(4), idle)
    bake_clip(rig, 'attack', loop_frames(1.5, 2), attack)
    return objs


# ---------------------------------------------------------------- RS-C011 «Безымянный охотник»

def hunter(rig):
    M = Mats('C011', {
        'Black': dict(color=0x17131f, metallic=0.55, roughness=0.26),
        'Violet': dict(color=0x5d2ca8, metallic=0.45, roughness=0.26),
        'VioletDeep': dict(color=0x2e1654, metallic=0.5, roughness=0.3),
        'Gold': dict(color=0xd9a94c, metallic=0.9, roughness=0.22),
        'Mask': dict(color=0xeae0ff, metallic=0.08, roughness=0.3),
        'Cape': dict(color=0x9a1a52, metallic=0.05, roughness=0.55),
        'CapeLining': dict(color=0x2a0f38, metallic=0.1, roughness=0.6),
        'Glow': dict(color=0xb45cff, emission=0xb45cff, strength=4.0),
        'GlowEye': dict(color=0xff3fd8, emission=0xff3fd8, strength=8.0),
    })
    J = rig.joint
    J('hips', (0, 0.05, 4.75))
    J('spine', (0, 0.05, 5.6), 'hips')
    J('head', (0, 0.05, 8.3), 'spine')
    J('cape', (0, 0.6, 7.6), 'spine')
    J('cape2', (0, 1.0, 5.2), 'cape')
    J('cape3', (0, 1.5, 2.8), 'cape2')
    for s, sd in ((1, 'L'), (-1, 'R')):
        J(f'leg_{sd}', (s * 0.62, 0.05, 4.6))
        J(f'arm_{sd}', (s * 1.6, 0.05, 7.5), 'spine')
        J(f'elbow_{sd}', (s * 2.15, 0.1, 5.95), f'arm_{sd}')
        J(f'hand_{sd}', (s * 2.3, -0.75, 4.85), f'elbow_{sd}')
        J(f'larm_{sd}', (s * 1.05, 0.1, 6.15), 'spine')
        J(f'lelbow_{sd}', (s * 1.8, -0.2, 5.45), f'larm_{sd}')
        J(f'lhand_{sd}', (s * 1.6, -1.15, 5.3), f'lelbow_{sd}')
    P = rig.part

    # ---- legs: black under-armour, violet greaves with gold trim, pointed sabatons
    for s, sd in ((1, 'L'), (-1, 'R')):
        jn = f'leg_{sd}'
        TH = Path([(s * 0.6, 0.05, 4.75), (s * 0.66, -0.05, 3.65), (s * 0.7, -0.15, 2.65)], [0.5, 0.44, 0.36])
        pt = P(f'thigh_{sd}', jn)
        tube(pt, M.Black, TH, rings=6, sides=8)
        pos, nrm, tan = TH.surf_dir(0.9, (s * 0.7, -1, 0), -0.06)
        plate(pt, M.Violet, pos, nrm, V((0, 0, 1)), 0.8, 1.55, t=0.16, shape='shield', bend=0.5, edge=M.Gold)
        SH = Path([(s * 0.7, -0.15, 2.65), (s * 0.72, 0.0, 1.6), (s * 0.74, 0.12, 0.75)], [0.36, 0.33, 0.27])
        pt = P(f'shin_{sd}', jn)
        tube(pt, M.Black, SH, rings=6, sides=8)
        pos, nrm, tan = SH.surf_dir(0.95, (0, -1, 0), -0.05)
        top = plate(pt, M.Violet, pos, nrm, V((0, 0, 1)), 0.66, 1.95, t=0.18, shape=[(0, -0.5), (0.5, -0.35), (0.5, 0.3), (0, 0.5), (-0.5, 0.3), (-0.5, -0.35)], bend=0.6, edge=M.Gold)
        line(pt, M.Glow, [top + V((0, -0.02, 0.7)), top + V((0, -0.02, -0.75))], 0.035, sides=4)
        pos, nrm, tan = TH.surf_dir(2.0, (0, -1, 0.1), -0.02)
        plate(pt, M.Gold, pos, nrm, V((0, 0, 1)), 0.55, 0.75, t=0.16, shape='kite')
        spike(pt, M.Gold, pos + nrm * 0.1, pos + nrm * 0.45 + V((0, 0, 0.45)), 0.1)
        pt = P(f'boot_{sd}', jn)
        x0 = s * 0.75

        def bsec(y, w, zt, zb=0.0):
            h = zt - zb
            return [V((x0 + x, y, z)) for x, z in ((0.9 * w, zb), (w, zb + 0.45 * h), (0.6 * w, zt), (-0.6 * w, zt), (-w, zb + 0.45 * h), (-0.9 * w, zb))]
        loft(pt, M.Violet, [bsec(0.5, 0.26, 0.85), bsec(0.1, 0.33, 0.8), bsec(-0.45, 0.3, 0.48), bsec(-0.95, 0.19, 0.28), V((x0, -1.3, 0.07))])
        plate(pt, M.Gold, (x0, -0.72, 0.38), (0, -0.45, 1), (0, -1, 0.3), 0.36, 0.7, t=0.08, shape='kite')
        spike(pt, M.Gold, (x0, 0.45, 0.35), (x0, 0.95, 0.1), 0.09)
        tube(pt, M.Black, Path([(s * 0.74, 0.12, 0.95), (x0, 0.12, 0.6)], [0.28, 0.3]), rings=2, sides=8)

    # ---- hips and waist: black core, gold belt, violet tassets, a long cloth tabard
    pt = P('pelvis', 'hips')
    tube(pt, M.Black, Path([(0, 0.05, 4.35), (0, 0.05, 4.95), (0, 0.05, 5.5)], [(0.95, 0.62), (0.82, 0.55), (0.62, 0.46)]), rings=5, sides=8)
    ring_loop(pt, M.Gold, [V((0.9 * math.cos(a), 0.05 + 0.62 * math.sin(a), 5.02)) for a in [TAU * i / 12 for i in range(12)]], 0.075, sides=5)
    ring_loop(pt, M.Glow, [V((0.8 * math.cos(a), 0.05 + 0.56 * math.sin(a), 5.2)) for a in [TAU * i / 12 for i in range(12)]], 0.035, sides=4)
    plate(pt, M.Gold, (0, -0.62, 5.02), (0, -1, 0), (0, 0, 1), 0.5, 0.42, t=0.12, shape='hex')
    gem(pt, M.Glow, (0, -0.76, 5.02), 0.12, scale=(1, 0.6, 1.3))
    for s in (1, -1):
        for fy in (-1, 1):
            plate(pt, M.Violet, (s * 0.78, 0.05 + fy * 0.32, 4.35), (s * 0.8, fy * 0.6, 0.1), (0, 0, 1), 0.78, 1.1, t=0.12, shape='shield', bend=0.3, edge=M.Gold)
    for fy, jn in ((-1, 'front'), (1, 'back')):
        rows = []
        for i in range(6):
            v = i / 5
            w = lerp(0.36, 0.3, v)
            z = lerp(4.95, 2.2 if fy < 0 else 2.9, v)
            y = 0.05 + fy * (0.66 + 0.25 * v * v)
            rows.append([V((w * x, y, z - (0.28 if (i == 5 and x == 0) else 0))) for x in (-1, -0.5, 0, 0.5, 1)])
        shell(P(f'tabard_{jn}', 'hips'), rows, 0.05, (0, fy, 0), M.Cape, M.CapeLining, M.Gold)

    # ---- torso: black cuirass, violet pectorals with gold trim, a glowing sigil at the sternum
    pt = P('abdomen', 'spine')
    tube(pt, M.Black, Path([(0, 0.08, 5.3), (0, 0.05, 5.9), (0, 0.0, 6.4)], [(0.62, 0.46), (0.7, 0.5), (0.85, 0.58)]), rings=4, sides=8)
    for z in (5.62, 5.95):
        plate(pt, M.Violet, (0, -0.47 - (z - 5.62) * 0.2, z), (0, -1, 0), (0, 0, 1), 0.95, 0.28, t=0.1, bend=0.4, edge=M.Gold)
    pt = P('cuirass', 'spine')

    def csec(z, rx, ry, yc=0.02):
        return [V((rx * math.cos(a), yc + ry * math.sin(a) * (1.15 if math.sin(a) < -0.9 else 1.0), z)) for a in [TAU * i / 12 for i in range(12)]]
    loft(pt, M.Black, [csec(6.2, 0.92, 0.6), csec(6.7, 1.22, 0.72), csec(7.2, 1.42, 0.72), csec(7.62, 1.28, 0.6), csec(7.92, 0.72, 0.45)])
    for s in (1, -1):
        plate(pt, M.Violet, (s * 0.6, -0.66, 7.05), (s * 0.35, -1, 0.12), (0, 0, 1), 1.02, 1.0, t=0.2, bend=0.35, edge=M.Gold)
    plate(pt, M.Violet, (0, 0.66, 7.0), (0, 1, 0.1), (0, 0, 1), 1.8, 1.3, t=0.18, bend=0.5, edge=M.Gold)
    core = V((0, -0.9, 6.62))
    plate(pt, M.Gold, core + V((0, 0.12, 0)), (0, -1, 0.05), (0, 0, 1), 0.52, 0.8, t=0.12, shape='diamond')
    gem(pt, M.Glow, core + V((0, -0.05, 0)), 0.2, scale=(1.0, 0.55, 1.6))
    for s in (1, -1):
        line(pt, M.Glow, [core + V((s * 0.18, 0.02, 0.3)), core + V((s * 0.55, 0.06, 0.95)), core + V((s * 0.62, 0.3, 1.25))], 0.035, sides=4)
        line(pt, M.Glow, [core + V((s * 0.14, 0.05, -0.3)), core + V((s * 0.3, 0.2, -0.75))], 0.035, sides=4)
    J('chest', core, 'spine')
    pt = P('collar', 'spine')
    for a in (-1.9, -1.1, -0.35, 0.35, 1.1, 1.9):
        d = V((math.sin(a), math.cos(a), 0))
        c = V((0, 0.05, 8.0)) + d * 0.62
        plate(pt, M.Black, c, d + V((0, 0, 0.35)), V((0, 0, 1)) + d * 0.35, 0.62, 1.0 - abs(a) * 0.12, t=0.1, shape='kite', edge=M.Gold)
    tube(pt, M.Black, Path([(0, 0.05, 7.8), (0, 0.05, 8.5)], [0.32, 0.3]), rings=2, sides=8)

    # ---- head: faceted helm, pale mask with magenta eye slits, swept horns tipped with gold
    pt = P('helm', 'head')

    def ring(z, rx, ry, yc=0.05, n=8):
        return [V((rx * math.cos(a), yc + ry * math.sin(a), z)) for a in [TAU * i / n + TAU / 16 for i in range(n)]]
    loft(pt, M.Black, [ring(8.2, 0.4, 0.44), ring(8.6, 0.5, 0.55), ring(9.0, 0.52, 0.58), ring(9.35, 0.44, 0.5), ring(9.6, 0.25, 0.32, 0.1), V((0, 0.12, 9.72))])
    plate(pt, M.Violet, (0, 0.05, 9.55), (0, 0.1, 1), (0, -1, 0.2), 0.3, 1.2, t=0.14, shape='kite', edge=M.Gold)
    for s in (1, -1):
        plate(pt, M.Violet, (s * 0.5, 0.02, 8.75), (s, 0.1, 0), (0, -0.3, 1), 0.55, 0.75, t=0.1, shape='shield', edge=M.Gold)
    pt = P('mask', 'head')
    top = plate(pt, M.Mask, (0, -0.52, 8.82), (0, -1, 0.05), (0, 0, 1), 0.86, 1.06, t=0.1,
                shape=[(0, -0.5), (0.3, -0.25), (0.5, 0.1), (0.45, 0.5), (-0.45, 0.5), (-0.5, 0.1), (-0.3, -0.25)], bend=0.5, bendv=0.1, edge=M.Gold)
    for s in (1, -1):
        plate(pt, M.GlowEye, (s * 0.2, -0.67, 8.98), (s * 0.2, -1, 0), (s * 0.45, 0, 1), 0.36, 0.13, t=0.06, taper=0.45)
    gem(pt, M.Glow, (0, -0.63, 9.22), 0.06, scale=(1, 0.6, 1.6), subdiv=0)
    line(pt, M.VioletDeep, [(0, -0.64, 8.75), (0, -0.66, 8.45)], 0.03, sides=4)
    pt = P('horns', 'head')
    for s in (1, -1):
        H = Path([(s * 0.36, -0.05, 9.3), (s * 0.7, 0.1, 9.75), (s * 0.95, 0.45, 10.35), (s * 1.0, 0.95, 10.95), (s * 0.85, 1.3, 11.35)], [0.17, 0.14, 0.1, 0.06, 0.0], (0, 1, 0))
        tube(pt, M.Black, H, 0, 2.7, rings=7, sides=6)
        tube(pt, M.Gold, H, 2.6, 4, rings=5, sides=6)
        ring_loop(pt, M.Gold, [H.surf(0.2, a, 0.02)[0] for a in [TAU * i / 8 for i in range(8)]], 0.04, sides=4)
        tube(pt, M.Gold, Path([(s * 0.45, 0.1, 8.95), (s * 0.85, 0.45, 9.1), (s * 1.15, 0.95, 9.35)], [0.1, 0.07, 0.0], (0, 0, 1)), rings=5, sides=5)

    # ---- the upper arms: layered pauldrons, clawed gauntlets, long glowing blades
    for s, sd in ((1, 'L'), (-1, 'R')):
        pt = P(f'pauldron_{sd}', f'arm_{sd}')
        plate(pt, M.Violet, (s * 1.62, 0.05, 7.92), (s * 0.5, 0, 0.87), (0, -1, 0), 1.5, 1.35, t=0.25, bend=0.55, edge=M.Gold)
        plate(pt, M.Violet, (s * 2.0, 0.05, 7.45), (s * 0.85, 0, 0.5), (0, -1, 0), 1.2, 1.25, t=0.22, bend=0.5, edge=M.Gold)
        plate(pt, M.VioletDeep, (s * 2.2, 0.05, 6.98), (s, 0, 0.15), (0, -1, 0), 0.9, 1.1, t=0.2, bend=0.4, edge=M.Gold)
        spike(pt, M.Gold, (s * 1.7, 0.3, 8.2), (s * 2.05, 0.7, 9.1), 0.14, bend=(s * 0.05, 0, 0))
        spike(pt, M.Gold, (s * 1.95, -0.15, 8.05), (s * 2.35, -0.25, 8.75), 0.1)
        pt = P(f'upper_{sd}', f'arm_{sd}')
        UA = Path([(s * 1.6, 0.05, 7.5), (s * 1.9, 0.08, 6.7), (s * 2.15, 0.1, 5.95)], [0.36, 0.32, 0.28])
        tube(pt, M.Black, UA, rings=5, sides=8)
        pos, nrm, tan = UA.surf_dir(1.1, (s, -0.35, 0), -0.04)
        top = plate(pt, M.Violet, pos, nrm, tan, 0.55, 1.05, t=0.14, shape='shield', bend=0.55, edge=M.Gold)
        line(pt, M.Glow, [top + tan * 0.3, top - tan * 0.35], 0.03, sides=4)
        pt = P(f'fore_{sd}', f'elbow_{sd}')
        FA = Path([(s * 2.15, 0.1, 5.95), (s * 2.25, -0.3, 5.4), (s * 2.3, -0.75, 4.85)], [0.27, 0.25, 0.22])
        tube(pt, M.Black, FA, rings=5, sides=8)
        pos, nrm, tan = FA.surf_dir(1.0, (s, 0.2, 0))
        top = plate(pt, M.Violet, pos, nrm, tan, 0.5, 1.2, t=0.14, shape='shield', bend=0.5, edge=M.Gold)
        line(pt, M.Glow, [top + tan * 0.4, top - tan * 0.45], 0.03, sides=4)
        plate(pt, M.VioletDeep, pos + nrm * 0.1 + V((0, 0.25, 0.1)), nrm, V((0, 1, 0.35)), 0.4, 1.0, t=0.06, shape='fin', edge=M.Gold)
        plate(pt, M.Violet, (s * 2.18, 0.42, 5.95), (0, 1, 0), (0, 0, 1), 0.45, 0.6, t=0.12, shape='kite', edge=M.Gold)
        spike(pt, M.Gold, (s * 2.2, 0.5, 5.9), (s * 2.3, 1.05, 5.65), 0.1)
        hand = rig.jw[f'hand_{sd}']
        pt = P(f'hand_{sd}', f'hand_{sd}')
        gem(pt, M.Black, hand + V((0, -0.08, -0.12)), 0.26, scale=(1, 1.1, 1.2))
        plate(pt, M.Gold, hand + V((s * 0.05, -0.28, -0.05)), (s * 0.3, -1, 0.2), (0, 0, 1), 0.35, 0.35, t=0.08)
        d = V((s * 0.2, -0.65, -0.73)).normalized()
        n = (V((1, 0, 0)) - d * d.x).normalized()
        grip = hand + V((0, -0.1, -0.12))
        line(pt, M.Gold, [grip - d * 0.45, grip + d * 0.25], 0.075, sides=6)
        gem(pt, M.Glow, grip - d * 0.52, 0.1, subdiv=0)
        guard = grip + d * 0.3
        plate(pt, M.Gold, guard - d * 0.06, d, n, 0.3, 0.75, t=0.1, shape='diamond')
        pt = P(f'blade_{sd}', f'hand_{sd}')
        c = guard + d * 1.85
        plate(pt, M.Glow, c - n * 0.03, n, d, 0.62, 3.4, t=0.07, bev=0.04,
              shape=[(0.35, -0.5), (-0.3, -0.5), (-0.48, -0.25), (-0.5, 0.05), (-0.38, 0.3), (-0.12, 0.47), (0.1, 0.52), (0.2, 0.3), (0.32, 0.0), (0.38, -0.3)])
        e = n.cross(d).normalized()
        line(pt, M.VioletDeep, [guard + d * 0.15 + e * 0.1, c + e * 0.1, c + d * 1.2 + e * 0.06], 0.045, sides=4)

    # ---- the lower arms: slender, with glowing talons (the "many-armed silhouette")
    for s, sd in ((1, 'L'), (-1, 'R')):
        sh, el, hd = rig.jw[f'larm_{sd}'], rig.jw[f'lelbow_{sd}'], rig.jw[f'lhand_{sd}']
        pt = P(f'lupper_{sd}', f'larm_{sd}')
        tube(pt, M.Black, Path([sh, (sh + el) / 2 + V((0, 0, -0.05)), el], [0.22, 0.19, 0.17]), rings=4, sides=6)
        plate(pt, M.Violet, sh + V((s * 0.3, -0.05, 0.05)), (s, -0.1, 0.5), (s, -0.3, -0.7), 0.5, 0.65, t=0.12, shape='kite', edge=M.Gold)
        pt = P(f'lfore_{sd}', f'lelbow_{sd}')
        LF = Path([el, (el + hd) / 2 + V((s * 0.05, 0, 0.05)), hd], [0.17, 0.15, 0.13])
        tube(pt, M.Black, LF, rings=4, sides=6)
        spike(pt, M.Gold, el + V((0, 0.1, 0)), el + V((s * 0.15, 0.6, -0.25)), 0.09)
        pos, nrm, tan = LF.surf_dir(1.0, (s, 0, 0.6))
        top = plate(pt, M.Violet, pos, nrm, tan, 0.36, 0.9, t=0.1, shape='shield', bend=0.4, edge=M.Gold)
        line(pt, M.Glow, [top + tan * 0.3, top - tan * 0.3], 0.028, sides=4)
        pt = P(f'claws_{sd}', f'lhand_{sd}')
        base = rig.jw[f'lhand_{sd}']
        gem(pt, M.Black, base, 0.16, scale=(1, 1.2, 1))
        for k in (-1, 0, 1):
            spike(pt, M.Glow, base + V((k * 0.08 * s, -0.1, 0)), base + V((s * (0.05 + k * 0.2), -1.05, -0.35 + k * 0.1)), 0.06, sides=4, bend=(0, 0, 0.18))

    # ---- cape: three layered bands on a joint chain, red-violet outside, dark lining, gold rim, a glowing rune line
    def capept(xn, v, lift=0.0):
        W = 1.45 + 1.05 * v
        x = xn * W
        z = 7.78 - v * (7.78 - 0.35) + lift
        y = 0.62 + 0.45 * v + 1.05 * v * v - (0.5 + 0.7 * v) * xn * xn + 0.18 * v * math.sin(xn * 3 * math.pi)
        return V((x, y, z))
    nx = 13
    bands = ((0.0, 0.37, 'cape'), (0.33, 0.7, 'cape2'), (0.66, 1.0, 'cape3'))
    for k, (v0, v1, jn) in enumerate(bands):
        rows = []
        nrows = 4
        for i in range(nrows + 1):
            v = lerp(v0, v1, i / nrows)
            row = []
            for j in range(nx):
                xn = -1 + 2 * j / (nx - 1)
                lift = 0.0
                if k == 2 and i == nrows:
                    lift = 0.55 if j % 2 else 0.0
                p = capept(xn, v, lift)
                p.y -= k * 0.035
                row.append(p)
            rows.append(row)
        shell(P(f'cape{k}', jn), rows, 0.06, (0, 1, 0), M.Cape, M.CapeLining, M.Gold)
    pt = P('cape_trim', 'cape')
    line(pt, M.Gold, [capept(-1 + 2 * j / 12, 0.0) + V((0, 0.03, 0.02)) for j in range(13)], 0.07, sides=5, rings=26)
    for s in (1, -1):
        gem(pt, M.Gold, capept(s * 0.93, 0.01) + V((0, -0.05, 0.02)), 0.2, subdiv=1)
        gem(pt, M.Glow, capept(s * 0.93, 0.01) + V((0, -0.2, 0.02)), 0.09, subdiv=0)
    pt = P('cape_rune', 'cape3')
    line(pt, M.Glow, [capept(-1 + 2 * j / 16, 0.86) + V((0, 0.05, 0)) for j in range(17)], 0.04, sides=4, rings=40)

    objs = rig.finish()

    def idle(jn, f):
        t = TAU * (f - 1) / (4 * FPS)
        side = 1 if jn.endswith('_L') else -1
        if jn == 'spine':
            return {'rot': (0.025 * math.sin(t), 0, 0.03 * math.sin(t + 0.5)), 'scale': 1 + 0.012 * math.sin(2 * t)}
        if jn == 'hips':
            return {'loc': (0, 0, 0.035 * math.sin(2 * t))}
        if jn == 'head':
            return {'rot': (0.05 * math.sin(2 * t + 1), 0, 0.16 * math.sin(t))}
        if jn.startswith('arm_'):
            return {'rot': (0.05 * math.sin(t + side), side * 0.04 * math.sin(t), 0)}
        if jn.startswith('elbow_'):
            return {'rot': (0.06 * math.sin(t + 1), 0, 0)}
        if jn.startswith('hand_'):
            return {'rot': (0.1 * math.sin(2 * t + side), 0, 0)}
        if jn.startswith('larm_'):
            return {'rot': (0.12 * math.sin(2 * t + side * 1.3), side * 0.05 * math.sin(t), 0)}
        if jn.startswith('lelbow_'):
            return {'rot': (0.1 * math.sin(2 * t + side), 0, 0)}
        if jn == 'cape':
            return {'rot': (0.03 + 0.025 * math.sin(t), 0, 0.02 * math.sin(t + 0.4))}
        if jn == 'cape2':
            return {'rot': (0.04 * math.sin(t - 0.8), 0, 0.03 * math.sin(t - 0.3))}
        if jn == 'cape3':
            return {'rot': (0.07 * math.sin(t - 1.6), 0, 0.05 * math.sin(t - 1.0))}
        return None

    def attack(jn, f):
        x = (f - 1) / FPS

        def env(*pts):
            for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
                if t0 <= x <= t1:
                    k = (x - t0) / (t1 - t0)
                    return lerp(v0, v1, k * k * (3 - 2 * k))
            return pts[-1][1]
        side = 1 if jn.endswith('_L') else -1
        if jn == 'spine':
            return {'rot': (env((0, 0), (0.5, -0.15), (0.78, 0.25), (1.5, 0)), 0, env((0, 0), (0.5, 0.3), (0.78, -0.25), (1.5, 0)))}
        if jn == 'head':
            return {'rot': (env((0, 0), (0.5, -0.1), (0.78, 0.15), (1.5, 0)), 0, 0)}
        if jn.startswith('arm_'):
            return {'rot': (env((0, 0), (0.5, 0.55), (0.8, -1.15), (1.5, 0)), 0, side * env((0, 0), (0.5, 0.25), (0.8, -0.3), (1.5, 0)))}
        if jn.startswith('elbow_'):
            return {'rot': (env((0, 0), (0.5, 0.3), (0.8, -0.35), (1.5, 0)), 0, 0)}
        if jn.startswith('hand_'):
            return {'rot': (env((0, 0), (0.5, 0.4), (0.8, -0.3), (1.5, 0)), 0, 0)}
        if jn.startswith('larm_'):
            return {'rot': (env((0, 0), (0.55, 0.3), (0.85, -0.7), (1.5, 0)), 0, 0)}
        if jn == 'cape':
            return {'rot': (env((0, 0.03), (0.5, 0.0), (0.85, 0.24), (1.5, 0.03)), 0, 0)}
        if jn == 'cape2':
            return {'rot': (env((0, 0), (0.55, -0.03), (0.9, 0.1), (1.5, 0)), 0, 0)}
        if jn == 'cape3':
            return {'rot': (env((0, 0), (0.6, -0.04), (0.95, 0.12), (1.5, 0)), 0, 0)}
        if jn == 'hips':
            return {'loc': (0, env((0, 0), (0.5, 0.25), (0.78, -0.45), (1.5, 0)), 0)}
        return None

    bake_clip(rig, 'idle', loop_frames(4), idle)
    bake_clip(rig, 'attack', loop_frames(1.5, 2), attack)
    rig.root.scale = (1.1, 1.1, 1.1)  # a tall hunter: stands a head above the wyvern's shoulders
    return objs


BUILDERS = {'RS-C001': wyvern, 'RS-C011': hunter}


# ---------------------------------------------------------------- build, preview, export

def stats(objs):
    tris = 0
    for o in objs:
        me = o.data
        me.calc_loop_triangles()
        tris += len(me.loop_triangles)
    return tris


def bounds(objs):
    pts = [o.matrix_world @ V(c) for o in objs for c in o.bound_box]
    lo = V((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = V((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def _window():
    wm = bpy.context.window_manager
    return wm.windows[0] if wm.windows else None


def build(cid, out_dir=None, show=True):
    rig = Rig(cid)
    win = _window()
    if show and win:
        win.scene = rig.scene
    objs = BUILDERS[cid](rig)
    rig.scene.frame_set(1)
    bpy.context.view_layer.update() if bpy.context.view_layer else None
    lo, hi = bounds(objs)
    info = {'id': cid, 'parts': len(objs), 'tris': stats(objs), 'min': list(map(lambda v: round(v, 2), lo)), 'max': list(map(lambda v: round(v, 2), hi))}
    if out_dir:
        info['glb'] = export(rig.scene, f'{out_dir}/{cid}.glb')
    return info


def export(scene, path):
    # object names are global in Blender: give this colossus the plain joint names the game looks up (chest, head...)
    for o in list(scene.objects):
        base = re.sub(r'\.\d{3}$', '', o.name)
        if base != o.name:
            other = bpy.data.objects.get(base)
            if other is not None:
                other.name = f'{base}~{other.users_scene[0].name if other.users_scene else "old"}'
            o.name = base
    win = _window()
    prev = win.scene if win else None
    if win:
        win.scene = scene
    try:
        with bpy.context.temp_override(window=win, scene=scene):
            bpy.ops.export_scene.gltf(
                filepath=path, export_format='GLB', use_active_scene=True, use_selection=False,
                export_yup=True, export_apply=False, export_cameras=False, export_lights=False,
                export_materials='EXPORT', export_image_format='NONE', export_extras=False,
                export_animations=True, export_animation_mode='NLA_TRACKS', export_force_sampling=True,
                export_optimize_animation_size=True, export_def_bones=False, export_morph=False, export_vertex_color='NONE')
    finally:
        if win and prev:
            win.scene = prev
    return path


def preview(cid, out_png, views=(('front', (0.55, -1.0, 0.18)), ('side', (1.0, -0.15, 0.08)))):
    """Quick EEVEE renders of a built colossus (cameras and lights live in a side scene that links the objects)."""
    src = bpy.data.scenes[cid]
    name = f'{cid} preview'
    old = bpy.data.scenes.get(name)
    if old:
        for o in list(old.objects):
            if o.type in ('CAMERA', 'LIGHT'):
                bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.scenes.remove(old)
    sc = bpy.data.scenes.new(name)
    sc.collection.children.link(src.collection) if False else None
    for o in src.objects:
        sc.collection.objects.link(o)
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.resolution_x = sc.render.resolution_y = 720
    sc.render.film_transparent = False
    try:
        sc.view_settings.view_transform = 'Standard'
    except Exception:
        pass
    world = bpy.data.worlds.get('RS preview') or bpy.data.worlds.new('RS preview')
    world.color = (0.55, 0.7, 0.9)
    try:
        world.use_nodes = True
    except Exception:
        pass
    bg = next((n for n in world.node_tree.nodes if n.type == 'BACKGROUND'), None) if world.node_tree else None
    if bg:
        bg.inputs[0].default_value = (0.62, 0.76, 0.95, 1)
        bg.inputs[1].default_value = 0.9
    sc.world = world
    for nm, e, rot in (('key', 3.5, (0.8, 0.2, 0.9)), ('rim', 2.5, (-0.9, 0.3, -2.4))):
        ld = bpy.data.lights.new(f'{cid} {nm}', 'SUN')
        ld.energy = e
        lo = bpy.data.objects.new(f'{cid} {nm}', ld)
        lo.rotation_euler = rot
        sc.collection.objects.link(lo)
    cd = bpy.data.cameras.new(f'{cid} cam')
    cd.lens = 50
    cam = bpy.data.objects.new(f'{cid} cam', cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    lo, hi = bounds([o for o in src.objects if o.type == 'MESH'])
    ctr = (lo + hi) / 2
    size = max(hi - lo)
    out = []
    win = _window()
    for tag, d in views:
        d = V(d).normalized()
        cam.location = ctr + d * size * 1.9
        cam.rotation_euler = (ctr - cam.location).to_track_quat('-Z', 'Y').to_euler()
        sc.frame_set(12)
        path = out_png.replace('.png', f'-{tag}.png')
        sc.render.filepath = path
        with bpy.context.temp_override(window=win, scene=sc):
            bpy.ops.render.render(write_still=True, scene=sc.name)
        out.append(path)
    return out
