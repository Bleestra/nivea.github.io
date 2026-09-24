"""
Sensor teacher: the direct senses (touch, balance, the block sensors) teach the eyes, live.

Readout neurons on top of the visual cortex learn, while the bot plays, to predict from the image
alone what the direct senses report: the class of each of the 25 cells ahead, whether the sky is
above, where the nearest tree is. Learning is a perceptron (cerebellar climbing-fibre error) that
only changes synapses of the visual neurons active right now. Its agreement with the senses is
tracked: when it is high, the brain can act from vision alone (--blind), and the perceived scene is
also given to the striatum as extra cells either way.
"""
import numpy as np

N_CLS = 6


class SensorTeacher:
    def __init__(self, n_visual=8192):
        self.W = np.zeros((n_visual, 25 * N_CLS + 2 + 5), np.float32)
        self.acc = {"front": 0.0, "grid": 0.0, "sky": 0.0, "tree": 0.0}
        self.n = self.session = 0

    def perceive(self, code):
        s = self.W[code].sum(0)
        grid = s[:25 * N_CLS].reshape(25, N_CLS).argmax(1)
        sky = int(s[25 * N_CLS:25 * N_CLS + 2].argmax())
        tree = int(s[25 * N_CLS + 2:].argmax())
        return grid, sky, tree

    def teach(self, code, grid, sky, tree):
        """code: active visual neurons; grid/sky/tree: what the direct senses say. Returns the percept."""
        pg, ps, pt = self.perceive(code)
        grid = np.minimum(np.asarray(grid), N_CLS - 1)
        upd = np.zeros(self.W.shape[1], np.float32)
        wrong = np.nonzero(pg != grid)[0]
        upd[wrong * N_CLS + grid[wrong]] += 1
        upd[wrong * N_CLS + pg[wrong]] -= 1
        o = 25 * N_CLS
        if ps != sky:
            upd[o + sky] += 1
            upd[o + ps] -= 1
        if pt != tree:
            upd[o + 2 + tree] += 1
            upd[o + 2 + pt] -= 1
        if upd.any():
            self.W[code] += upd
        self.n += 1
        self.session += 1  # agreement is averaged over the last ~200 moments of this session
        k = max(0.005, 1.0 / self.session)
        for key, ok in (("front", pg[7] == grid[7]), ("grid", (pg == grid).mean()), ("sky", ps == sky),
                        ("tree", pt == tree)):
            self.acc[key] += k * (float(ok) - self.acc[key])
        return pg, ps, pt

    def report(self):
        return ", ".join(f"{k} {v * 100:.0f}%" for k, v in self.acc.items())

    def save(self, path):
        np.savez_compressed(path, W=self.W, n=self.n)

    def load(self, path):
        z = np.load(path)
        self.W[:], self.n = z["W"], int(z["n"])
