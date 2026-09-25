"""
Recognition: learning what things are and where they are in the picture.

On top of the visual cortex sit readout neurons, one set for every zone of the picture (5x5 zones,
retinotopic: a cortical neuron reports to the zone its receptive field lies in). For each zone they learn
a name (oak_log, zombie, water, sky, ...) and how far it is (<=2, <=5, <=12, farther). Nothing about
any object is written in: the vocabulary grows by itself - a new name gets a new readout neuron the first
time the teacher says it (neurogenesis) - and the synapses learn by the cerebellar error rule: only when
the guess was wrong, only the synapses of the neurons active right now, +1 to the right name, -1 to the
wrong one. The teacher is the body: what each zone really shows (a ray through it, like touching what
you see, or a parent naming it). A child learns the names of things in the same way.

Runs on the GPU when there is one (PyTorch), else on the CPU.
"""
import json
import os

import numpy as np
import torch

DIST_EDGES = (2.0, 5.0, 12.0)          # distance buckets: 0 <=2, 1 <=5, 2 <=12, 3 farther (as relDir)
EMPTY = ("sky", "far", "nothing")


def dist_bucket(d):
    return int(sum(d > e for e in DIST_EDGES))


class Recognizer:
    def __init__(self, cy, cx, size, grid=5, dev=None, capacity=512):
        self.dev = dev or torch.device("cpu")
        self.grid, self.size = grid, size
        cy = torch.as_tensor(np.asarray(cy), device=self.dev).long()
        cx = torch.as_tensor(np.asarray(cx), device=self.dev).long()
        self.zone = (cy * grid // size).clamp(max=grid - 1) * grid + (cx * grid // size).clamp(max=grid - 1)
        self.n = len(cy)
        self.W = torch.zeros((self.n, capacity), device=self.dev)       # zone readouts: what it is
        self.WD = torch.zeros((self.n, 4), device=self.dev)             # ... and how far
        self.names, self.kind, self.idx = ["nothing"], {"nothing": "sky"}, {"nothing": 0}
        self.seen = {}                  # name -> how often the teacher showed it
        self.right = {}                 # name -> running share of zones where it was recognised correctly
        self.acc, self.acc_dist, self.session = 0.0, 0.0, 0

    # ---------------------------------------------------------------- vocabulary (neurogenesis)
    def _cls(self, name, kind):
        i = self.idx.get(name)
        if i is None:
            i = len(self.names)
            if i >= self.W.shape[1]:                                    # more names than readouts: grow
                self.W = torch.cat([self.W, torch.zeros_like(self.W)], 1)
            self.idx[name] = i
            self.names.append(name)
            self.kind[name] = kind
        return i

    # ---------------------------------------------------------------- seeing
    @torch.no_grad()
    def _scores(self, code):
        code = torch.as_tensor(code, device=self.dev).long()
        z = self.zone[code]
        Z = self.grid * self.grid
        S = torch.zeros((Z, len(self.names)), device=self.dev).index_add_(0, z, self.W[code, :len(self.names)])
        D = torch.zeros((Z, 4), device=self.dev).index_add_(0, z, self.WD[code])
        cnt = torch.bincount(z, minlength=Z).float()
        return code, z, S, D, cnt

    @torch.no_grad()
    def perceive(self, code):
        """-> per zone (row by row): (name, distance bucket, confidence 0..1, kind)."""
        _, _, S, D, cnt = self._scores(code)
        return self._read(S, D, cnt)

    def _read(self, S, D, cnt):
        k = min(2, S.shape[1])
        top = S.topk(k, dim=1)
        pred = top.indices[:, 0]
        margin = (top.values[:, 0] - (top.values[:, 1] if k > 1 else 0)) / (cnt + 1.0)
        conf = torch.clamp(margin / 2.0, 0, 1)
        dist = D.argmax(1)
        out = []
        for p, d, c in zip(pred.tolist(), dist.tolist(), conf.tolist()):
            name = self.names[p]
            out.append((name, d, c, self.kind.get(name, "block")))
        return out

    @torch.no_grad()
    def teach(self, code, labels):
        """labels: per zone [name, distance, kind] from the body. Learns from the mistakes; returns what
        the eyes saw BEFORE learning (the honest percept of this moment)."""
        y = torch.tensor([self._cls(str(l[0]), str(l[2]) if len(l) > 2 else "block") for l in labels], device=self.dev)
        yd = torch.tensor([dist_bucket(float(l[1])) for l in labels], device=self.dev)
        code, z, S, D, cnt = self._scores(code)
        percept = self._read(S, D, cnt)
        pred, pd = S.argmax(1), D.argmax(1)
        wrong = (pred != y)[z]                                          # active neurons of zones guessed wrong
        if wrong.any():
            i, zz = code[wrong], z[wrong]
            one = torch.ones(len(i), device=self.dev)
            self.W.index_put_((i, y[zz]), one, accumulate=True)
            self.W.index_put_((i, pred[zz]), -one, accumulate=True)
        wd = (pd != yd)[z]
        if wd.any():
            i, zz = code[wd], z[wd]
            one = torch.ones(len(i), device=self.dev)
            self.WD.index_put_((i, yd[zz]), one, accumulate=True)
            self.WD.index_put_((i, pd[zz]), -one, accumulate=True)
        # how well do the eyes already know things (measured before learning from this picture)
        ok = (pred == y).float()
        self.session += 1
        k = max(0.002, 1.0 / self.session)
        self.acc += k * (float(ok.mean()) - self.acc)
        self.acc_dist += k * (float((pd == yd).float().mean()) - self.acc_dist)
        for name, good in zip((str(l[0]) for l in labels), ok.tolist()):
            n = self.seen.get(name, 0) + 1
            self.seen[name] = n
            self.right[name] = self.right.get(name, 0.0) + max(0.01, 1.0 / n) * (good - self.right.get(name, 0.0))
        return percept

    # ---------------------------------------------------------------- what it knows
    def known(self, min_seen=20):
        """Things the eyes have been shown enough times, with how well they recognise each."""
        rows = [(n, self.right.get(n, 0.0), c) for n, c in self.seen.items() if c >= min_seen]
        return sorted(rows, key=lambda r: -r[2])

    def save(self, prefix):
        np.savez_compressed(prefix + ".npz", W=self.W[:, :len(self.names)].cpu().numpy(), WD=self.WD.cpu().numpy())
        with open(prefix + ".json", "w", encoding="utf-8") as f:
            json.dump({"names": self.names, "kind": self.kind, "seen": self.seen, "right": self.right,
                       "acc": self.acc, "acc_dist": self.acc_dist}, f, ensure_ascii=False)

    def load(self, prefix):
        if not (os.path.exists(prefix + ".npz") and os.path.exists(prefix + ".json")):
            return False
        z = np.load(prefix + ".npz")
        if z["W"].shape[0] != self.n:
            return False
        meta = json.load(open(prefix + ".json", encoding="utf-8"))
        self.names, self.kind = meta["names"], meta["kind"]
        self.idx = {n: i for i, n in enumerate(self.names)}
        self.seen, self.right = meta["seen"], meta["right"]
        self.acc, self.acc_dist = meta["acc"], meta["acc_dist"]
        cap = max(self.W.shape[1], 1 << int(np.ceil(np.log2(max(2, len(self.names))))))
        self.W = torch.zeros((self.n, cap), device=self.dev)
        self.W[:, :len(self.names)] = torch.as_tensor(z["W"], device=self.dev)
        self.WD = torch.as_tensor(z["WD"], device=self.dev).clone()
        return True
