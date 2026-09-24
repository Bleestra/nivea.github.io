"""
Benchmarks for SynapseBrain. Hyper-parameters were picked on a validation split
(last 10k of the training set); everything below is measured on the untouched test set.

    python3 bench.py            # all experiments
"""
import os
import time

import numpy as np

from brain import (
    basal_ganglia, build_cortex, cerebellum_learn, encode_kwta, encode_thresh,
    hippocampus_learn, hippocampus_scores, homeostatic_theta, readout, retina,
    sleep_replay, stream_delta, stream_full, unit_hist,
)

HERE = os.path.dirname(os.path.abspath(__file__))
N_UNITS, K, RADIUS, K_ACTIVE, LEVELS = 20000, 10, 4, 1000, (64, 128, 192)
CEREB_EPOCHS, SLEEP_PER_CLASS, BG_W = 6, 1000, 0.5
TASKS = [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9)]
SEEDS = [0, 1, 2]


def load(name):
    path = os.path.join(HERE, "data", f"{name}.npz")
    if not os.path.exists(path):
        from sklearn.datasets import fetch_openml

        os.makedirs(os.path.dirname(path), exist_ok=True)
        oml = {"mnist": "mnist_784", "fashion": "Fashion-MNIST"}[name]
        X, y = fetch_openml(oml, version=1, return_X_y=True, as_frame=False, parser="liac-arff")
        np.savez_compressed(path, X=X.astype(np.uint8), y=y.astype(int))
    d = np.load(path)
    return d["X"][:60000], d["y"][:60000], d["X"][60000:], d["y"][60000:]


# ------------------------------------------------------------------ backprop baseline
class MLP:
    """784-1000-10 ReLU network, SGD + backprop, numpy/BLAS on all cores."""

    def __init__(self, seed):
        r = np.random.default_rng(seed)
        self.W1 = r.normal(0, np.sqrt(2 / 784), (784, 1000)).astype(np.float32)
        self.b1 = np.zeros(1000, np.float32)
        self.W2 = r.normal(0, np.sqrt(1 / 1000), (1000, 10)).astype(np.float32)
        self.b2 = np.zeros(10, np.float32)
        self.rng = r

    def fit(self, X, y, epochs=1, lr=0.05, bs=64):
        for _ in range(epochs):
            p = self.rng.permutation(len(X))
            for s in range(0, len(X), bs):
                i = p[s : s + bs]
                x, t = X[i], y[i]
                h = np.maximum(0, x @ self.W1 + self.b1)
                z = h @ self.W2 + self.b2
                z -= z.max(1, keepdims=True)
                pr = np.exp(z)
                pr /= pr.sum(1, keepdims=True)
                pr[np.arange(len(t)), t] -= 1
                g = pr / len(t)
                gh = (g @ self.W2.T) * (h > 0)
                self.W2 -= lr * h.T @ g
                self.b2 -= lr * g.sum(0)
                self.W1 -= lr * x.T @ gh
                self.b1 -= lr * gh.sum(0)

    def predict(self, X):
        return (np.maximum(0, X @ self.W1 + self.b1) @ self.W2 + self.b2).argmax(1)


def norm(X, mu):
    return X.astype(np.float32) / 255.0 - mu


def warmup():
    X = np.zeros((4, 784), np.uint8)
    X[:, 300:400] = 255
    p, i, nch = retina(X, LEVELS)
    _, ap, at = build_cortex(200, K, RADIUS, nch, 0)
    c = encode_kwta(p, i, ap, at, 200, K, 10)
    M = np.zeros((200, 10), np.float32)
    hippocampus_learn(c, np.zeros(4, np.int64), M)
    cerebellum_learn(c, np.zeros(4, np.int64), M, np.arange(4), 0.0)
    readout(c, M)
    sleep_replay(M + 1, np.array([0]), 2, 10, 1.0, 0)
    th = homeostatic_theta(unit_hist(p, i, ap, at, 200, K), 4, 0.05)
    encode_thresh(p, i, ap, at, th, 10)
    stream_full(p, i, ap, at, th, M)
    stream_delta(p, i, nch, ap, at, th, M)


# ------------------------------------------------------------------ experiment 1+2
def brain_run(Xtr, ytr, Xte, yte, seed):
    T = {}
    t = time.perf_counter()
    ptr, idx, nch = retina(Xtr, LEVELS)
    _, ap, at = build_cortex(N_UNITS, K, RADIUS, nch, seed)
    codes = encode_kwta(ptr, idx, ap, at, N_UNITS, K, K_ACTIVE)
    T["retina+cortex"] = time.perf_counter() - t

    t = time.perf_counter()
    Hm = np.zeros((N_UNITS, 10), np.float32)
    hippocampus_learn(codes, ytr, Hm)
    T["hippocampus"] = time.perf_counter() - t

    t = time.perf_counter()
    Wc = np.zeros((N_UNITS, 10), np.float32)
    rng = np.random.default_rng(seed)
    for _ in range(CEREB_EPOCHS):
        cerebellum_learn(codes, ytr, Wc, rng.permutation(len(ytr)), 0.0)
    T["cerebellum"] = time.perf_counter() - t

    t = time.perf_counter()
    tp, ti, _ = retina(Xte, LEVELS)
    ct = encode_kwta(tp, ti, ap, at, N_UNITS, K, K_ACTIVE)
    Sh, Sc = hippocampus_scores(ct, Hm), readout(ct, Wc)
    pred = basal_ganglia([Sh, Sc], [BG_W, 1])
    T["test inference"] = time.perf_counter() - t
    acc = {
        "hippocampus": (Sh.argmax(1) == yte).mean() * 100,
        "cerebellum": (Sc.argmax(1) == yte).mean() * 100,
        "brain (BG)": (pred == yte).mean() * 100,
    }

    # class-incremental: tasks arrive one after another, never revisited
    Hm = np.zeros((N_UNITS, 10), np.float32)
    Wn = np.zeros((N_UNITS, 10), np.float32)  # cerebellum without sleep
    Ws = np.zeros((N_UNITS, 10), np.float32)  # cerebellum with sleep
    seen = []
    t = time.perf_counter()
    for task in TASKS:
        m = np.isin(ytr, task)
        seen += list(task)
        hippocampus_learn(codes[m], ytr[m], Hm)
        cerebellum_learn(codes[m], ytr[m], Wn, rng.permutation(m.sum()), 0.0)
        cerebellum_learn(codes[m], ytr[m], Ws, rng.permutation(m.sum()), 0.0)
        rc, ry = sleep_replay(Hm, np.array(seen), SLEEP_PER_CLASS, K_ACTIVE, 1.0, seed * 100 + len(seen))
        cerebellum_learn(rc, ry, Ws, rng.permutation(len(ry)), 0.0)
    T["class-incremental learning"] = time.perf_counter() - t
    Sh, Sn, Ss = hippocampus_scores(ct, Hm), readout(ct, Wn), readout(ct, Ws)
    ci = {
        "hippocampus": (Sh.argmax(1) == yte).mean() * 100,
        "cerebellum, no sleep": (Sn.argmax(1) == yte).mean() * 100,
        "cerebellum + sleep": (Ss.argmax(1) == yte).mean() * 100,
        "brain (BG)": (basal_ganglia([Sh, Ss], [BG_W, 1]) == yte).mean() * 100,
    }
    return acc, ci, T


def mlp_run(Xtr, ytr, Xte, yte, seed):
    mu = (Xtr / 255.0).mean(0).astype(np.float32)
    A, B = norm(Xtr, mu), norm(Xte, mu)
    T, acc = {}, {}
    m = MLP(seed)
    spent = 0.0
    for ep in range(1, 11):
        t = time.perf_counter()
        m.fit(A, ytr, 1)
        spent += time.perf_counter() - t
        T[f"{ep} epochs"] = spent
        acc[f"{ep} epochs"] = (m.predict(B) == yte).mean() * 100
    m = MLP(seed)
    for task in TASKS:
        msk = np.isin(ytr, task)
        m.fit(A[msk], ytr[msk], 1)
    acc["class-incremental"] = (m.predict(B) == yte).mean() * 100
    return acc, T


def ms(vals):
    v = np.array(vals)
    return f"{v.mean():5.1f} ± {v.std():.1f}"


def exp_accuracy(name):
    Xtr, ytr, Xte, yte = load(name)
    B, BT, M, MT = [], [], [], []
    for s in SEEDS:
        a, ci, t = brain_run(Xtr, ytr, Xte, yte, s)
        B.append((a, ci))
        BT.append(t)
        a, t = mlp_run(Xtr, ytr, Xte, yte, s)
        M.append(a)
        MT.append(t)
    print(f"\n## {name}: test accuracy, mean ± std over {len(SEEDS)} seeds")
    print("Ordinary (shuffled) training:")
    for key in B[0][0]:
        print(f"  SynapseBrain {key:<22}{ms([b[0][key] for b in B])} %")
    for ep in [1, 2, 3, 5, 10]:
        key = f"{ep} epochs"
        print(f"  Backprop MLP {key:<22}{ms([m[key] for m in M])} %   "
              f"{np.mean([t[key] for t in MT]):5.2f} s")
    print("Class-incremental (0/1 -> 2/3 -> ... -> 8/9, each task seen once):")
    for key in B[0][1]:
        print(f"  SynapseBrain {key:<22}{ms([b[1][key] for b in B])} %")
    print(f"  Backprop MLP {'1 epoch per task':<22}{ms([m['class-incremental'] for m in M])} %")
    print("Wall-clock, seconds (60k training images, 4 CPU cores):")
    for key in BT[0]:
        print(f"  SynapseBrain {key:<28}{np.mean([t[key] for t in BT]):6.2f}")
    tot = np.mean([t["retina+cortex"] + t["hippocampus"] + t["cerebellum"] for t in BT])
    print(f"  SynapseBrain {'TOTAL training':<28}{tot:6.2f}")
    target = np.mean([b[0]["brain (BG)"] for b in B])
    hit = [ep for ep in range(1, 11) if np.mean([m[f"{ep} epochs"] for m in M]) >= target]
    if hit:
        tm = np.mean([t[f"{hit[0]} epochs"] for t in MT])
        print(f"  Backprop MLP needs {hit[0]} epochs = {tm:.2f} s to reach SynapseBrain's "
              f"{target:.1f}% -> SynapseBrain is {tm / tot:.1f}x faster to the same accuracy")
    else:
        print(f"  Backprop MLP does not reach SynapseBrain's {target:.1f}% within 10 epochs")


# ------------------------------------------------------------------ experiment 3
def exp_speed():
    """Same cortex (same synapses, same answer), three ways of computing it."""
    Xtr, _, _, _ = load("mnist")
    X = Xtr[:10000]
    ptr, idx, nch = retina(X, LEVELS)
    dend, ap, at = build_cortex(N_UNITS, K, RADIUS, nch, 0)
    E = np.zeros((len(X), nch), np.float32)
    for i in range(len(X)):
        E[i, idx[ptr[i] : ptr[i + 1]]] = 1
    Md = np.zeros((nch, N_UNITS), np.float32)
    np.add.at(Md, (dend.ravel(), np.repeat(np.arange(N_UNITS), K)), 1)

    print("\n## Speed: one cortex, three implementations (10k MNIST images)")
    print(f"  spikes per image: {len(idx) / len(X):.0f} of {nch} channels "
          f"({len(idx) / len(X) / nch * 100:.1f}%), synapses: {N_UNITS * K:,}")

    t = time.perf_counter()
    for s in range(0, len(X), 500):
        drive = E[s : s + 500][:, dend].sum(-1)
        np.argpartition(-drive, K_ACTIVE, axis=1)[:, :K_ACTIVE]
    t_gather = time.perf_counter() - t

    t = time.perf_counter()
    D = E @ Md
    t_mm = time.perf_counter() - t
    t = time.perf_counter()
    np.argpartition(-D, K_ACTIVE, axis=1)[:, :K_ACTIVE]
    t_sel = time.perf_counter() - t

    t = time.perf_counter()
    codes = encode_kwta(ptr, idx, ap, at, N_UNITS, K, K_ACTIVE)
    t_ev = time.perf_counter() - t

    # exactness: the event-driven winners are exactly a top-k set of the dense drive
    ok = 0
    for i in range(1000):
        d = D[i]
        kth = np.sort(d)[-K_ACTIVE]
        c = codes[i][codes[i] >= 0]
        ok += len(c) == K_ACTIVE and d[c].min() >= kth and (d > kth).sum() <= K_ACTIVE
    ev_ops = len(idx) / len(X) * (N_UNITS * K / nch) + 2 * N_UNITS
    print(f"  naive gather (numpy, like the fly demo) : {t_gather:6.2f} s")
    print(f"  dense GPU-style matmul (BLAS) + top-k   : {t_mm + t_sel:6.2f} s "
          f"(matmul {t_mm:.2f} + select {t_sel:.2f})")
    print(f"  event-driven synapses (this project)    : {t_ev:6.2f} s")
    print(f"  -> {t_gather / t_ev:.0f}x faster than gather, {(t_mm + t_sel) / t_ev:.0f}x faster than dense, "
          f"{t_mm / t_ev:.0f}x faster than the matmul alone")
    print(f"  work per image: dense {nch * N_UNITS / 1e6:.0f}M MACs vs event-driven ~{ev_ops / 1e3:.0f}k adds")
    print(f"  exactness check: {ok}/1000 images give an exact top-k of the dense result")


# ------------------------------------------------------------------ experiment 4
def make_stream(X, n_scenes, frames, mode, rng):
    out = []
    for s in range(n_scenes):
        img = X[s].reshape(28, 28)
        oy = ox = 0
        for f in range(frames):
            if mode == "still camera, 1% sensor noise":
                fr = img.copy()
                flip = rng.random((28, 28)) < 0.01
                fr[flip] = 255 - fr[flip]
            else:  # "moving object": random walk of 1 px every frame
                oy = int(np.clip(oy + rng.integers(-1, 2), -3, 3))
                ox = int(np.clip(ox + rng.integers(-1, 2), -3, 3))
                fr = np.roll(np.roll(img, oy, 0), ox, 1)
            out.append(fr.ravel())
    return np.array(out, np.uint8)


def exp_stream():
    Xtr, ytr, Xte, yte = load("mnist")
    ptr, idx, nch = retina(Xtr, LEVELS)
    _, ap, at = build_cortex(N_UNITS, K, RADIUS, nch, 0)
    theta = homeostatic_theta(
        unit_hist(ptr[:20001], idx, ap, at, N_UNITS, K), 20000, K_ACTIVE / N_UNITS)
    codes = encode_thresh(ptr, idx, ap, at, theta, 4 * K_ACTIVE)
    Wc = np.zeros((N_UNITS, 10), np.float32)
    rng = np.random.default_rng(0)
    for _ in range(CEREB_EPOCHS):
        cerebellum_learn(codes, ytr, Wc, rng.permutation(len(ytr)), 0.0)

    print("\n## Thalamic delta coding on video streams (300 scenes x 30 frames)")
    for mode in ["still camera, 1% sensor noise", "moving object"]:
        F = make_stream(Xte, 300, 30, mode, np.random.default_rng(1))
        labels = np.repeat(yte[:300], 30)
        fp, fi, _ = retina(F, LEVELS)
        t = time.perf_counter()
        S1, ops1 = stream_full(fp, fi, ap, at, theta, Wc)
        t1 = time.perf_counter() - t
        t = time.perf_counter()
        S2, ops2 = stream_delta(fp, fi, nch, ap, at, theta, Wc)
        t2 = time.perf_counter() - t
        same = (S1.argmax(1) == S2.argmax(1)).mean() * 100
        err = np.abs(S1 - S2).max() / (np.abs(S1).max() + 1e-9)
        acc = (S2.argmax(1) == labels).mean() * 100
        print(f"  {mode}:")
        print(f"    full recompute {t1 * 1e3:7.1f} ms, {ops1 / len(F) / 1e3:6.1f}k ops/frame")
        print(f"    delta coding   {t2 * 1e3:7.1f} ms, {ops2 / len(F) / 1e3:6.1f}k ops/frame"
              f"  -> {ops1 / ops2:.1f}x fewer ops ({t1 / t2:.1f}x wall-clock)")
        print(f"    identical decisions: {same:.1f}% of frames, max rel. score diff {err:.1e},"
              f" frame accuracy {acc:.1f}%")


if __name__ == "__main__":
    warmup()
    import numba

    print(f"CPU threads: {numba.get_num_threads()}  |  cortex: {N_UNITS} units x {K} synapses, "
          f"{K_ACTIVE} active ({K_ACTIVE / N_UNITS * 100:.0f}%)")
    exp_accuracy("mnist")
    exp_accuracy("fashion")
    exp_speed()
    exp_stream()
