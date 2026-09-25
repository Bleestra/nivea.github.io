"""
Seeing: the eyes of the grown brain - they see, learn to recognise, and hand what they recognise to the
rest of the brain, which learns how to react.

  retina -> visual cortex (visual_cortex_gpu / visual_cortex)
         -> recognition (recognizer.py): what is in each of 5x5 zones of the picture and how far
         -> the sensor teacher (teacher): the 5x5 cells ahead on the ground, the sky, where a tree is

The body's direct senses and the rays through the picture (vis_labels) are only the TEACHER. How much the
brain relies on its eyes instead of them is a choice of senses:
  full   - the direct senses as before; what the eyes recognise is added (the habits learn from both)
  grow   - as a child: the direct senses fade as the eyes become good at each of them (measured agreement)
  human  - only what a person has: vision, hearing, touch, the body's feelings, the HUD and the recipe book
In every mode the eyes' percepts become cells of the habits and "see:" concepts of the mind, so what is
recognised can be reacted to, and which reactions are good is learned (nothing like "see zombie -> hit").
"""
import os

import numpy as np

REP_DIST = (1, 4, 9, 20)                                # a distance for each distance bucket
SENSES = ("full", "grow", "human")


class Seeing:
    def __init__(self, prefix, device="auto", neurons=131072, size=256, models=None, zones=8):
        import torch

        from recognizer import Recognizer

        self.prefix = prefix
        # One live frame at a time is faster on the CPU (8 ms) than on a GPU that is busy drawing the game (46 ms,
        # measured on an RTX 3090 with Minecraft running); the GPU is for developing the eyes on many frames at once
        # (develop_gpu.py). "cuda" puts them on the GPU anyway.
        dev_live = torch.device("cuda") if device == "cuda" and torch.cuda.is_available() else torch.device("cpu")
        want_gpu = True                                          # the large (torch) cortex, on dev_live
        self.gpu = dev_live.type == "cuda"
        if want_gpu:
            from visual_cortex_gpu import SensorTeacherGPU, VisualCortexGPU, retina_gpu

            if dev_live.type == "cpu":
                torch.set_num_threads(4)                         # several brains share the processor
            self.cortex = VisualCortexGPU(n=neurons, size=size, seed=1, dev=dev_live)
            self.retina = lambda f: retina_gpu(f, size, dev_live)[0]
            self.teacher = SensorTeacherGPU(self.cortex.n, dev=dev_live)
            dev = self.cortex.dev
            cy, cx, sz = self.cortex.cy.cpu().numpy(), self.cortex.cx.cpu().numpy(), size
            loaded = self.cortex.load(prefix + "_cortex_gpu.npz") or (
                models is not None and self.cortex.load(os.path.join(models, "visual_cortex_gpu.npz")))
        else:
            from teacher import SensorTeacher
            from visual_cortex import SIZE, VisualCortex, retina

            self.cortex = VisualCortex(seed=1)
            self.retina = retina
            self.teacher = SensorTeacher(self.cortex.n)
            dev = torch.device("cpu")
            cy, cx, sz = self.cortex.cy, self.cortex.cx, SIZE
            vc = os.path.join(models, "visual_cortex.npz") if models else ""
            loaded = False
            if os.path.exists(prefix + "_cortex.npz"):
                self.cortex.syn[:] = np.load(prefix + "_cortex.npz")["syn"]
                loaded = True
            elif vc and os.path.exists(vc):
                self.cortex.syn[:] = np.load(vc)["syn"]
                loaded = True
        self.loaded = loaded
        tpath = prefix + "_eyes_gpu.npz"                          # the large cortex's readouts (on either device)
        if os.path.exists(tpath):
            self.teacher.load(tpath)
        self.G = zones                                          # the picture is understood in G x G zones
        self.rec = Recognizer(cy, cx, sz, grid=zones, dev=dev)
        self.rec.load(prefix + "_recognition")
        self.last = None
        self._prev = None                                       # the previous look (for motion)

    def describe(self):
        where = "GPU" if self.gpu else "CPU (live frames are faster there while the GPU draws the game)"
        size = getattr(self.cortex, "size", 64)
        return (f"eyes on the {where}: {self.cortex.n} neurons, {size}x{size} picture, {self.G}x{self.G} zones, "
                f"knows {len(self.rec.names) - 1} things")

    def _dir_of(self, z):
        """A zone's direction as the body's relDir: left (4), ahead (1) or right (2)."""
        f = ((z % self.G) + 0.5) / self.G
        return 4 if f < 0.4 else 2 if f > 0.6 else 1

    # ---------------------------------------------------------------- one look
    def look(self, frame, m):
        """frame: uint8 BGR; m: the body's report (its direct senses and vis_labels teach the eyes)."""
        code = self.cortex(self.retina(frame), plasticity=True)
        grid = np.asarray(m.get("obs", [0] * 25))
        pg, ps, pt = self.teacher.teach(code, grid, int(m.get("sky", 0)), int(m.get("goal", 0)) // 4)
        code_np = code.cpu().numpy() if hasattr(code, "cpu") else np.asarray(code)
        labels = m.get("vis_labels")
        zones = self.rec.teach(code_np, labels) if labels and len(labels) == self.G * self.G else self.rec.perceive(code_np)
        ids = []
        for z, (name, d, conf, kind) in enumerate(zones):
            if conf > 0.05 and name not in ("nothing", "sky", "far"):
                ids.append((z * 4 + d) * 4096 + self.rec.idx.get(name, 0) % 4096)
        motion = self._motion(frame, m, zones)
        for i, what in enumerate(("moving", "approach")):
            ids += [(1000 + i) * 4096 + self.rec.idx.get(n, 0) % 4096 for n in motion[what]]
        self.last = {"grid": np.asarray(pg), "sky": int(ps), "tree": int(pt), "zones": zones, "ids": ids,
                     "labels": labels, "motion": motion}
        return self.last

    def _motion(self, frame, m, zones):
        """Seeing things move: a being that is nearer than a moment ago approaches (this works while I walk
        too); when my head is still, a zone whose picture changed holds something moving."""
        import cv2

        side = self.G * 8
        g = cv2.resize(cv2.cvtColor(np.ascontiguousarray(frame), cv2.COLOR_BGR2GRAY), (side, side), interpolation=cv2.INTER_AREA).astype(np.int16)
        look, pos = tuple(m.get("look") or (0.0, 0.0)), m.get("pos")
        prev, self._prev = self._prev, (g, look, pos, zones)
        out = {"moving": [], "approach": []}
        if prev is None:
            return out
        pg, plook, ppos, pzones = prev
        beings = lambda zs: [(n, d) for n, d, c, k in zs if k == "mob" and c > 0.05]
        before = {}
        for n, d in beings(pzones):
            before[n] = min(before.get(n, 9), d)
        for n, d in beings(zones):
            if n in before and d < before[n] and n not in out["approach"]:
                out["approach"].append(n)
        moved = pos is not None and ppos is not None and sum((a - b) ** 2 for a, b in zip(pos, ppos)) > 0.02
        if abs(look[0] - plook[0]) < 1 and abs(look[1] - plook[1]) < 1 and not moved:
            energy = np.abs(g - pg).reshape(self.G, 8, self.G, 8).mean(axis=(1, 3)).ravel()
            for z, (n, d, c, k) in enumerate(zones):
                if energy[z] > 10 and k == "mob" and c > 0.05 and n not in out["moving"]:
                    out["moving"].append(n)
        return out

    def _zone_point(self, m, z, dist):
        """Where in the world a zone of the picture at this distance is (the eyes' own estimate of a place)."""
        pos, look = m.get("pos"), m.get("look")
        if not pos or not look:
            return None
        yaw, pitch = np.radians(look[0]), np.radians(look[1])
        f = np.array([-np.sin(yaw) * np.cos(pitch), -np.sin(pitch), np.cos(yaw) * np.cos(pitch)])
        right = np.array([-f[2], 0.0, f[0]])
        right = right / (np.linalg.norm(right) + 1e-9)
        up = np.cross(right, f)
        t = np.tan(np.radians(float(m.get("fov", 70))) / 2)
        u, v = ((z % self.G) + 0.5) / self.G * 2 - 1, ((z // self.G) + 0.5) / self.G * 2 - 1
        d = f + right * (u * t) + up * (-v * t)
        p = np.array(pos) + np.array([0, 1.62, 0]) + d / np.linalg.norm(d) * dist
        return [int(np.floor(x)) for x in p]

    # ---------------------------------------------------------------- how much to trust the eyes
    def trust(self):
        """0..1 per sense: how far the eyes can replace it. It grows with measured agreement AND with
        experience: a few hundred pictures that happen to agree are not yet eyes one can trust."""
        t = lambda a, n: float(np.clip((a - 0.5) / 0.4, 0.0, 1.0)) * min(1.0, n / 3000.0)
        acc = self.teacher.acc
        n_t = float(self.teacher.n)                              # pictures the ground/sky/tree readouts learned from
        n_r = sum(self.rec.seen.values()) / float(self.G * self.G)   # pictures the recognition learned from
        return {"grid": t(acc["grid"], n_t), "sky": t(acc["sky"], n_t), "tree": t(acc["tree"], n_t),
                "things": t(self.rec.acc, n_r)}

    def apply(self, m, mode, rng=np.random):
        """Replace the body's direct senses in m by what the eyes perceive, as the chosen senses say."""
        p = self.last
        if p is None or mode == "full":
            return
        tr = self.trust() if mode == "grow" else {k: 1.0 for k in ("grid", "sky", "tree", "things")}
        if rng.random() < tr["grid"]:
            m["obs"] = [int(x) for x in p["grid"]]
        if rng.random() < tr["sky"]:
            m["sky"] = p["sky"]
        if rng.random() < tr["things"]:
            seen, goal, diamond = {}, 0, 0
            best_log = None
            for z, (name, d, conf, kind) in enumerate(p["zones"]):
                if conf <= 0.05 or name in ("nothing", "sky", "far"):
                    continue
                dist = REP_DIST[d]
                if name not in seen or seen[name][0] > dist:
                    seen[name] = (dist, "mob" if kind in ("mob", "item") else "block", self._zone_point(m, z, dist))
                code = self._dir_of(z) * 4 + min(d, 3)
                if name.endswith("_log") and (best_log is None or d < best_log[0]):
                    best_log = (d, code)
                if "diamond_ore" in name:
                    diamond = code
            if best_log:
                goal = best_log[1]
            m["seen"] = [[n, dist, k] + (xyz or []) for n, (dist, k, xyz) in seen.items()]
            m["goal"] = goal
            m["diamond_seen"] = diamond
            vis = set(m.get("near_vis", []))                   # beings: those I see, or that are touching me
            m["near"] = [x for x in m.get("near", []) if x[1] in vis or x[2] <= 1]
        if mode == "human":
            m["_human"] = True                                 # hearing: only real sounds (feel_bridge)

    # ---------------------------------------------------------------- memory
    def save(self):
        self.cortex.save(self.prefix + "_cortex_gpu.npz")        # the large cortex, whichever device it ran on
        self.teacher.save(self.prefix + "_eyes_gpu.npz")
        self.rec.save(self.prefix + "_recognition")

    def stats(self):
        acc = self.teacher.acc
        return {"things": round(self.rec.acc, 3), "distance": round(self.rec.acc_dist, 3),
                "ground": round(acc["grid"], 3), "sky": round(acc["sky"], 3), "tree": round(acc["tree"], 3),
                "vocabulary": len(self.rec.names) - 1,
                "known": [[n, round(r, 2), c] for n, r, c in self.rec.known()[:40]],
                "trust": {k: round(v, 2) for k, v in self.trust().items()}}
