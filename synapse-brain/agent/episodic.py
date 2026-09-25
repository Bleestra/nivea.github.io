"""
Episodic memory: every moment lived, and the ones most like now.

The hippocampus keeps episodes, not rules: here I was, this I did, this came of it. Every moment of life is
kept (on disk, for as long as the project's budget has room) and each new moment is compared with all of
them: the most similar come back - "I have been in a situation like this; then I did that, and then ...".
From them the mind reads two things, nothing more:
  what came of each action   the reward that followed it in the similar moments (episodic control: one
                             good experience is used at once, not after a thousand repetitions);
  what led to what I want    after which actions, in moments like this, the thing I want now happened.
What to do is still the mind's choice; memory only says what happened before.

A moment is recognised by its fingerprint: the concepts true in it and the cells of the senses, each thrown
onto a fixed random direction and summed - moments that share much get close fingerprints. The search is
FAISS (an inverted index over the whole life: about a millisecond for millions of moments), grown in the
background as life gets longer; without faiss, an exact search over the last moments.

On disk (append-only, nothing is rewritten): keys.f16 (fingerprints), act.i16, rew.f16, done.u8,
evn.i32 + evs.i32 (what happened after each moment), index.faiss.
"""
import json
import os
import threading

import numpy as np

try:
    import faiss
except ImportError:                  # pip install faiss-cpu
    faiss = None

DIM = 128
HALF = DIM // 2
_A = np.random.default_rng(12345).integers(1, 2 ** 62, size=(2, HALF), dtype=np.uint64) | np.uint64(1)
_B = np.random.default_rng(54321).integers(0, 2 ** 62, size=(2, HALF), dtype=np.uint64)
FILES = {"act": np.int16, "rew": np.float16, "done": np.uint8, "evn": np.int32, "evs": np.int32}


def _throw(ids, part):
    """Each id onto its own fixed random +-1 direction; the sum, normalised."""
    if len(ids) == 0:
        return np.zeros(HALF, np.float32)
    x = np.asarray(ids).astype(np.uint64)[:, None] * _A[part] + _B[part]
    x ^= x >> np.uint64(31)
    x *= np.uint64(0xBF58476D1CE4E5B9)
    s = (x >> np.uint64(63)).astype(np.float32).sum(0) * 2 - len(ids)
    return s / (np.linalg.norm(s) + 1e-6)


class _Vec:
    """An array that grows at its end."""

    def __init__(self, dtype, data=None):
        data = np.zeros(0, dtype) if data is None else np.asarray(data, dtype)
        self.a = np.zeros(max(1024, 2 * len(data)), dtype)
        self.a[:len(data)] = data
        self.n = len(data)

    def add(self, x):
        x = np.atleast_1d(np.asarray(x, self.a.dtype))
        while self.n + len(x) > len(self.a):
            self.a = np.concatenate([self.a, np.zeros(len(self.a), self.a.dtype)])
        self.a[self.n:self.n + len(x)] = x
        self.n += len(x)

    @property
    def v(self):
        return self.a[:self.n]


class Recalled:
    """The moments most like now: who they are, how alike, what I did, what followed."""

    def __init__(self, sims, act, ret, events):
        self.w = np.clip(sims, 0.0, 1.0) ** 4                 # the closer, the more it counts
        self.act, self.ret, self.events = act, ret, events

    def _per_action(self, x, nA):
        num, den = np.zeros(nA, np.float32), np.zeros(nA, np.float32)
        np.add.at(num, self.act, self.w * x)
        np.add.at(den, self.act, self.w)
        return num / (den + 1.0)                               # little evidence -> close to nothing

    def worth(self, nA):
        """What came of each action in moments like this (the reward that followed)."""
        return self._per_action(self.ret, nA)

    def toward(self, g, nA):
        """How often each action was followed by g, in moments like this."""
        hit = np.array([g in e for e in self.events], np.float32)
        return self._per_action(hit, nA)


class Episodic:
    def __init__(self, path, room=None, k=32, horizon=40, gamma=0.95):
        self.path, self.room = path, room
        self.k, self.H, self.gamma = k, horizon, gamma
        os.makedirs(path, exist_ok=True)
        self.index, self.trained_at = None, 0
        self._build, self._built = None, None
        self.pending = []                                      # fingerprints not yet on disk
        self.full = False
        self._load()

    def _f(self, name):
        return os.path.join(self.path, name)

    # ---------------------------------------------------------------- a moment
    @staticmethod
    def key(concepts, cells):
        return np.concatenate([_throw(concepts, 0), _throw(cells, 1)]) / np.sqrt(2)

    def add(self, key, a, r, events, done):
        """The moment that just passed: where I was (key), what I did, what I felt, what happened."""
        if self.full:
            return
        self.pending.append(key.astype(np.float16))
        self.act.add(a)
        self.rew.add(r)
        self.done.add(bool(done))
        ev = np.asarray(list(events), np.int32)
        self.evn.add(len(ev))
        self.evs.add(ev)
        self.evp.add(self.evp.v[-1] + len(ev))
        self._index_add(key[None].astype(np.float32))

    @property
    def n(self):
        return self.act.n

    # ---------------------------------------------------------------- remembering
    def recall(self, key):
        self._swap()
        if self.index is None or self.index.ntotal == 0:
            return None
        sims, ids = self.index.search(key[None].astype(np.float32), self.k)
        n, H = self.n, self.H
        ok = (ids[0] >= 0) & (ids[0] < n - H)                  # only moments whose sequel is known
        ids, sims = ids[0][ok], sims[0][ok]
        if len(ids) == 0:
            return None
        idx = ids[:, None] + np.arange(H)[None, :]
        d = self.done.v[idx].astype(bool)
        alive = (np.cumsum(d, 1) - d) == 0                     # up to and including a death, not after
        ret = (self.rew.v[idx].astype(np.float32) * alive * self.gamma ** np.arange(H)).sum(1)
        span = alive.sum(1)
        evp, evs = self.evp.v, self.evs.v
        events = [evs[evp[i]:evp[i + s]] for i, s in zip(ids, span)]
        return Recalled(sims, self.act.v[ids].astype(np.int64), ret, events)

    # ---------------------------------------------------------------- the index
    def _index_add(self, x):
        if faiss is None:
            if self.index is None:
                self.index = _Exact()
            self.index.add(x)
            return
        if self.index is None:
            self.index = faiss.IndexFlatIP(DIM)
        self.index.add(x)
        if self._build is None and self.n >= 4096 and self.n >= 8 * max(self.trained_at, 512):
            self._rebuild()

    def _rebuild(self):
        """Life got 8x longer than the index was made for: make a bigger one in the background."""
        self.flush()
        N0 = self.n
        nlist = int(2 ** np.floor(np.log2(max(64, min(4 * np.sqrt(N0), N0 / 40)))))   # >= 40 moments per cluster
        path = self._f("keys.f16")

        def chunks(step=262144):                                # read the fingerprints piece by piece
            for s in range(0, N0, step):
                m = min(N0, s + step) - s
                yield s, np.fromfile(path, np.float16, m * DIM, offset=s * DIM * 2).reshape(m, DIM).astype(np.float32)

        def work():
            try:
                rows = np.sort(np.random.default_rng(N0).choice(N0, min(N0, 64 * nlist), replace=False))
                sample = np.concatenate([x[rows[(rows >= s) & (rows < s + len(x))] - s] for s, x in chunks()])
                ix = faiss.IndexIVFScalarQuantizer(faiss.IndexFlatIP(DIM), DIM, nlist, faiss.ScalarQuantizer.QT_8bit,
                                                   faiss.METRIC_INNER_PRODUCT)
                ix.train(sample)
                for _, x in chunks():
                    ix.add(x)
                ix.nprobe = max(8, nlist // 32)
                self._built = (ix, N0)
            except Exception as e:
                print("episodic memory index:", e, flush=True)
                self._built = (None, N0)
        self._build = threading.Thread(target=work, daemon=True)
        self._build.start()

    def _swap(self):
        if self._built is None:
            return
        ix, N0 = self._built
        self._built, self._build = None, None
        if ix is None:
            self.trained_at = N0                               # failed: try again when life is 8x longer
            return
        if self.n > N0:
            ix.add(self._keys(N0, self.n))
        self.index, self.trained_at = ix, N0

    def _keys(self, a, b):
        on_disk = self.n - len(self.pending)
        out = []
        if a < on_disk:
            out.append(np.fromfile(self._f("keys.f16"), np.float16, (min(b, on_disk) - a) * DIM,
                                   offset=a * DIM * 2).reshape(-1, DIM))
        if b > on_disk:
            out.append(np.array(self.pending[max(0, a - on_disk):b - on_disk]))
        return np.concatenate(out).astype(np.float32)

    # ---------------------------------------------------------------- disk
    def flush(self):
        """Append what is new to the files (nothing is rewritten)."""
        if not self.pending:
            return
        a = self.n - len(self.pending)
        with open(self._f("keys.f16"), "ab") as f:
            f.write(np.array(self.pending, np.float16).tobytes())
        for name in FILES:
            v = getattr(self, name).v
            start = a if name != "evs" else int(self.evp.v[a])
            with open(self._f(name + ".bin"), "ab") as f:
                f.write(v[start:].tobytes())
        self.pending = []

    def save(self):
        self.flush()
        if self.room is not None:                              # the project's disk budget
            self.full = self.room() < 2 ** 30
        if faiss is not None and self.index is not None and self._build is None:
            faiss.write_index(self.index, self._f("index.tmp"))
            os.replace(self._f("index.tmp"), self._f("index.faiss"))
            with open(self._f("index.json"), "w") as f:
                json.dump({"rows": int(self.index.ntotal), "trained_at": self.trained_at}, f)

    def _load(self):
        rows = os.path.getsize(self._f("keys.f16")) // (DIM * 2) if os.path.exists(self._f("keys.f16")) else 0
        data = {k: np.fromfile(self._f(k + ".bin"), t) if os.path.exists(self._f(k + ".bin")) else np.zeros(0, t)
                for k, t in FILES.items()}
        n = min(rows, *(len(data[k]) for k in ("act", "rew", "done", "evn")))
        ne = int(data["evn"][:n].sum())
        if len(data["evs"]) < ne:                               # a save was cut short: keep the whole moments
            n = int(np.searchsorted(np.cumsum(data["evn"][:n]), len(data["evs"]), "right"))
            ne = int(data["evn"][:n].sum())
        for k, t in FILES.items():                             # files longer than the whole moments: cut
            keep = ne if k == "evs" else n
            if len(data[k]) > keep:
                with open(self._f(k + ".bin"), "r+b") as f:
                    f.truncate(keep * np.dtype(t).itemsize)
            setattr(self, k, _Vec(t, data[k][:keep]))
        if rows > n:
            with open(self._f("keys.f16"), "r+b") as f:
                f.truncate(n * DIM * 2)
        self.evp = _Vec(np.int64, np.concatenate([[0], np.cumsum(self.evn.v, dtype=np.int64)]))
        if n == 0:
            return
        if faiss is None:
            self.index = _Exact()
            self.index.add(self._keys(max(0, n - _Exact.MOST), n))
            return
        meta = json.load(open(self._f("index.json"))) if os.path.exists(self._f("index.json")) else {}
        if os.path.exists(self._f("index.faiss")) and meta.get("rows", n + 1) <= n:
            self.index, self.trained_at = faiss.read_index(self._f("index.faiss")), meta.get("trained_at", 0)
            if self.index.ntotal < n:
                self.index.add(self._keys(self.index.ntotal, n))
        elif n < 4096:
            self.index = faiss.IndexFlatIP(DIM)
            self.index.add(self._keys(0, n))
        else:
            self._rebuild()                                    # the index was lost: make it again (background)

    def status(self):
        return {"moments": self.n, "indexed": 0 if self.index is None else int(self.index.ntotal),
                "full": self.full}


class _Exact:
    """Without faiss: an exact search over the last MOST moments."""
    MOST = 200000

    def __init__(self):
        self.x, self.ntotal, self.first = np.zeros((0, DIM), np.float32), 0, 0

    def add(self, x):
        self.x = np.concatenate([self.x, x.astype(np.float32)])[-self.MOST:]
        self.ntotal += len(x)
        self.first = self.ntotal - len(self.x)

    def search(self, q, k):
        s = self.x @ q[0]
        top = np.argsort(-s)[:k]
        return s[top][None], (top + self.first)[None]
