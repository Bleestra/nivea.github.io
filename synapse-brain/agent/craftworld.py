"""
CraftWorld: a Minecraft-like world with long chains of cause and effect, caves and pits.

Built to test whether a brain can learn *logical chains* and *skills* by itself:
  - trees grow only on the surface (under the sky); the agent is often born deep in a cave
    and has to find the way out (it can see light at the end of the tunnel);
  - sometimes it is born in a pit: walking does not help, it has to dig the walls (dirt) and
    build up under itself;
  - the tech tree: log -> planks -> sticks, crafting table -> wooden pickaxe -> cobblestone ->
    stone pickaxe -> iron ore -> furnace -> iron ingot -> iron pickaxe (9 steps, quantities matter).
Nothing about these rules is given to the agent: it sees a 5x5 egocentric view, whether it sees
the sky, the direction of daylight, the nearest tree (only under the sky) and its inventory.

Actions: 0 forward, 1 turn left, 2 turn right, 3 dig/chop/mine, 4 wait, 5 craft, 6 build up.
Reward (the same for every brain): +1 the first time in a life an item is obtained, -0.01 a step.
"""
import numpy as np

OPEN, TREE, STONE, WATER, OUT, IRON, CAVE, DIAMOND = 0, 1, 2, 4, 5, 6, 7, 8
DIRS = [(-1, 0), (0, 1), (1, 0), (0, -1)]
ITEMS = ["log", "planks", "stick", "table", "wood_pick", "cobble", "stone_pick", "furnace", "iron_ore",
         "iron_ingot", "iron_pick", "dirt"]
DEPTH = {"log": 1, "planks": 2, "stick": 3, "table": 3, "wood_pick": 4, "cobble": 5, "stone_pick": 6,
         "furnace": 6, "iron_ore": 7, "iron_ingot": 8, "iron_pick": 9, "dirt": 0, "diamond": 10, "diamond_pick": 11,
         "book": 0}
ACTIONS = ["forward", "turn_left", "turn_right", "dig", "wait", "craft", "build_up"]
DIAMOND_ITEMS = ITEMS + ["diamond", "diamond_pick", "book"]
DIAMOND_ACTIONS = ACTIONS + ["read"]


class CraftWorld:
    def __init__(self, size=20, seed=0, life=800, p_cave=0.5, p_pit=0.25, diamonds=False, book=""):
        self.n, self.life, self.p_cave, self.p_pit = size, life, p_cave, p_pit
        self.diamonds, self.book = diamonds, book   # diamonds deep in the mountain; a book found after the iron pickaxe
        self.items = DIAMOND_ITEMS if diamonds else ITEMS
        self.just_read = None
        self.rng = np.random.default_rng(seed)
        self.reset()

    # ---------------------------------------------------------------- world
    def reset(self):
        r, n = self.rng, self.n
        g = np.full((n, n), OPEN, np.int64)
        g[r.random((n, n)) < 0.04] = WATER
        side = int(r.integers(4))                               # the mountain is on one side
        yy, xx = np.mgrid[:n, :n]
        coord = [yy, n - 1 - xx, n - 1 - yy, xx][side]           # 0 at the mountain's far edge
        mountain = coord < n // 2
        g[mountain] = STONE
        g[mountain & (r.random((n, n)) < 0.12)] = IRON
        self.core = coord < n // 4                               # the dark heart of the mountain
        if self.diamonds:
            g[self.core & (r.random((n, n)) < 0.08)] = DIAMOND
        surf = np.argwhere(~mountain & (g == OPEN))
        for k in r.choice(len(surf), 14, replace=False):
            g[tuple(surf[k])] = TREE
        # a winding cave from deep inside the mountain to its edge
        out = DIRS[(side + 2) % 4]                              # from the mountain towards the field
        p = np.array([int(yy[mountain].mean()), int(xx[mountain].mean())])
        cave = []
        for _ in range(60):
            cave.append(tuple(p))
            g[tuple(p)] = CAVE
            if not mountain[tuple(p)]:
                break
            d = DIRS[int(r.integers(4))] if r.random() < 0.5 else out
            p = np.clip(p + d, 0, n - 1)
        self.g, self.mountain, self.t = g, mountain, 0
        self.inv = {k: 0 for k in self.items}
        self.got = set()
        self.pit = False
        u = r.random()
        if u < self.p_cave:
            self.pos = cave[0]
        else:
            self.pos = tuple(surf[int(r.integers(len(surf)))])
            while self.g[self.pos] != OPEN:
                self.pos = tuple(surf[int(r.integers(len(surf)))])
            self.pit = u < self.p_cave + self.p_pit
        self.born_in = "cave" if u < self.p_cave else "pit" if self.pit else "surface"
        self.dir = int(r.integers(4))
        return self.obs()

    def cell(self, y, x):
        return self.g[y, x] if 0 <= y < self.n and 0 <= x < self.n else OUT

    def sky(self):
        return int(self.g[self.pos] == OPEN)

    def _toward(self, mask):
        """Direction (1 ahead, 2 right, 3 behind, 4 left) and distance bucket of the nearest cell in mask."""
        ys, xs = np.nonzero(mask)
        if len(ys) == 0:
            return 0
        d = np.abs(ys - self.pos[0]) + np.abs(xs - self.pos[1])
        k = int(np.argmin(d))
        dy, dx = ys[k] - self.pos[0], xs[k] - self.pos[1]
        fy, fx = DIRS[self.dir]
        ry, rx = DIRS[(self.dir + 1) % 4]
        ahead, right = dy * fy + dx * fx, dy * ry + dx * rx
        dirc = (1 if ahead > 0 else 3) if abs(ahead) >= abs(right) else (2 if right > 0 else 4)
        dist = int(d[k])
        return dirc * 4 + (0 if dist <= 1 else 1 if dist <= 3 else 2 if dist <= 8 else 3)

    # ---------------------------------------------------------------- senses
    def obs(self):
        dy, dx = DIRS[self.dir]
        ry, rx = DIRS[(self.dir + 1) % 4]
        v = np.empty(25, np.int64)
        for a in range(5):
            for b in range(5):
                v[a * 5 + b] = self.cell(self.pos[0] + dy * a + ry * (b - 2), self.pos[1] + dx * a + rx * (b - 2))
        if self.pit:  # in a pit you see only its walls
            v[:] = OUT
            v[2] = OPEN
        sky = self.sky() and not self.pit
        tree = self._toward(self.g == TREE) if sky else 0      # trees are visible only under the sky
        light = 0 if sky else self._toward(self.g == OPEN)     # daylight at the end of the tunnel
        inv = [min(self.inv[k], 3) for k in self.items]
        drives = [int(sky), int(self.pit), light] + inv
        return v, min(self.inv["log"], 7), tree, None, drives

    def state(self):
        """What the agent knows about itself right now (for the brain's concept neurons)."""
        s = {"have:" + k: c for k, c in self.inv.items()}
        s["sky"] = int(self.sky() and not self.pit)
        s["free"] = int(not self.pit)
        s["in_pit"] = int(self.pit)
        if self.diamonds:
            s["deep"] = int(bool(self.core[self.pos]))
            s["see:diamond"] = int((self.obs()[0] == DIAMOND).any())
        return s

    # ---------------------------------------------------------------- physics
    def _craft(self):
        i = self.inv

        def can(**need):
            return all(i[k] >= v for k, v in need.items())

        recipes = [("diamond_pick", i.get("diamond_pick", 1) == 0 and can(table=1, diamond=3, stick=2), dict(diamond=3, stick=2)),
                   ("iron_pick", i["iron_pick"] == 0 and can(table=1, iron_ingot=3, stick=2), dict(iron_ingot=3, stick=2)),
                   ("iron_ingot", i["iron_ingot"] < 3 and can(furnace=1, iron_ore=1, planks=1), dict(iron_ore=1, planks=1)),
                   ("furnace", i["furnace"] == 0 and can(table=1, cobble=8), dict(cobble=8)),
                   ("stone_pick", i["stone_pick"] == 0 and can(table=1, cobble=3, stick=2), dict(cobble=3, stick=2)),
                   ("wood_pick", i["wood_pick"] == 0 and can(table=1, planks=3, stick=2), dict(planks=3, stick=2)),
                   ("table", i["table"] == 0 and can(planks=4), dict(planks=4)),
                   ("stick", i["stick"] < 4 and can(planks=2), dict(planks=2)),
                   ("planks", i["planks"] < 12 and can(log=1), dict(log=1))]
        for name, ok, cost in recipes:
            if ok:
                for k, v in cost.items():
                    i[k] -= v
                i[name] += 4 if name in ("planks", "stick") else 1
                return name
        return None

    def step(self, act):
        self.t += 1
        dy, dx = DIRS[self.dir]
        fy, fx = self.pos[0] + dy, self.pos[1] + dx
        front = self.cell(fy, fx)
        new = None
        if act == 0 and not self.pit and front in (OPEN, CAVE):
            self.pos = (fy, fx)
        elif act == 1:
            self.dir = (self.dir - 1) % 4
        elif act == 2:
            self.dir = (self.dir + 1) % 4
        elif act == 3:
            if self.pit:
                self.inv["dirt"] += 1
                new = "dirt"
            elif front == TREE:
                self.inv["log"] += 1
                new = "log"
                self.g[fy, fx] = OPEN
                free = np.argwhere((self.g == OPEN) & ~self.mountain)
                self.g[tuple(free[int(self.rng.integers(len(free)))])] = TREE  # a tree grows elsewhere
            elif front == STONE and self.inv["wood_pick"]:
                self.inv["cobble"] += 1
                new = "cobble"
                self.g[fy, fx] = CAVE
            elif front == DIAMOND and self.inv["iron_pick"]:
                self.inv["diamond"] += 1
                new = "diamond"
                self.g[fy, fx] = CAVE
            elif front == IRON and self.inv["stone_pick"]:
                self.inv["iron_ore"] += 1
                new = "iron_ore"
                self.g[fy, fx] = CAVE
        elif act == 5:
            new = self._craft()
        elif act == 7 and self.inv.get("book"):
            self.just_read = self.book                          # reading: the text goes to the language areas
        elif act == 6 and self.pit and (self.inv["dirt"] or self.inv["cobble"]):
            self.inv["dirt" if self.inv["dirt"] else "cobble"] -= 1
            self.pit = False
        if new == "iron_pick" and self.diamonds and not self.inv["book"]:
            self.inv["book"] = 1                                # ... and there, next to the anvil, lies a book
        r = -0.01
        if new and new not in self.got:
            self.got.add(new)
            r += 1.0
        return self.obs(), r, self.t >= self.life

    def tech(self):
        return max([DEPTH[k] for k in self.got] + [0])
