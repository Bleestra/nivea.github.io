"""
Visual cortex on the GPU: the same retina and the same cortex as visual_cortex.py, but many frames
at once and a much larger cortex.

Nothing about learning changes: the retina is fixed, the cortex is k-winners-take-all with structural
Hebbian plasticity and homeostasis, readouts learn by a local error rule. What the GPU buys is size:
a bigger picture (128x128 instead of 64x64: a block 20 blocks away is still a few pixels) and 4x
more neurons (32768), developed on thousands of frames per second instead of hundreds.

  retina_gpu(frames)            uint8 BGR frames (B, H, W, 3) -> spikes (B, 10*S*S), bool, on the GPU
  VisualCortexGPU(n, size=S)    spikes (B, N_IN) -> winners (B, k) (indices of the neurons that fire)

Measured on an RTX 3090 (65536 neurons, 128x128, 64 frames): 170 ms on the CPU, 7 ms on the GPU.
One small frame (8192 neurons, 64x64) is faster on the CPU - use visual_cortex.py there.
"""
import numpy as np
import torch
import torch.nn.functional as F

N_MAPS = 10


def device():
    """The GPU if there is one (SYNAPSE_DEVICE=cpu forces the CPU)."""
    import os

    want = os.environ.get("SYNAPSE_DEVICE", "auto")
    if want != "cpu" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _hsv(bgr):
    """(B, 3, S, S) float 0..255 BGR -> H (0..179), S (0..255), V (0..255) as OpenCV computes them."""
    b, g, r = bgr[:, 0], bgr[:, 1], bgr[:, 2]
    v, _ = bgr.max(1)
    mn, _ = bgr.min(1)
    diff = v - mn
    s = torch.where(v > 0, 255.0 * diff / v.clamp(min=1e-6), torch.zeros_like(v))
    d = diff.clamp(min=1e-6)
    h = torch.where(v == r, 60.0 * (g - b) / d,
                    torch.where(v == g, 120.0 + 60.0 * (b - r) / d, 240.0 + 60.0 * (r - g) / d))
    h = torch.where(diff > 0, h, torch.zeros_like(h))
    h = torch.where(h < 0, h + 360.0, h)
    return torch.round(h / 2).clamp(max=179), torch.round(s), v


def retina_gpu(frames, size=64, dev=None):
    """uint8 BGR frames (B, H, W, 3) (numpy or tensor, any H, W) -> bool spikes (B, N_MAPS*size*size).

    The same 10 maps as visual_cortex.retina: ON and OFF centre-surround (edges), 6 hue channels of
    saturated pixels, dark and bright cells."""
    dev = dev or device()
    x = torch.as_tensor(np.ascontiguousarray(frames) if isinstance(frames, np.ndarray) else frames, device=dev)
    if x.dim() == 3:
        x = x[None]
    x = x.permute(0, 3, 1, 2).float()
    if x.shape[-1] != size or x.shape[-2] != size:
        x = torch.round(F.interpolate(x, size=(size, size), mode="area"))
    h, s, v = _hsv(x)
    blur = torch.round(F.avg_pool2d(F.pad(v[:, None], (2, 2, 2, 2), mode="reflect"), 5, stride=1)[:, 0])
    maps = [v - blur > 12, blur - v > 12]
    sat = s > 60
    hue = torch.div(h, 30, rounding_mode="floor")
    maps += [sat & (hue == k) for k in range(6)]
    maps += [v < 50, v > 200]
    return torch.stack(maps, 1).reshape(x.shape[0], -1)


class VisualCortexGPU:
    """N neurons, each with k_syn synapses from a local patch of the visual field; the k most driven
    fire (lateral inhibition). With plasticity, winners rewire a silent synapse to an active input."""

    def __init__(self, n=32768, k_syn=24, radius=None, active=0.03, size=128, seed=0, dev=None):
        self.dev = dev or device()
        self.n, self.k, self.size = n, int(n * active), size
        self.rad = radius or max(5, size // 12)
        self.n_in = N_MAPS * size * size
        self.g = torch.Generator(device=self.dev).manual_seed(seed)
        self.cy = self._int(self.rad, size - self.rad, (n,))
        self.cx = self._int(self.rad, size - self.rad, (n,))
        self.syn = self._draw(self.cy[:, None], self.cx[:, None], (n, k_syn))
        self.freq = torch.full((self.n_in,), 0.1, device=self.dev)   # how often each input fires (homeostasis)
        self.wins = torch.full((n,), active, device=self.dev)        # how often each neuron wins

    def _int(self, lo, hi, shape):
        return torch.randint(lo, hi, shape, generator=self.g, device=self.dev)

    def _draw(self, cy, cx, shape):
        dy = self._int(-self.rad, self.rad + 1, shape)
        dx = self._int(-self.rad, self.rad + 1, shape)
        ch = self._int(0, N_MAPS, shape)
        return ch * self.size * self.size + (cy + dy) * self.size + (cx + dx)

    @torch.no_grad()
    def __call__(self, spikes, plasticity=False, rate=0.25):
        """spikes: bool (N_IN,) or (B, N_IN) on the device. Returns winners (k,) or (B, k)."""
        single = spikes.dim() == 1
        sp = spikes[None] if single else spikes
        drive = sp[:, self.syn].sum(2, dtype=torch.int16)
        win = drive.topk(self.k, dim=1).indices
        if plasticity:
            self._develop(sp, win, rate)
        return win[0] if single else win

    def _develop(self, sp, win, rate):
        B = sp.shape[0]
        decay = 0.999 ** B
        self.freq.mul_(decay).add_(0.001 * sp.float().sum(0))
        self.wins.mul_(decay).index_add_(0, win.reshape(-1), torch.full((win.numel(),), 0.001, device=self.dev))
        for b in range(B):                                   # frames in order, as the eye sees them
            s, w = sp[b], win[b]
            w = w[torch.rand(len(w), generator=self.g, device=self.dev) < rate]
            w = w[self.wins[w] < 3 * self.k / self.n]
            if not len(w):
                continue
            silent = ~s[self.syn[w]]
            has = silent.any(1)
            w = w[has]
            j = silent[has].int().argmax(1)
            cand = self._draw(self.cy[w], self.cx[w], (len(w),))
            ok = s[cand] & (self.freq[cand] < 0.25)
            self.syn[w[ok], j[ok]] = cand[ok]

    def state(self):
        return {"syn": self.syn.cpu().numpy(), "cy": self.cy.cpu().numpy(), "cx": self.cx.cpu().numpy(),
                "freq": self.freq.cpu().numpy(), "wins": self.wins.cpu().numpy(), "size": self.size}

    def save(self, path):
        np.savez_compressed(path, **self.state())

    def load(self, path):
        """Load a developed cortex if it has this shape (another size would be another cortex)."""
        import os

        if not os.path.exists(path):
            return False
        z = np.load(path)
        if z["syn"].shape != tuple(self.syn.shape) or int(z["size"]) != self.size:
            return False
        for k in ("syn", "cy", "cx", "freq", "wins"):
            getattr(self, k).copy_(torch.as_tensor(z[k], device=self.dev))
        return True


class SensorTeacherGPU:
    """sensor teacher (see teacher.py) with its readout synapses on the GPU, for a large cortex."""

    N_CLS = 6

    def __init__(self, n_visual, dev=None):
        self.dev = dev or device()
        self.W = torch.zeros((n_visual, 25 * self.N_CLS + 2 + 5), device=self.dev)
        self.acc = {"front": 0.0, "grid": 0.0, "sky": 0.0, "tree": 0.0}
        self.n = self.session = 0

    @torch.no_grad()
    def perceive(self, code):
        s = self.W[code].sum(0)
        o = 25 * self.N_CLS
        grid = s[:o].reshape(25, self.N_CLS).argmax(1)
        return grid, int(s[o:o + 2].argmax()), int(s[o + 2:].argmax())

    @torch.no_grad()
    def teach(self, code, grid, sky, tree):
        """code: winners (tensor on the device); grid/sky/tree: what the direct senses say.
        Returns the percept as numpy/int (what the eyes alone saw)."""
        pg, ps, pt = self.perceive(code)
        g = torch.as_tensor(np.minimum(np.asarray(grid), self.N_CLS - 1), device=self.dev)
        upd = torch.zeros(self.W.shape[1], device=self.dev)
        wrong = torch.nonzero(pg != g).squeeze(1)
        upd.index_add_(0, wrong * self.N_CLS + g[wrong], torch.ones(len(wrong), device=self.dev))
        upd.index_add_(0, wrong * self.N_CLS + pg[wrong], -torch.ones(len(wrong), device=self.dev))
        o = 25 * self.N_CLS
        if ps != sky:
            upd[o + sky] += 1
            upd[o + ps] -= 1
        if pt != tree:
            upd[o + 2 + tree] += 1
            upd[o + 2 + pt] -= 1
        self.W[code] += upd
        pg = pg.cpu().numpy()
        grid = np.minimum(np.asarray(grid), self.N_CLS - 1)
        self.n += 1
        self.session += 1
        k = max(0.005, 1.0 / self.session)
        for key, ok in (("front", pg[7] == grid[7]), ("grid", (pg == grid).mean()), ("sky", ps == sky),
                        ("tree", pt == tree)):
            self.acc[key] += k * (float(ok) - self.acc[key])
        return pg, ps, pt

    def report(self):
        return ", ".join(f"{k} {v * 100:.0f}%" for k, v in self.acc.items())

    def save(self, path):
        np.savez_compressed(path, W=self.W.cpu().numpy(), n=self.n)

    def load(self, path):
        z = np.load(path)
        if z["W"].shape != tuple(self.W.shape):
            return
        self.W.copy_(torch.as_tensor(z["W"], device=self.dev))
        self.n = int(z["n"])
