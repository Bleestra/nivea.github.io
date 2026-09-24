"""
1. Development: the visual cortex watches MineRL Navigate videos (humans walking through
   Minecraft forests, mountains, villages) with structural plasticity switched on.
2. Mirror neurons: on CraftJarvis gameplay screenshots, a cerebellar readout learns to predict
   what the human did (dig / turn left / turn right / forward / wait) from the cortical code.
   Tested on held-out episodes. Compared: majority class, a newborn (random) cortex, the
   developed cortex.

    python3 vision_bench.py
"""
import glob
import os
import re
import sys
import time

import cv2
import numpy as np
import pyarrow.parquet as pq

from visual_cortex import VisualCortex, retina

HERE = os.path.dirname(os.path.abspath(__file__))
MC = os.path.join(HERE, "..", "data", "mc")
ACTIONS = ["forward", "turn left", "turn right", "dig", "wait"]


def action_class(text):
    m = re.search(r"move\((-?\d+),\s*(-?\d+)\)", text)
    dx = int(m.group(1)) if m else 0
    if "click(left)" in text:
        return 3
    if dx <= -5:
        return 1
    if dx >= 5:
        return 2
    if re.search(r"press\([^)]*\bw\b", text):
        return 0
    return 4


def craftjarvis(max_eps=None):
    eps = []
    for f in sorted(glob.glob(os.path.join(MC, "cj_shard*.parquet"))):
        for r in pq.read_table(f, columns=["conversations", "image_bytes"]).to_pylist():
            acts = [c["text"] for t in r["conversations"] if t["role"] == "assistant"
                    for c in t["content"] if c["type"] == "text"]
            imgs = r["image_bytes"]
            n = min(len(acts), len(imgs))
            if n:
                eps.append([(imgs[i], action_class(acts[i])) for i in range(n)])
    return eps[:max_eps]


def watch_videos(cortex, step=4, max_videos=None):
    files = sorted(glob.glob(os.path.join(MC, "minerl", "*", "*.mp4")))[:max_videos]
    frames = 0
    for f in files:
        cap = cv2.VideoCapture(f)
        i = 0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            if i % step == 0:
                cortex(retina(fr), plasticity=True)
                frames += 1
            i += 1
    return frames, len(files)


def mirror_test(cortex, eps, epochs=3, seed=0):
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(eps))
    cut = int(len(eps) * 0.8)
    tr = [x for e in order[:cut] for x in eps[e]]
    te = [x for e in order[cut:] for x in eps[e]]
    enc = lambda data: [(cortex(retina(cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR))), y) for b, y in data]
    tr, te = enc(tr), enc(te)
    W = np.zeros((cortex.n, 5), np.float32)
    for _ in range(epochs):  # cerebellar rule: correct output +, wrongly winning output -
        for i in rng.permutation(len(tr)):
            c, y = tr[i]
            p = int(W[c].sum(0).argmax())
            if p != y:
                W[c, y] += 1
                W[c, p] -= 1
    pred = np.array([int(W[c].sum(0).argmax()) for c, _ in te])
    ys = np.array([y for _, y in te])
    counts = np.bincount([y for _, y in tr], minlength=5)
    bal = np.mean([np.mean(pred[ys == k] == k) for k in range(5) if (ys == k).any()])
    return (pred == ys).mean(), bal, (ys == counts.argmax()).mean(), len(tr), len(te)


if __name__ == "__main__":
    t = time.time()
    eps = craftjarvis()
    print(f"CraftJarvis: {len(eps)} episodes, {sum(len(e) for e in eps)} screenshots with actions "
          f"({time.time() - t:.0f}s)", flush=True)
    newborn = VisualCortex(seed=1)
    acc, bal, maj, ntr, nte = mirror_test(newborn, eps)
    print(f"newborn cortex : accuracy {acc * 100:.1f}%  balanced {bal * 100:.1f}%  (majority class {maj * 100:.1f}%, "
          f"chance balanced 20%; train {ntr}, test {nte})", flush=True)
    adult = VisualCortex(seed=1)
    t = time.time()
    frames, vids = watch_videos(adult)
    print(f"development: watched {frames} frames from {vids} MineRL videos in {time.time() - t:.0f}s", flush=True)
    acc, bal, maj, _, _ = mirror_test(adult, eps)
    print(f"developed cortex: accuracy {acc * 100:.1f}%  balanced {bal * 100:.1f}%", flush=True)
    np.savez(os.path.join(HERE, "..", "data", "visual_cortex.npz"), syn=adult.syn, cy=adult.cy, cx=adult.cx)
