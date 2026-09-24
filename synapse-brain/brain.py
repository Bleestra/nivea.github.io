"""
SynapseBrain: a brain built as a set of "microservices" that talk only through spikes.

    retina  ->  cortex (V1 + granule-cell expansion)  ->  hippocampus  (one-shot memory)
                                                      ->  cerebellum   (error-corrected readout)
                                                      ->  basal ganglia (arbitration / choice)
    thalamus: the event bus. Only spikes travel, and in a video stream only *changes* travel.

Speed tricks (the point of the project):
  1. Axonal lists: synapses are stored per presynaptic neuron, so a spike pushes into its
     targets (scatter). Work = spikes x fan-out, not neurons x synapses.
  2. Integer dendrites + histogram inhibition: dendritic sums are small integers (0..K), so
     they fit in uint8 (the whole cortex sits in L1 cache) and k-winners-take-all is one
     counting pass, no sorting.
  3. Sparse readout: only the ~k active units are read or updated in memory/readout.
  4. Delta coding (thalamus): in a stream only changed input spikes are propagated; units
     that cross their threshold emit on/off events; the readout is updated incrementally.
"""
import numpy as np
from numba import njit, prange

SIDE = 28
NPIX = SIDE * SIDE


# ------------------------------------------------------------------ retina
@njit(cache=True)
def _retina_img(img, levels, out):
    """Spikes of one image. ON cells: pixel brighter than each level. OFF-surround cells:
    dark pixel next to a bright one (contour detectors, like retinal OFF cells)."""
    L = len(levels)
    pos = 0
    for m in range(L):
        for p in range(NPIX):
            if img[p] > levels[m]:
                out[pos] = m * NPIX + p
                pos += 1
    for yy in range(SIDE):
        for xx in range(SIDE):
            p = yy * SIDE + xx
            if img[p] > 127:
                continue
            lit = False
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    y2 = yy + dy
                    x2 = xx + dx
                    if 0 <= y2 < SIDE and 0 <= x2 < SIDE and img[y2 * SIDE + x2] > 127:
                        lit = True
            if lit:
                out[pos] = L * NPIX + p
                pos += 1
    return pos


@njit(parallel=True, cache=True)
def _retina(X, levels):
    n = X.shape[0]
    buf = np.empty((n, (len(levels) + 1) * NPIX), np.int32)
    cnt = np.empty(n, np.int64)
    for i in prange(n):
        cnt[i] = _retina_img(X[i], levels, buf[i])
    ptr = np.zeros(n + 1, np.int64)
    for i in range(n):
        ptr[i + 1] = ptr[i] + cnt[i]
    idx = np.empty(ptr[n], np.int32)
    for i in prange(n):
        idx[ptr[i] : ptr[i + 1]] = buf[i, : cnt[i]]
    return ptr, idx


def retina(X, levels=(127,)):
    """uint8 images (n, 784) -> CSR spike lists over (len(levels)+1)*784 channels."""
    lv = np.asarray(levels, np.int32)
    ptr, idx = _retina(np.ascontiguousarray(X, dtype=np.uint8), lv)
    return ptr, idx, (len(lv) + 1) * NPIX


# ------------------------------------------------------------------ cortex wiring
def build_cortex(n_units, K, radius, n_ch, seed=0):
    """Retinotopic random wiring: every unit gets K synapses from a local patch
    (radius) of randomly chosen retinal channels. Returns dendrite table and axon CSR."""
    rng = np.random.default_rng(seed)
    n_maps = n_ch // NPIX
    cy = rng.integers(radius, SIDE - radius, n_units)
    cx = rng.integers(radius, SIDE - radius, n_units)
    dy = rng.integers(-radius, radius + 1, (n_units, K))
    dx = rng.integers(-radius, radius + 1, (n_units, K))
    ch = rng.integers(0, n_maps, (n_units, K))
    dend = (ch * NPIX + (cy[:, None] + dy) * SIDE + (cx[:, None] + dx)).astype(np.int32)
    flat = dend.ravel()
    order = np.argsort(flat, kind="stable")
    ax_tgt = (np.arange(flat.size) // K)[order].astype(np.int32)
    ax_ptr = np.zeros(n_ch + 1, np.int64)
    np.cumsum(np.bincount(flat, minlength=n_ch), out=ax_ptr[1:])
    return dend, ax_ptr, ax_tgt


# ------------------------------------------------------------------ cortex dynamics
@njit(cache=True)
def _integrate(i, ev_ptr, ev_idx, ax_ptr, ax_tgt, acc, touched):
    nt = 0
    for e in range(ev_ptr[i], ev_ptr[i + 1]):
        c = ev_idx[e]
        for s in range(ax_ptr[c], ax_ptr[c + 1]):
            u = ax_tgt[s]
            if acc[u] == 0:
                touched[nt] = u
                nt += 1
            acc[u] += 1
    return nt


@njit(parallel=True, cache=True)
def encode_kwta(ev_ptr, ev_idx, ax_ptr, ax_tgt, n_units, K, k):
    """Event-driven cortex with global inhibition: the k most driven units spike.
    Dendrites are uint8 (drive <= K), so 20k units fit in L1 cache and the hot loop is a
    branch-free scatter. Inhibition is a histogram pass (no sort); ties go to lower ids,
    which is unbiased because the wiring is random."""
    n = len(ev_ptr) - 1
    out = np.full((n, k), -1, np.int32)
    nblk = 256
    for b in prange(nblk):
        acc = np.zeros(n_units, np.uint8)
        hist = np.zeros(K + 2, np.int32)
        for i in range(b * n // nblk, (b + 1) * n // nblk):
            for e in range(ev_ptr[i], ev_ptr[i + 1]):
                c = ev_idx[e]
                for s in range(ax_ptr[c], ax_ptr[c + 1]):
                    acc[ax_tgt[s]] += 1
            hist[:] = 0
            for u in range(n_units):
                hist[acc[u]] += 1
            taken = 0
            tie = 0
            need = 0
            for v in range(K, 0, -1):
                if taken + hist[v] <= k:
                    taken += hist[v]
                else:
                    tie = v
                    need = k - taken
                    break
            pos = 0
            for u in range(n_units):
                a = acc[u]
                if a > tie or (a == tie and need > 0 and tie > 0):
                    if a == tie:
                        need -= 1
                    out[i, pos] = u
                    pos += 1
            acc[:] = 0
    return out


@njit(parallel=True, cache=True)
def encode_thresh(ev_ptr, ev_idx, ax_ptr, ax_tgt, theta, kmax):
    """Event-driven cortex with per-unit (homeostatic) firing thresholds."""
    n = len(ev_ptr) - 1
    n_units = len(theta)
    out = np.full((n, kmax), -1, np.int32)
    nblk = 256
    for b in prange(nblk):
        acc = np.zeros(n_units, np.int32)
        touched = np.empty(n_units, np.int32)
        for i in range(b * n // nblk, (b + 1) * n // nblk):
            nt = _integrate(i, ev_ptr, ev_idx, ax_ptr, ax_tgt, acc, touched)
            pos = 0
            for j in range(nt):
                u = touched[j]
                if acc[u] >= theta[u] and pos < kmax:
                    out[i, pos] = u
                    pos += 1
                acc[u] = 0
    return out


@njit(parallel=True, cache=True)
def unit_hist(ev_ptr, ev_idx, ax_ptr, ax_tgt, n_units, K):
    """Distribution of dendritic drive per unit, used to set homeostatic thresholds."""
    n = len(ev_ptr) - 1
    nblk = 4
    H = np.zeros((nblk, n_units, K + 1), np.int64)
    for b in prange(nblk):
        acc = np.zeros(n_units, np.int32)
        touched = np.empty(n_units, np.int32)
        for i in range(b * n // nblk, (b + 1) * n // nblk):
            nt = _integrate(i, ev_ptr, ev_idx, ax_ptr, ax_tgt, acc, touched)
            for j in range(nt):
                u = touched[j]
                H[b, u, acc[u]] += 1
                acc[u] = 0
    return H.sum(0)


def homeostatic_theta(hist, n_samples, rate):
    """Intrinsic plasticity: each unit picks the lowest threshold at which it fires on
    at most `rate` of inputs (units never touched count as drive 0)."""
    h = hist.copy()
    h[:, 0] = n_samples - h[:, 1:].sum(1)
    tail = np.cumsum(h[:, ::-1], 1)[:, ::-1] / n_samples  # P(drive >= v)
    ok = tail <= rate
    ok[:, 0] = False
    theta = np.where(ok.any(1), ok.argmax(1), hist.shape[1])
    return theta.astype(np.int32)


# ------------------------------------------------------------------ memory / readout services
@njit(cache=True)
def hippocampus_learn(codes, y, Hm):
    """One-shot Hebbian memory: active unit -> presented class, +1. Never overwrites."""
    for i in range(codes.shape[0]):
        for j in range(codes.shape[1]):
            u = codes[i, j]
            if u < 0:
                break
            Hm[u, y[i]] += 1.0


@njit(cache=True)
def cerebellum_learn(codes, y, Wc, order, margin):
    """Purkinje-cell rule: climbing-fibre error signal adjusts only the active synapses
    of the correct output (+) and the wrongly winning output (-)."""
    C = Wc.shape[1]
    s = np.zeros(C, np.float32)
    mistakes = 0
    for ii in range(len(order)):
        i = order[ii]
        s[:] = 0.0
        for j in range(codes.shape[1]):
            u = codes[i, j]
            if u < 0:
                break
            for c in range(C):
                s[c] += Wc[u, c]
        t = y[i]
        best = -1
        bv = -1e30
        for c in range(C):
            if c != t and s[c] > bv:
                bv = s[c]
                best = c
        if s[t] - bv <= margin:
            mistakes += 1
            for j in range(codes.shape[1]):
                u = codes[i, j]
                if u < 0:
                    break
                Wc[u, t] += 1.0
                Wc[u, best] -= 1.0
    return mistakes


@njit(parallel=True, cache=True)
def readout(codes, M):
    """Sparse readout: sum the rows of M for active units only."""
    n = codes.shape[0]
    C = M.shape[1]
    S = np.zeros((n, C), np.float32)
    for i in prange(n):
        for j in range(codes.shape[1]):
            u = codes[i, j]
            if u < 0:
                break
            for c in range(C):
                S[i, c] += M[u, c]
    return S


@njit(cache=True)
def sleep_replay(Hm, classes, n_per_class, k, gamma, seed):
    """'Sleep': the hippocampus dreams sparse codes for each stored class
    (units drawn with probability ~ memory strength^gamma)."""
    np.random.seed(seed)
    n_units = Hm.shape[0]
    codes = np.full((len(classes) * n_per_class, k), -1, np.int32)
    ys = np.empty(len(classes) * n_per_class, np.int64)
    mark = np.zeros(n_units, np.int32)
    r = 0
    for ci in range(len(classes)):
        c = classes[ci]
        p = np.empty(n_units)
        tot = 0.0
        for u in range(n_units):
            p[u] = Hm[u, c] ** gamma
            tot += p[u]
        cdf = np.cumsum(p / tot)
        for _ in range(n_per_class):
            pos = 0
            tries = 0
            while pos < k and tries < 4 * k:
                u = np.searchsorted(cdf, np.random.random())
                if u >= n_units:
                    u = n_units - 1
                tries += 1
                if mark[u] != r + 1:
                    mark[u] = r + 1
                    codes[r, pos] = u
                    pos += 1
            ys[r] = c
            r += 1
    return codes, ys


def basal_ganglia(scores, weights):
    """Arbitration: each service's votes are standardised per input, then weighted."""
    tot = 0
    for S, w in zip(scores, weights):
        mu = S.mean(1, keepdims=True)
        sd = S.std(1, keepdims=True) + 1e-9
        tot = tot + w * (S - mu) / sd
    return tot.argmax(1)


def hippocampus_scores(codes, Hm):
    return readout(codes, Hm / (np.linalg.norm(Hm, axis=0, keepdims=True) + 1e-9))


# ------------------------------------------------------------------ thalamus: delta streaming
@njit(cache=True)
def stream_full(frames_ptr, frames_idx, ax_ptr, ax_tgt, theta, M):
    """Baseline: recompute everything for every video frame."""
    n_units = len(theta)
    C = M.shape[1]
    T = len(frames_ptr) - 1
    acc = np.zeros(n_units, np.int32)
    touched = np.empty(n_units, np.int32)
    S = np.zeros((T, C), np.float32)
    ops = 0
    for t in range(T):
        nt = _integrate(t, frames_ptr, frames_idx, ax_ptr, ax_tgt, acc, touched)
        for e in range(frames_ptr[t], frames_ptr[t + 1]):
            c = frames_idx[e]
            ops += ax_ptr[c + 1] - ax_ptr[c]
        ops += nt  # threshold test + reset of every touched unit
        for j in range(nt):
            u = touched[j]
            if acc[u] >= theta[u]:
                for c in range(C):
                    S[t, c] += M[u, c]
                ops += C
            acc[u] = 0
    return S, ops


@njit(cache=True)
def stream_delta(frames_ptr, frames_idx, n_ch, ax_ptr, ax_tgt, theta, M):
    """Thalamic delta coding: only input spikes that appeared/disappeared are sent;
    cortical units report only threshold crossings; the readout is kept incrementally."""
    n_units = len(theta)
    C = M.shape[1]
    T = len(frames_ptr) - 1
    acc = np.zeros(n_units, np.int32)
    on = np.zeros(n_ch, np.uint8)
    now = np.zeros(n_ch, np.uint8)
    score = np.zeros(C, np.float32)
    S = np.zeros((T, C), np.float32)
    ops = 0
    for t in range(T):
        for e in range(frames_ptr[t], frames_ptr[t + 1]):
            now[frames_idx[e]] = 1
        # appeared spikes
        for e in range(frames_ptr[t], frames_ptr[t + 1]):
            c = frames_idx[e]
            if on[c] == 0:
                on[c] = 1
                for s in range(ax_ptr[c], ax_ptr[c + 1]):
                    u = ax_tgt[s]
                    acc[u] += 1
                    if acc[u] == theta[u]:  # unit starts firing
                        for k in range(C):
                            score[k] += M[u, k]
                        ops += C
                ops += ax_ptr[c + 1] - ax_ptr[c]
        # vanished spikes (scan previous frame's list)
        if t > 0:
            for e in range(frames_ptr[t - 1], frames_ptr[t]):
                c = frames_idx[e]
                if on[c] == 1 and now[c] == 0:
                    on[c] = 0
                    for s in range(ax_ptr[c], ax_ptr[c + 1]):
                        u = ax_tgt[s]
                        if acc[u] == theta[u]:  # unit stops firing
                            for k in range(C):
                                score[k] -= M[u, k]
                            ops += C
                        acc[u] -= 1
                    ops += ax_ptr[c + 1] - ax_ptr[c]
        for e in range(frames_ptr[t], frames_ptr[t + 1]):
            now[frames_idx[e]] = 0
        # bookkeeping: mark/unmark this frame's spikes, scan the previous frame's list
        ops += 3 * (frames_ptr[t + 1] - frames_ptr[t])
        if t > 0:
            ops += frames_ptr[t] - frames_ptr[t - 1]
        S[t] = score
    return S, ops
