"""
SynapseBrain-LM: a language model built from brain services instead of attention.

Every byte is predicted bit by bit (8 binary decisions, like a population of binary neurons).

  granule layer  : sparse context detectors. Each of N_CTX "granule populations" hashes a
                   different view of the past (last 1,2,3,4,5,6,8 bytes, current word, word
                   pair, a skip context) to ONE active cell out of ~1M. Cells live in 64-byte "columns"
                   (one cache line per context per nibble), so a byte costs 2 memory fetches
                   per population - cost does not depend on how long the past is.
  hippocampus    : episodic index. A hash of the last few bytes points to the last time this
                   situation happened; the byte that followed is recalled (pattern completion).
                   This replaces attention's "induction heads" at O(1) cost and with
                   unlimited distance.
  short-term     : every granule synapse also keeps the last 6 outcomes it saw; a small
  plasticity       adaptive map turns that recent history into a second vote (fast synapses
                   next to slow ones).
  cerebellum     : Purkinje-like mixers. Weights over granule/hippocampal votes are selected
                   by context - three microzone maps: partial byte, novelty (how many
                   contexts were seen before) x recall state, previous byte - and learn from
                   the prediction error (climbing fibre) with a local delta rule. The learning
                   rate starts high and settles (developmental critical period).
  semantic memory: Hebbian word associations (words seen together wire together) plus a ring of
                   recently used words; at a word start the associates of the current topic are
                   pre-activated (priming), which keeps generated text on topic.
  working memory : a short-range episodic index (3 bytes, last 2 kB) - the brain's version of
                   an induction head.
  basal ganglia  : a second, tiny mixer arbitrates between the microzone outputs.
  thalamic gain  : adaptive probability maps (APM) re-calibrate the final confidence, one of
                   them keyed by the byte the hippocampus recalled.

Everything learns online: predict, see the real bit, update only the synapses that were active.
"""
import math
import mmap

import numpy as np
from numba import njit

N_CTX = 18         # granule populations
N_IN = 2 * N_CTX + 13  # votes per population, 4 x 2 hippocampal, 2 word-cache, 2 semantic, bias
ASSOC_BITS = 20    # semantic memory: 2^20 words x 8 associate synapses
RECENT = 2048      # reach of the short-range episodic index (working memory)
N_CACHE = 64       # recently used content words kept "primed"
MATCH_LONG = 16    # bytes of context for the second (precise) hippocampal index
# columns per population (log2): tiny for short contexts, large for long ones - like giving
# each brain area the number of synapses its job needs. 64 bytes per column.
#            o1  o2  o3  o4  o6  o8  word word2 o5  skip word3 skip34 place wplace shape vert topic sent
LOG_COLS = (16, 21, 23, 23, 23, 23, 22, 23, 23, 21, 23, 21, 22, 22, 22, 21, 22, 22)
LOG_WM = 18        # working-memory columns per population (used only when weights are frozen)
MATCH_MIN = 6      # bytes of context needed for hippocampal recall
MATCH_BITS = 22


def _huge(n, dtype, fill=0):
    """Zeroed array on 2 MB pages (fewer TLB misses on random access into GBs of synapses)."""
    dtype = np.dtype(dtype)
    m = mmap.mmap(-1, max(1, n * dtype.itemsize), flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
    if hasattr(mmap, "MADV_HUGEPAGE"):
        m.madvise(mmap.MADV_HUGEPAGE)
    a = np.frombuffer(m, dtype, count=n)
    if fill:
        a[:] = fill
    return a


def make_state(shrink=0, n_bytes=100_000_000):
    """shrink: use 2^-shrink of the default memory (for quick experiments)."""
    sizes = [1 << max(8, lc - shrink) for lc in LOG_COLS]
    wm = [1 << max(8, LOG_WM - shrink)] * N_CTX
    off = np.cumsum([0] + sizes + wm[:-1]).astype(np.int64) * 32
    st = {
        "T": _huge((sum(sizes) + sum(wm)) * 32, np.uint16),    # columns: [check, 15 p, 15 n, -]
        "TO": off[:N_CTX].copy(),                              # long-term column offset / population
        "TM": np.array(sizes, np.int64) - 1,                   # long-term column mask
        "WO": off[N_CTX:].copy(),                              # working-memory offset / population
        "WM": np.array(wm, np.int64) - 1,
        "W1": np.full((256, N_IN), 0.15, np.float32),          # microzones by partial byte
        "W2": np.full((4096, N_IN), 0.15, np.float32),         # microzones by match state/novelty/bit
        "HM": np.zeros(N_CTX * 8 * 8 * 64, np.uint16),          # short-term history maps
        "W3": np.full((1024, 5), 0.25, np.float32),            # basal ganglia arbiter
        "W4": _huge(65536 * N_IN, np.float32, 0.15).reshape(65536, N_IN),  # microzones by previous byte
        "A3": np.zeros(512 * 256 * 33, np.uint16),             # gain map keyed by recalled byte
        "A4": _huge((1 << 18) * 33, np.uint16),                # gain map keyed by last 2 bytes
        "W5": _huge((1 << 16) * N_IN, np.float32, 0.15).reshape(1 << 16, N_IN),  # microzones by last 2 bytes
        "CM": np.ones(N_CTX, np.bool_),                        # populations switched on
        "LN": np.zeros(4, np.int64),                           # line starts (for column context)
        "WF": np.full((256, 6), 0.2, np.float32),              # final learned arbitration
        "MT": _huge(1 << MATCH_BITS, np.int64),                # hippocampal index
        "MP": np.full(64 * 2 * 8, 32768, np.uint16),           # recall reliability
        "MT2": _huge(1 << MATCH_BITS, np.int64),               # precise (long-context) index
        "MP2": np.full(32 * 2 * 8, 32768, np.uint16),
        "MT3": _huge(1 << 20, np.int64),                       # lexical priming: word start -> last use
        "MP3": np.full(16 * 2 * 8, 32768, np.uint16),
        "WC": np.zeros((N_CACHE, 3), np.int64),                # primed words: (start, length, id)
        "AW": _huge((1 << ASSOC_BITS) * 8 * 4, np.int64).reshape(1 << ASSOC_BITS, 8, 4),
        "MP6": np.full(16 * 9 * 8, 32768, np.uint16),
        "MP4": np.full(16 * 9 * 8, 32768, np.uint16),
        "MT4": _huge(1 << 16, np.int64),                       # recent-only index on 3 bytes
        "MP5": np.full(16 * 8 * 2 * 8, 32768, np.uint16),
        "A1": np.zeros(256 * 33, np.uint16),                   # thalamic gain maps
        "A2": _huge(65536 * 33, np.uint16),
        "buf": _huge(n_bytes + 8, np.uint8),                   # episodic store (the text)
        "S": np.zeros(32, np.int64),                           # scalar state
    }
    st["HM"][:] = 32768
    for a in (st["A1"], st["A2"], st["A3"], st["A4"]):
        for j in range(33):
            a[j::33] = int(65535 / (1 + math.exp(-((j - 16) / 2.0))))
    return st


@njit(cache=True, inline="always")
def _hash(a, b):
    h = (a * 0x2F0B3A49D1C2E5 + b * 0x6A09E667F3BCC909 + 0x3C6EF372FE94F82B) & 0x7FFFFFFFFFFFFFFF
    return h ^ (h >> 29)


@njit(cache=True, inline="always", fastmath=True)
def _dot(w, x):
    s = np.float32(0.0)
    for i in range(x.shape[0]):
        s += w[i] * x[i]
    return s


@njit(cache=True, inline="always", fastmath=True)
def _learn(w, x, e):
    for i in range(x.shape[0]):
        w[i] += e * x[i]


@njit(cache=True, inline="always")
def _associate(AW, a, b, bs, bl):
    """Hebbian synapse a -> b in semantic memory (8 slots per word, weakest one decays)."""
    row = AW[a & ((1 << ASSOC_BITS) - 1)]
    weak = 0
    for q in range(8):
        if row[q, 0] == b:
            row[q, 1] = bs
            row[q, 2] = bl
            row[q, 3] += 1
            return
        if row[q, 3] < row[weak, 3]:
            weak = q
    if row[weak, 3] > 0:
        row[weak, 3] -= 1
    else:
        row[weak, 0] = b
        row[weak, 1] = bs
        row[weak, 2] = bl
        row[weak, 3] = 1


@njit(cache=True, inline="always")
def _squash(x, SQ):
    """Logistic function from a table (x in [-16, 16), step 1/64, linear interpolation)."""
    t = (x + 16.0) * 64.0
    if t <= 0.0:
        return SQ[0]
    if t >= 2047.0:
        return SQ[2047]
    k = int(t)
    f = t - k
    return SQ[k] + (SQ[k + 1] - SQ[k]) * f


@njit(cache=True, fastmath=True)
def run(data, start, end, learn_end, loss_start, T, TO, TM, WO, WM, LN, WF, final_mix, MT2, MP2, MT3, MP3, WC, MP4, MT4, MP5, AW, MP6, W1, W2, W3, MT, MP, A1, A2, buf, S,
        lr, limit, HM, W4, A3, use_w4, use_a3, hm_j, lr_decay, stp, A4, W5, CM, use_a4, use_w5, wm_cells,
        gen, temp, seed, recall):
    """Process data[start:end]. Synapses learn while pos < learn_end; log-loss (bits) is
    summed for pos >= loss_start. Returns (bits, n_bytes_scored)."""
    STR = np.empty(4096, np.float32)
    for i in range(4096):
        q = (i + 0.5) / 4096.0
        STR[i] = math.log(q / (1.0 - q))
    SQ = np.empty(2048, np.float64)
    for i in range(2048):
        SQ[i] = 1.0 / (1.0 + math.exp(-(i / 64.0 - 16.0)))
    RT = np.empty(1024, np.int64)
    for i in range(1024):
        RT[i] = int(65536.0 / (i + 1.6))

    c4 = S[0]
    c8 = S[1]
    wh = S[2]
    pw = S[3]
    mptr = S[4]
    mlen = S[5]
    ppw = S[6]
    place = S[7]  # "place cells": where we are in the document's markup
    shape = S[8]  # rhythm of character classes (letter/digit/space/punct/...)
    mptr2 = S[9]
    mlen2 = S[10]
    topic = S[11]    # semantic memory: the last two content words (5+ letters)
    sent = S[12]     # word index inside the current sentence
    wlen = S[13]     # letters in the current word
    wci = S[14]      # next slot in the primed-word ring
    mptr4 = S[15]
    mlen4 = S[16]
    cands = np.zeros(N_CACHE, np.int64)
    acands = np.zeros(64, np.int64)
    base = np.zeros(N_CTX, np.int64)
    hx = np.zeros(N_CTX, np.int64)
    x = np.zeros(N_IN, np.float32)
    xf = np.zeros(6, np.float32)
    idx = np.zeros(N_CTX, np.int64)
    ok = np.zeros(N_CTX, np.bool_)
    hidx = np.zeros(N_CTX, np.int64)
    bits = 0.0
    scored = 0
    lr0 = lr
    if gen:
        np.random.seed(seed)
    for pos in range(start, end):
        learn = pos < learn_end
        if lr_decay > 0.0:
            lr = lr0 * max(1.0, lr_decay / math.sqrt(1.0 + pos / 250000.0))
        byte = data[pos]
        # ---- context hashes for this byte (granule populations) --------------------
        hx[0] = _hash(1, c4 & 0xFF)
        hx[1] = _hash(2, c4 & 0xFFFF)
        hx[2] = _hash(3, c4 & 0xFFFFFF)
        hx[3] = _hash(4, c4 & 0xFFFFFFFF)
        hx[4] = _hash(6, (c4 & 0xFFFFFFFF) | ((c8 & 0xFFFF) << 32))
        hx[5] = _hash(8, (c4 & 0xFFFFFFFF) | ((c8 & 0xFFFFFFFF) << 32))
        hx[6] = _hash(10, wh)
        hx[7] = _hash(11, wh * 31 + pw)
        hx[8] = _hash(5, c4 & 0xFFFFFFFF | ((c8 & 0xFF) << 32))
        hx[9] = _hash(12, (c4 >> 8) & 0xFFFF)
        hx[10] = _hash(13, (wh * 31 + pw) * 17 + ppw)
        hx[11] = _hash(14, (c4 >> 16) & 0xFFFF)
        hx[12] = _hash(16, place * 65536 + (c4 & 0xFFFF))
        hx[13] = _hash(17, wh * 64 + (place & 31))
        hx[14] = _hash(18, shape * 256 + (c4 & 0xFF))
        colp = pos - LN[0]
        above = buf[LN[1] + colp] if LN[1] + colp < LN[0] else 0
        hx[15] = _hash(20, (above * 256 + (c4 & 0xFF)) * 64 + min(colp, 63))
        hx[16] = _hash(21, topic * 1000003 + wh)
        hx[17] = _hash(22, (min(sent, 15) * 1000003 + pw) * 31 + (c4 & 0xFF))
        h2 = _hash(15, c4 & 0xFFFF)
        # ---- hippocampus: recall the byte that followed the last identical context ---
        if mlen > 0 and mptr < pos and buf[mptr] == (c4 & 0xFF):
            mlen += 1
            mptr += 1
        else:
            mlen = 0
        if pos >= MATCH_MIN:
            mh = _hash(99, (c4 & 0xFFFFFFFF) | ((c8 & 0xFFFF) << 32)) & ((1 << MATCH_BITS) - 1)
            if mlen == 0:
                cand = MT[mh]
                if cand > 0:
                    L = 0
                    while L < 32 and cand - 1 - L >= 0 and buf[cand - 1 - L] == buf[pos - 1 - L]:
                        L += 1
                    if L >= MATCH_MIN:
                        mlen = L
                        mptr = cand
            MT[mh] = pos
        if mlen > 0:
            pbyte = buf[mptr] | 256
        else:
            pbyte = 0
        # second index: only exact recalls of 16+ bytes of context
        if mlen2 > 0 and mptr2 < pos and buf[mptr2] == (c4 & 0xFF):
            mlen2 += 1
            mptr2 += 1
        else:
            mlen2 = 0
        if pos >= MATCH_LONG:
            hl = 0
            for q in range(1, MATCH_LONG + 1):
                hl = (hl * 0x100000001B3 + buf[pos - q] + 1) & 0x7FFFFFFFFFFFFFFF
            mh2 = _hash(98, hl) & ((1 << MATCH_BITS) - 1)
            if mlen2 == 0:
                cand = MT2[mh2]
                if cand > 0:
                    L = 0
                    while L < 64 and cand - 1 - L >= 0 and buf[cand - 1 - L] == buf[pos - 1 - L]:
                        L += 1
                    if L >= MATCH_LONG:
                        mlen2 = L
                        mptr2 = cand
            MT2[mh2] = pos
        pbyte2 = (buf[mptr2] | 256) if mlen2 > 0 else 0
        # primed vocabulary: which recent content words fit the letters typed so far?
        nc = 0
        prev = c4 & 0xFF
        if wlen > 0 or prev == 32 or prev == 91 or prev == 40:
            for q in range(N_CACHE):
                ws_, wl_ = WC[q, 0], WC[q, 1]
                if wl_ > wlen:
                    same = True
                    for r in range(wlen):
                        if buf[ws_ + r] != buf[pos - wlen + r]:
                            same = False
                            break
                    if same:
                        cands[nc] = buf[ws_ + wlen]
                        nc += 1
        # semantic memory: letters of words associated with the last 8 content words
        na = 0
        if wlen > 0 or prev == 32 or prev == 91 or prev == 40:
            for back in range(1, 9):
                row = AW[WC[(wci - back) % N_CACHE, 2] & ((1 << ASSOC_BITS) - 1)]
                for q in range(8):
                    if row[q, 3] >= 2 and row[q, 2] > wlen and na < 64:
                        ws_ = row[q, 1]
                        same = True
                        for r in range(wlen):
                            if buf[ws_ + r] != buf[pos - wlen + r]:
                                same = False
                                break
                        if same:
                            acands[na] = buf[ws_ + wlen]
                            na += 1
        # working-memory recall: where in the last RECENT bytes did these 3 bytes occur?
        if mlen4 > 0 and mptr4 < pos and buf[mptr4] == (c4 & 0xFF):
            mlen4 += 1
            mptr4 += 1
        else:
            mlen4 = 0
        if pos >= 3:
            k4 = _hash(96, c4 & 0xFFFFFF) & ((1 << 16) - 1)
            if mlen4 == 0:
                cand = MT4[k4]
                if cand > 0 and pos - cand < RECENT and buf[cand - 1] == buf[pos - 1] and \
                        buf[cand - 2] == buf[pos - 2] and buf[cand - 3] == buf[pos - 3]:
                    mlen4 = 3
                    mptr4 = cand
            MT4[k4] = pos
        if mlen4 > 0 and pos - mptr4 >= RECENT:
            mlen4 = 0
        pbyte4 = (buf[mptr4] | 256) if mlen4 > 0 else 0
        dist4 = min((pos - mptr4) // 256, 7) if mlen4 > 0 else 0
        # lexical priming: how did the most recent word with this same beginning go on?
        pbyte3 = 0
        if wh != 0:
            k3 = _hash(97, wh) & ((1 << 20) - 1)
            cand = MT3[k3]
            if cand > 0 and cand < pos:
                pbyte3 = buf[cand] | 256
            MT3[k3] = pos
        mb = mlen if mlen < 15 else 15
        if mlen >= 32:
            mb = 15 + min((mlen - 15) // 16, 16)
        # ---- 8 bits -----------------------------------------------------------------
        c0 = 1
        for j in range(8):
            if j == 0 or j == 4:
                for i in range(N_CTX):
                    h = _hash(hx[i], c0 if j == 4 else 0)
                    b = (h >> 16) & TM[i]
                    chk = ((h >> 47) & 0xFFFF) | 1
                    bb = TO[i] + b * 32
                    if T[bb] != chk:
                        if learn:
                            T[bb] = chk
                            for k in range(1, 31):
                                T[bb + k] = 32768 if k < 16 else 0
                            ok[i] = True
                        elif stp and wm_cells:
                            # frozen weights: a new context gets a cell in working memory
                            # (separate, bounded - long-term cells are never overwritten)
                            bb = WO[i] + ((h >> 16) & WM[i]) * 32
                            if T[bb] != chk:
                                T[bb] = chk
                                for k in range(1, 31):
                                    T[bb + k] = 32768 if k < 16 else 0
                            ok[i] = True
                        else:
                            ok[i] = False
                    else:
                        ok[i] = True
                    base[i] = bb
                nib = 1
            bit = (byte >> (7 - j)) & 1
            # granule votes
            conf = 0
            for i in range(N_CTX):
                idx[i] = base[i] + nib
                if ok[i] and CM[i]:
                    x[i] = STR[T[idx[i]] >> 4]
                    nw = T[idx[i] + 15]
                    cnt = nw & 1023
                    hi = ((i * 8 + (cnt if cnt < 7 else 7)) * 8 + (j if hm_j else 0)) * 64 + (nw >> 10)
                    hidx[i] = hi
                    x[N_CTX + i] = STR[HM[hi] >> 4]
                    if cnt > 0 and i < 6:
                        conf += 1
                else:
                    # unseen context: vote exactly like a freshly created cell would
                    x[i] = 0.0
                    x[N_CTX + i] = STR[HM[(i * 64 + (j if hm_j else 0)) * 64] >> 4]
                    hidx[i] = -1
            # hippocampal votes
            expb = -1
            if pbyte > 0 and (pbyte >> (8 - j)) == c0:
                expb = (pbyte >> (7 - j)) & 1
            if expb >= 0:
                mi = (min(mlen, 63) * 2 + expb) * 8 + j
                x[2 * N_CTX] = STR[MP[mi] >> 4] * recall
                x[2 * N_CTX + 1] = (2 * expb - 1) * min(mlen, 32) / 8.0 * recall
            else:
                mi = -1
                x[2 * N_CTX] = 0.0
                x[2 * N_CTX + 1] = 0.0
            expb2 = -1
            if pbyte2 > 0 and (pbyte2 >> (8 - j)) == c0:
                expb2 = (pbyte2 >> (7 - j)) & 1
            if expb2 >= 0:
                mi2 = (min(mlen2 // 4, 31) * 2 + expb2) * 8 + j
                x[2 * N_CTX + 2] = STR[MP2[mi2] >> 4] * recall
                x[2 * N_CTX + 3] = (2 * expb2 - 1) * min(mlen2, 64) / 16.0 * recall
            else:
                mi2 = -1
                x[2 * N_CTX + 2] = 0.0
                x[2 * N_CTX + 3] = 0.0
            expb3 = -1
            if pbyte3 > 0 and (pbyte3 >> (8 - j)) == c0:
                expb3 = (pbyte3 >> (7 - j)) & 1
            if expb3 >= 0:
                mi3 = (min(wlen, 15) * 2 + expb3) * 8 + j
                x[2 * N_CTX + 4] = STR[MP3[mi3] >> 4]
                x[2 * N_CTX + 5] = (2 * expb3 - 1) * 0.5
            else:
                mi3 = -1
                x[2 * N_CTX + 4] = 0.0
                x[2 * N_CTX + 5] = 0.0
            n0 = 0
            n1 = 0
            for q in range(nc):
                if ((cands[q] | 256) >> (8 - j)) == c0:
                    if (cands[q] >> (7 - j)) & 1:
                        n1 += 1
                    else:
                        n0 += 1
            if n0 + n1 > 0:
                x[2 * N_CTX + 6] = min(max(math.log((n1 + 0.3) / (n0 + 0.3)), -4.0), 4.0)
                mi4 = (min(n0 + n1, 15) * 9 + (8 * n1) // (n0 + n1)) * 8 + j
                x[2 * N_CTX + 7] = STR[MP4[mi4] >> 4]
            else:
                mi4 = -1
                x[2 * N_CTX + 6] = 0.0
                x[2 * N_CTX + 7] = 0.0
            expb4 = -1
            if pbyte4 > 0 and (pbyte4 >> (8 - j)) == c0:
                expb4 = (pbyte4 >> (7 - j)) & 1
            if expb4 >= 0:
                mi5 = ((min(mlen4, 15) * 8 + dist4) * 2 + expb4) * 8 + j
                x[2 * N_CTX + 8] = STR[MP5[mi5] >> 4]
                x[2 * N_CTX + 9] = (2 * expb4 - 1) * min(mlen4, 16) / 8.0
            else:
                mi5 = -1
                x[2 * N_CTX + 8] = 0.0
                x[2 * N_CTX + 9] = 0.0
            n0 = 0
            n1 = 0
            for q in range(na):
                if ((acands[q] | 256) >> (8 - j)) == c0:
                    if (acands[q] >> (7 - j)) & 1:
                        n1 += 1
                    else:
                        n0 += 1
            if n0 + n1 > 0:
                x[2 * N_CTX + 10] = min(max(math.log((n1 + 0.3) / (n0 + 0.3)), -4.0), 4.0)
                mi6 = (min(n0 + n1, 15) * 9 + (8 * n1) // (n0 + n1)) * 8 + j
                x[2 * N_CTX + 11] = STR[MP6[mi6] >> 4]
            else:
                mi6 = -1
                x[2 * N_CTX + 10] = 0.0
                x[2 * N_CTX + 11] = 0.0
            x[2 * N_CTX + 12] = 0.25
            # cerebellar microzones
            z1 = c0
            z2 = ((mb * 2 + (1 if expb >= 0 else 0)) * 7 + conf) * 8 + j
            if z2 >= 4096:
                z2 = 4095
            z4 = ((c4 & 0xFF) << 8) | c0
            z5 = ((h2 & 255) << 8) | c0
            d1 = _dot(W1[z1], x)
            d2 = _dot(W2[z2], x)
            d4 = np.float32(0.0)
            d5 = np.float32(0.0)
            if use_w4:
                d4 = _dot(W4[z4], x)
            if use_w5:
                d5 = _dot(W5[z5], x)
            p1 = _squash(d1, SQ)
            p2 = _squash(d2, SQ)
            p4 = _squash(d4, SQ)
            p5 = _squash(d5, SQ)
            # basal ganglia arbitration
            z3 = (c4 & 0xFF) * 4 + (j >> 1)
            s1 = min(max(d1, -20.0), 20.0)
            s2 = min(max(d2, -20.0), 20.0)
            s4 = min(max(d4, -20.0), 20.0)
            s5 = min(max(d5, -20.0), 20.0)
            d3 = W3[z3, 0] * s1 + W3[z3, 1] * s2 + W3[z3, 2] * 0.25 + W3[z3, 3] * s4 + W3[z3, 4] * s5
            p3 = _squash(d3, SQ)
            # thalamic gain maps (interpolated APMs)
            st3 = d3 * 2.0 + 16.0
            if st3 < 0.0:
                st3 = 0.0
            if st3 > 31.999:
                st3 = 31.999
            lo = int(st3)
            wlo = st3 - lo
            a1 = c0 * 33 + lo
            a2 = (c0 | ((c4 & 0xFF) << 8)) * 33 + lo
            pa1 = (A1[a1] * (1 - wlo) + A1[a1 + 1] * wlo) / 65536.0
            pa2 = (A2[a2] * (1 - wlo) + A2[a2 + 1] * wlo) / 65536.0
            a3 = ((pbyte if expb >= 0 else 0) * 256 + c0) * 33 + lo
            a4 = ((h2 & 1023) * 256 + c0) * 33 + lo
            pa3 = (A3[a3] * (1 - wlo) + A3[a3 + 1] * wlo) / 65536.0 if use_a3 else p3
            pa4 = (A4[a4] * (1 - wlo) + A4[a4 + 1] * wlo) / 65536.0 if use_a4 else p3
            if final_mix:
                xf[0] = min(max(d3, -12.0), 12.0)
                xf[1] = STR[min(max(int(pa1 * 4096), 0), 4095)]
                xf[2] = STR[min(max(int(pa2 * 4096), 0), 4095)]
                xf[3] = STR[min(max(int(pa3 * 4096), 0), 4095)]
                xf[4] = STR[min(max(int(pa4 * 4096), 0), 4095)]
                xf[5] = 0.25
                df = _dot(WF[c0], xf)
                pf = _squash(df, SQ)
                p = (pf * 3 + (2 * p3 + pa1 + pa2 + 2 * pa3 + 2 * pa4) / 8.0) / 4.0
            else:
                pf = 0.5
                p = (2 * p3 + pa1 + pa2 + 2 * pa3 + 2 * pa4) / 8.0
            if p < 1.0 / 8192:
                p = 1.0 / 8192
            if p > 1 - 1.0 / 8192:
                p = 1 - 1.0 / 8192
            if gen:
                # speaking: sample the bit from the model's own belief (temperature `temp`)
                q = 1.0 / (1.0 + math.exp(-math.log(p / (1.0 - p)) / temp))
                bit = 1 if np.random.random() < q else 0
            if pos >= loss_start:
                bits -= math.log2(p if bit else 1.0 - p)
            # ---- learning: only active synapses change ------------------------------
            if learn:
                _learn(W1[z1], x, np.float32((bit - p1) * lr))
                _learn(W2[z2], x, np.float32((bit - p2) * lr))
                e3 = (bit - p3) * lr * 0.5
                W3[z3, 0] += e3 * s1
                W3[z3, 1] += e3 * s2
                W3[z3, 2] += e3 * 0.25
                if use_w4:
                    _learn(W4[z4], x, np.float32((bit - p4) * lr))
                    W3[z3, 3] += e3 * s4
                if use_w5:
                    _learn(W5[z5], x, np.float32((bit - p5) * lr))
                    W3[z3, 4] += e3 * s5
                tgt = bit * 65535
                if final_mix:
                    _learn(WF[c0], xf, np.float32((bit - pf) * lr * 0.5))
                A1[a1 + (1 if wlo > 0.5 else 0)] += (tgt - A1[a1 + (1 if wlo > 0.5 else 0)]) * 0.02
                A2[a2 + (1 if wlo > 0.5 else 0)] += (tgt - A2[a2 + (1 if wlo > 0.5 else 0)]) * 0.02
                if use_a3:
                    A3[a3 + (1 if wlo > 0.5 else 0)] += (tgt - A3[a3 + (1 if wlo > 0.5 else 0)]) * 0.02
                if use_a4:
                    A4[a4 + (1 if wlo > 0.5 else 0)] += (tgt - A4[a4 + (1 if wlo > 0.5 else 0)]) * 0.02
                for i in range(N_CTX):
                    if ok[i]:
                        k = idx[i]
                        nw = np.int64(T[k + 15])
                        n = nw & 1023
                        pv = np.int64(T[k])
                        pv += ((bit << 16) - bit - pv) * RT[n] >> 16
                        T[k] = pv
                        if n < limit:
                            n += 1
                        T[k + 15] = ((((nw >> 10) << 1) | bit) & 63) << 10 | n
                        hi = hidx[i]
                        hv = np.int64(HM[hi])
                        HM[hi] = hv + (((bit << 16) - bit - hv) >> 5)
                if mi >= 0:
                    pv = np.int64(MP[mi])
                    pv += ((bit << 16) - bit - pv) >> 6
                    MP[mi] = pv
                if mi2 >= 0:
                    pv = np.int64(MP2[mi2])
                    pv += ((bit << 16) - bit - pv) >> 6
                    MP2[mi2] = pv
                if mi3 >= 0:
                    pv = np.int64(MP3[mi3])
                    pv += ((bit << 16) - bit - pv) >> 6
                    MP3[mi3] = pv
                if mi4 >= 0:
                    pv = np.int64(MP4[mi4])
                    pv += ((bit << 16) - bit - pv) >> 6
                    MP4[mi4] = pv
                if mi6 >= 0:
                    pv = np.int64(MP6[mi6])
                    pv += ((bit << 16) - bit - pv) >> 6
                    MP6[mi6] = pv
                if mi5 >= 0:
                    pv = np.int64(MP5[mi5])
                    pv += ((bit << 16) - bit - pv) >> 6
                    MP5[mi5] = pv
            elif stp:
                # short-term plasticity only: cells remember their last outcomes (working
                # memory); long-term synapses (probabilities, counts, mixers, maps) stay frozen
                for i in range(N_CTX):
                    if ok[i]:
                        k = idx[i]
                        nw = np.int64(T[k + 15])
                        T[k + 15] = ((((nw >> 10) << 1) | bit) & 63) << 10 | (nw & 1023)
            c0 = (c0 << 1) | bit
            nib = (nib << 1) | bit
        if pos >= loss_start:
            scored += 1
        if gen:
            byte = c0 - 256
            data[pos] = byte
        # ---- byte done: update history / word state ---------------------------------
        buf[pos] = byte
        if byte == 10:
            LN[1] = LN[0]
            LN[0] = pos + 1
        c8 = ((c8 << 8) | (c4 >> 24)) & 0xFFFFFFFF
        c4 = ((c4 << 8) | byte) & 0xFFFFFFFF
        ch = byte
        if 65 <= ch <= 90:
            ch += 32
        if 97 <= ch <= 122 or ch >= 128:
            wh = (wh * 773 + ch) & 0xFFFFFFFFFFFF
            wlen += 1
        elif wh != 0:
            ppw = pw
            pw = wh
            if wlen >= 5:
                topic = ((topic & 0xFFFFFF) * 16777619 + (wh & 0xFFFFFF)) & 0xFFFFFFFFFFFF
            if wlen >= 4:
                if learn:  # Hebb: words that appear together wire together
                    for back in range(1, 17):
                        o = (wci - back) % N_CACHE
                        if WC[o, 1] > 0 and WC[o, 2] != wh:
                            _associate(AW, WC[o, 2], wh, pos - wlen, wlen)
                            _associate(AW, wh, WC[o, 2], WC[o, 0], WC[o, 1])
                WC[wci, 0] = pos - wlen
                WC[wci, 1] = wlen
                WC[wci, 2] = wh
                wci = (wci + 1) % N_CACHE
            wh = 0
            wlen = 0
            sent += 1
        if byte == 46 or byte == 10 or byte == 33 or byte == 63:
            sent = 0
        # place cells: bracket depth of [[links]], {{templates}}, <tags>, line start, column
        lk = place & 3
        tp = (place >> 2) & 3
        tg = (place >> 4) & 1
        col = (place >> 5) & 7
        if byte == 91 and lk < 3:
            lk += 1
        elif byte == 93 and lk > 0:
            lk -= 1
        elif byte == 123 and tp < 3:
            tp += 1
        elif byte == 125 and tp > 0:
            tp -= 1
        elif byte == 60:
            tg = 1
        elif byte == 62:
            tg = 0
        if byte == 10:
            col = 0
        elif col < 7:
            col += 1
        place = lk | (tp << 2) | (tg << 4) | (col << 5)
        if byte < 33:
            cl = 0
        elif 97 <= byte <= 122:
            cl = 1
        elif 65 <= byte <= 90:
            cl = 2
        elif 48 <= byte <= 57:
            cl = 3
        elif byte >= 128:
            cl = 4
        elif byte == 91 or byte == 93 or byte == 123 or byte == 125 or byte == 60 or byte == 62:
            cl = 5
        else:
            cl = 6
        shape = ((shape << 3) | cl) & 0xFFFFFF
    S[0] = c4
    S[1] = c8
    S[2] = wh
    S[3] = pw
    S[4] = mptr
    S[5] = mlen
    S[6] = ppw
    S[7] = place
    S[8] = shape
    S[9] = mptr2
    S[10] = mlen2
    S[11] = topic
    S[12] = sent
    S[13] = wlen
    S[14] = wci
    S[15] = mptr4
    S[16] = mlen4
    return bits, scored


def process(data, st, start, end, learn_end, loss_start, lr=0.002, limit=255, use_w4=True, use_a3=True,
            hm_j=True, lr_decay=5.0, stp=False, use_a4=True, use_w5=True, wm_cells=True, final_mix=True,
            gen=False, temp=1.0, seed=0, recall=1.0):
    return run(data, start, end, learn_end, loss_start, st["T"], st["TO"], st["TM"], st["WO"], st["WM"],
               st["LN"], st["WF"], final_mix, st["MT2"], st["MP2"], st["MT3"], st["MP3"], st["WC"], st["MP4"], st["MT4"], st["MP5"], st["AW"], st["MP6"], st["W1"], st["W2"], st["W3"],
               st["MT"], st["MP"], st["A1"], st["A2"], st["buf"], st["S"], lr, limit, st["HM"],
               st["W4"], st["A3"], use_w4, use_a3, hm_j, lr_decay, stp, st["A4"], st["W5"], st["CM"],
               use_a4, use_w5, wm_cells, gen, temp, seed, recall)


def generate(st, data, pos, n, temp=0.8, seed=0, prompt=None, recall=1.0):
    """Write `prompt` at data[pos:], let the brain read it (weights frozen, working memory on),
    then let it speak n bytes. `data` must be a writable uint8 array with room for the text.
    Returns the generated bytes."""
    if prompt is not None:
        data[pos : pos + len(prompt)] = np.frombuffer(prompt, np.uint8)
        process(data, st, pos, pos + len(prompt), 0, 1 << 62, stp=True)
        pos += len(prompt)
    # while speaking, recall from the global episodic index can be damped (recall < 1)
    process(data, st, pos, pos + n, 0, 1 << 62, stp=True, gen=True, temp=temp, seed=seed, recall=recall)
    return bytes(data[pos : pos + n])
