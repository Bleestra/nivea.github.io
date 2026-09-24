"""
MiniCraft: a tiny Minecraft-like world for testing real-time learning before the real game.

16x16 grid. Cells: 0 grass, 1 tree, 2 stone, 3 lava, 4 water (impassable).
The agent sees a 5x5 window in front of it (egocentric, rotated with its heading).
Actions: 0 forward, 1 turn left, 2 turn right, 3 mine the block in front, 4 wait.
Rewards: +1 wood (mining a tree; the tree regrows somewhere else), +0.3 stone,
-1 stepping into lava (respawn), -0.01 per step. Episodes last 300 steps.
"""
import numpy as np

GRASS, TREE, STONE, LAVA, WATER = range(5)
N_TYPES = 6  # + 5 = outside the world
DIRS = [(-1, 0), (0, 1), (1, 0), (0, -1)]  # N E S W


class MiniCraft:
    def __init__(self, size=16, seed=0, episode=300):
        self.n, self.episode = size, episode
        self.rng = np.random.default_rng(seed)
        self.reset()

    def reset(self):
        r = self.rng
        g = r.choice(5, (self.n, self.n), p=[0.62, 0.14, 0.12, 0.06, 0.06])
        self.g = g
        self.pos = self._free()
        self.dir = int(r.integers(4))
        self.t = 0
        self.inv = 0
        return self.obs()

    def _free(self):
        while True:
            p = tuple(self.rng.integers(self.n, size=2))
            if self.g[p] == GRASS:
                return p

    def cell(self, y, x):
        return self.g[y, x] if 0 <= y < self.n and 0 <= x < self.n else 5

    def obs(self):
        """5x5 cell types, rows = distance ahead (0..4), cols = left..right; plus inventory."""
        dy, dx = DIRS[self.dir]
        ry, rx = DIRS[(self.dir + 1) % 4]  # to the right
        v = np.empty(25, np.int64)
        for a in range(5):
            for b in range(5):
                v[a * 5 + b] = self.cell(self.pos[0] + dy * a + ry * (b - 2), self.pos[1] + dx * a + rx * (b - 2))
        return v, min(self.inv, 7)

    def step(self, act):
        self.t += 1
        r = -0.01
        dy, dx = DIRS[self.dir]
        fy, fx = self.pos[0] + dy, self.pos[1] + dx
        front = self.cell(fy, fx)
        if act == 0:
            if front in (GRASS, LAVA):
                self.pos = (fy, fx)
                if front == LAVA:
                    r -= 1.0
                    self.pos = self._free()
        elif act == 1:
            self.dir = (self.dir - 1) % 4
        elif act == 2:
            self.dir = (self.dir + 1) % 4
        elif act == 3 and front in (TREE, STONE):
            r += 1.0 if front == TREE else 0.3
            self.inv += 1
            self.g[fy, fx] = GRASS
            if front == TREE:  # a tree regrows elsewhere
                p = self._free()
                self.g[p] = TREE
        done = self.t >= self.episode
        return self.obs(), r, done
