"""
Visual cortex for SynapseBrain: pixels -> retinal spikes -> sparse cortical code.

  retina : a 64x64 RGB frame becomes 10 binary spike maps: ON and OFF centre-surround cells
           (edges), 6 colour channels (hue bins of saturated pixels), dark and bright cells.
  cortex : N neurons with K synapses each, drawn from a local patch of the visual field
           (retinotopy). The k most driven neurons fire (lateral inhibition, ~3%).
  development (plasticity=True): structural Hebbian plasticity - when a neuron wins, one of its
           synapses that saw nothing is rewired to an input that was active in its patch. The
           cortex tunes itself to what it keeps seeing, as young visual cortex does, with no labels.
"""
import cv2
import numpy as np

SIZE = 64
N_MAPS = 10
N_IN = N_MAPS * SIZE * SIZE


def retina(frame_bgr):
    """uint8 BGR frame (any size) -> boolean spike vector of length N_IN."""
    f = cv2.resize(frame_bgr, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2].astype(np.int16)
    blur = cv2.blur(v, (5, 5))
    maps = [v - blur > 12, blur - v > 12]                       # ON / OFF centre-surround
    sat = hsv[..., 1] > 60
    hue = hsv[..., 0] // 30                                     # 6 hue bins (0..179)
    maps += [sat & (hue == h) for h in range(6)]
    maps += [v < 50, v > 200]                                   # dark / bright
    return np.concatenate([m.ravel() for m in maps])


class VisualCortex:
    def __init__(self, n=8192, k_syn=16, radius=5, active=0.03, seed=0):
        r = np.random.default_rng(seed)
        self.n, self.k = n, int(n * active)
        cy, cx = r.integers(radius, SIZE - radius, (2, n))
        self.cy, self.cx, self.rad = cy, cx, radius
        self.syn = self._draw(r, cy[:, None], cx[:, None], (n, k_syn))
        self.rng = r
        self.freq = np.full(N_IN, 0.1, np.float32)       # how often each input fires (homeostasis)
        self.wins = np.full(n, active, np.float32)       # how often each neuron wins

    def _draw(self, r, cy, cx, shape):
        dy = r.integers(-self.rad, self.rad + 1, shape)
        dx = r.integers(-self.rad, self.rad + 1, shape)
        ch = r.integers(0, N_MAPS, shape)
        return (ch * SIZE * SIZE + (cy + dy) * SIZE + (cx + dx)).astype(np.int32)

    def __call__(self, spikes, plasticity=False, rate=0.25):
        drive = spikes[self.syn].sum(1, dtype=np.int16)
        win = np.argpartition(-drive, self.k)[: self.k]
        if plasticity:
            # homeostasis: track input and neuron activity; greedy neurons stop rewiring and
            # inputs that are almost always on (sky, ground) are not worth a synapse
            self.freq *= 0.999
            self.freq[spikes] += 0.001
            self.wins *= 0.999
            self.wins[win] += 0.001
            w = win[self.rng.random(len(win)) < rate]
            w = w[self.wins[w] < 3 * self.k / self.n]
            # structural Hebbian plasticity: winners rewire one silent synapse to an active input
            if len(w):
                silent = ~spikes[self.syn[w]]
                has = silent.any(1)
                w = w[has]
                j = silent[has].argmax(1)
                cand = self._draw(self.rng, self.cy[w], self.cx[w], (len(w),))
                ok = spikes[cand] & (self.freq[cand] < 0.25)
                self.syn[w[ok], j[ok]] = cand[ok]
        return win
