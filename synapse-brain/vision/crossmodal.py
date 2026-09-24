"""
Cross-modal learning: the bot's direct senses teach its eyes.

Recorded live frames (first-person 3D view, 64x64) come with what the direct senses said at the
same moment. A cerebellar readout on the visual cortex code learns to predict, from the image only:
  front   : the block class right in front (walkable / tree / stone / lava / water / wall)
  walk    : can I step forward?
  tree    : is there a tree anywhere in the 5x5 area ahead?
  goal    : direction of the nearest reachable log (none / ahead / right / behind / left)
Tested on recordings the readout never saw. Compared: newborn cortex, cortex developed on MineRL
videos, cortex developed on MineRL + the live frames themselves (all unsupervised).
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vision_bench import watch_videos  # noqa: E402
from visual_cortex import VisualCortex, retina  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    files = sorted(glob.glob(os.path.join(HERE, "..", "data", "mc_frames", "rec_*.npz")))
    F, G, Q = [], [], []
    for f in files:
        z = np.load(f)
        F.append(z["frames"]), G.append(z["grid"]), Q.append(z["goal"])
    cut = max(1, int(len(files) * 0.8))
    tr = (np.concatenate(F[:cut]), np.concatenate(G[:cut]), np.concatenate(Q[:cut]))
    te = (np.concatenate(F[cut:]), np.concatenate(G[cut:]), np.concatenate(Q[cut:]))
    return tr, te, len(files)


def targets(G, Q):
    return {"front": G[:, 7], "walk": (G[:, 7] == 0).astype(int), "tree": (G == 1).any(1).astype(int),
            "goal": Q // 4}


def readout(codes_tr, y_tr, codes_te, y_te, n, n_cls, epochs=5, seed=0):
    rng = np.random.default_rng(seed)
    W = np.zeros((n, n_cls), np.float32)
    for _ in range(epochs):
        for i in rng.permutation(len(codes_tr)):
            c, y = codes_tr[i], y_tr[i]
            p = int(W[c].sum(0).argmax())
            if p != y:
                W[c, y] += 1
                W[c, p] -= 1
    pred = np.array([int(W[c].sum(0).argmax()) for c in codes_te])
    acc = (pred == y_te).mean()
    bal = np.mean([np.mean(pred[y_te == k] == k) for k in np.unique(y_te)])
    return acc, bal


def evaluate(cortex, tr, te, name):
    ctr = [cortex(retina(f)) for f in tr[0]]
    cte = [cortex(retina(f)) for f in te[0]]
    Ttr, Tte = targets(tr[1], tr[2]), targets(te[1], te[2])
    parts = []
    for k in Ttr:
        maj = (Tte[k] == np.bincount(Ttr[k]).argmax()).mean()
        acc, bal = readout(ctr, Ttr[k], cte, Tte[k], cortex.n, int(max(Ttr[k].max(), Tte[k].max())) + 1)
        parts.append(f"{k} {acc * 100:4.1f}% (bal {bal * 100:4.1f}, maj {maj * 100:4.1f})")
    print(f"{name:<34}" + " | ".join(parts), flush=True)


if __name__ == "__main__":
    tr, te, nf = load()
    print(f"{nf} recordings: {len(tr[0])} training frames, {len(te[0])} test frames")
    evaluate(VisualCortex(seed=1), tr, te, "newborn cortex")
    c = VisualCortex(seed=1)
    watch_videos(c)
    evaluate(c, tr, te, "developed on MineRL videos")
    for f in tr[0]:
        c(retina(f), plasticity=True)
    evaluate(c, tr, te, "developed on MineRL + live frames")
    np.savez(os.path.join(HERE, "..", "data", "visual_cortex.npz"), syn=c.syn, cy=c.cy, cx=c.cx)
