"""
LifeWorld: a small Minecraft-like world to grow up in.

Everything a child needs to develop feelings about: days and nights with sunsets and dawns, a sky to
look at, hunger and food of different taste (fish, apples, rotten flesh), fishing, wild cats that can
be tamed with fish, zombies at night (they cannot walk through blocks), creepers that hiss and blow
up whatever is near them (blocks, chests with their contents, cats), and a caregiver who comes by,
speaks in a warm, alarmed or scolding tone, fights zombies, gives gifts and sometimes plays with the
cat. The world persists when the agent dies: what it built stays, its inventory is lost.

Nothing in the world rewards building, sunsets or cats. The agent gets only what a body gets:
senses, pain, taste, hunger, tiredness, sounds. What it comes to want is up to its brain.

Actions: forward, turn_left, turn_right, hit (a being in front, else dig the block), place (a block
in front), eat, use (fish at water / feed a cat / put things in a chest / greet the caregiver),
take (from a chest), make_chest, sleep, wait, look_up (see the whole sky), back.
"""
import numpy as np

GRASS, TREE, STONE, WATER, BLOCK, CHEST, OUT = range(7)
ZOMBIE, CREEPER, CAT, MYCAT, CARER = 7, 8, 9, 10, 11
SOLID = (TREE, STONE, WATER, BLOCK, CHEST, OUT)
DIRS = [(-1, 0), (0, 1), (1, 0), (0, -1)]
ACTIONS = ["forward", "turn_left", "turn_right", "hit", "place", "eat", "use", "take", "make_chest",
           "sleep", "wait", "look_up", "back"]
DAY = 240                      # steps per day
SUNSET, NIGHT, DAWN = 150, 175, 225
FOOD = {"apple": 4, "fish": 6, "rotten_flesh": 4}
TASTE = {"apple": 0.5, "fish": 1.0, "rotten_flesh": -0.6}   # the tongue's receptors (innate)


def phase(t):
    x = t % DAY
    return "day" if x < SUNSET else "sunset" if x < NIGHT else "night" if x < DAWN else "dawn"


class Being:
    def __init__(self, kind, pos, hp, uid):
        self.kind, self.pos, self.hp, self.id = kind, pos, hp, uid
        self.fuse, self.tamed, self.cool, self.away = 0, False, 0, 0


class LifeWorld:
    def __init__(self, size=24, seed=0, mobs=True, carer=True, hut=True, home_days=25, sunset_structure=True):
        self.n, self.mobs, self.with_carer, self.home_days = size, mobs, carer, home_days
        self.sunset_structure = sunset_structure     # False: sunsets are random colour noise (a control)
        self.rng = np.random.default_rng(seed)
        r, n = self.rng, size
        g = np.full((n, n), GRASS, np.int64)
        g[r.random((n, n)) < 0.07] = TREE
        cy, cx = r.integers(4, n - 4, 2)
        yy, xx = np.mgrid[:n, :n]
        g[(yy - cy) ** 2 + (xx - cx) ** 2 <= 7] = WATER              # a pond
        sy, sx = r.integers(3, n - 3, 2)
        g[(np.abs(yy - sy) <= 2) & (np.abs(xx - sx) <= 2) & (r.random((n, n)) < 0.7) & (g == GRASS)] = STONE
        self.g = g
        self.owner = np.zeros((n, n), np.int64)      # 1 = placed by the agent (the world knows; the agent must remember)
        self.chests = {}                             # (y, x) -> {item: count}
        self.stars = r.random(8) < 0.3               # the night sky of this world
        self.beings, self.uid, self.carer = [], 0, None
        for _ in range(3):
            self._spawn(CAT, near_water=True)
        self.hut = None
        if hut:                                      # the caregiver's home: the child is born there
            hy, hx = (int(v) for v in r.integers(4, n - 4, 2))
            while (g[hy - 2:hy + 3, hx - 2:hx + 3] == WATER).any():
                hy, hx = (int(v) for v in r.integers(4, n - 4, 2))
            g[hy - 2:hy + 3, hx - 2:hx + 3] = BLOCK
            g[hy - 1:hy + 2, hx - 1:hx + 2] = GRASS
            self.hut, self.door = (hy, hx), (hy + 2, hx)
            g[self.door] = GRASS
        self.spawn_point = self.hut if self.hut else self._free()
        self.pos, self.dir = self.spawn_point, 0
        self.t = 10
        self.hp, self.hunger, self.fatigue, self.nausea = 20, 20, 0, 0
        self.inv = {"log": 0, "cobble": 0, "apple": 0, "fish": 0, "rotten_flesh": 0}
        self.got_ever = set()
        self.sunset_phi = 0.0
        self.deaths = 0
        self.ev = self._new_events()

    # ---------------------------------------------------------------- helpers
    def _new_events(self):
        return {"deaths": [], "hurt": [], "destroyed": [], "ate": None, "caught": False, "tamed": None,
                "tone": 0, "gift": False, "carer_did": None, "explosion": None, "sounds": set(),
                "died": False, "slept": False, "placed": None, "got": [], "cat_with_carer": False}

    def cell(self, p):
        y, x = p
        return self.g[y, x] if 0 <= y < self.n and 0 <= x < self.n else OUT

    def being_at(self, p):
        for b in self.beings:
            if b.pos == p:
                return b
        if self.carer is not None and self.carer.pos == p:
            return self.carer
        return None

    def _free(self, far_from=None, dmin=0, near_water=False):
        for _ in range(500):
            p = tuple(int(v) for v in self.rng.integers(self.n, size=2))
            if self.g[p] != GRASS or self.being_at(p) is not None:
                continue
            if far_from is not None and abs(p[0] - far_from[0]) + abs(p[1] - far_from[1]) < dmin:
                continue
            if near_water and not any(self.cell((p[0] + dy, p[1] + dx)) == WATER for dy, dx in DIRS):
                continue
            return p
        return None

    def _spawn(self, kind, near_water=False):
        p = self._free(getattr(self, "pos", None), 7 if kind in (ZOMBIE, CREEPER) else 0, near_water)
        if p is None:
            return None
        self.uid += 1
        b = Being(kind, p, {ZOMBIE: 3, CREEPER: 2, CAT: 4}[kind], self.uid)
        self.beings.append(b)
        return b

    def front(self):
        dy, dx = DIRS[self.dir]
        return (self.pos[0] + dy, self.pos[1] + dx)

    def dist(self, a, b):
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

    def walls(self):
        y, x = self.pos
        return sum(self.cell((y + dy, x + dx)) in SOLID for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx)

    def _step_toward(self, b, target, passable=(GRASS,)):
        best, bd = None, abs(b.pos[0] - target[0]) + abs(b.pos[1] - target[1])
        for dy, dx in DIRS:
            p = (b.pos[0] + dy, b.pos[1] + dx)
            if self.cell(p) in passable and self.being_at(p) is None and p != self.pos:
                d = abs(p[0] - target[0]) + abs(p[1] - target[1])
                if d < bd:
                    best, bd = p, d
        if best is not None:
            b.pos = best

    def _wander(self, b):
        dy, dx = DIRS[int(self.rng.integers(4))]
        p = (b.pos[0] + dy, b.pos[1] + dx)
        if self.cell(p) == GRASS and self.being_at(p) is None and p != self.pos:
            b.pos = p

    def _gain(self, item, k=1):
        self.inv[item] = self.inv.get(item, 0) + k
        self.ev["got"].append(item)
        if item not in self.got_ever:
            self.got_ever.add(item)
            if self.carer is not None and self.dist(self.carer.pos, self.pos) <= 5:
                self.ev["tone"] = 1                               # "well done!"

    def _hurt_self(self, dmg, cause):
        self.hp -= dmg
        self.ev["hurt"].append(("self", 0, dmg, cause))

    def _kill(self, b, cause):
        self.beings.remove(b)
        seen = self.dist(b.pos, self.pos) <= 6
        name = ("mycat" if b.tamed else "cat") if b.kind == CAT else {ZOMBIE: "zombie", CREEPER: "creeper"}[b.kind]
        self.ev["deaths"].append((name, b.id, b.tamed, cause, seen))
        if b.kind == ZOMBIE and cause in ("self", "carer"):
            if cause == "self":
                self._gain("rotten_flesh")

    # ---------------------------------------------------------------- the creeper
    def explode(self, at, cause="creeper"):
        """Blow up everything within 2 cells of `at` (also used by tests to stage a disaster)."""
        lost = []
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                p = (at[0] + dy, at[1] + dx)
                c = self.cell(p)
                if c in (BLOCK, CHEST):
                    lost.append((p, int(c), int(self.owner[p]), dict(self.chests.get(p, {}))))
                    self.g[p] = GRASS
                    self.owner[p] = 0
                    self.chests.pop(p, None)
        self.ev["destroyed"] += [(p, c, own, items, cause) for p, c, own, items in lost]
        d = self.dist(at, self.pos)
        if d <= 2:
            self._hurt_self(10 if d <= 1 else 5, cause)
        for b in list(self.beings):
            if self.dist(b.pos, at) <= 2 and b.kind != CREEPER:
                self._kill(b, cause)
        if self.carer is not None and self.dist(self.carer.pos, at) <= 2:
            self.ev["hurt"].append(("carer", -1, 4, cause))
        if self.dist(at, self.pos) <= 16:
            self.ev["sounds"].add("boom")
        self.ev["explosion"] = at

    # ---------------------------------------------------------------- the caregiver
    def _carer_step(self):
        day = self.t // DAY
        if self.carer is None and self.with_carer and day < self.home_days:
            p = self._free() if self.hut is None else (self.hut[0], self.hut[1] + 1)
            if p is not None and self.being_at(p) is None and p != self.pos:
                self.carer = Being(CARER, p, 20, -1)
                self.carer.away, self.carer.holds = 10 ** 9, self.rng.choice(["nothing", "fish", "gem"])
            return
        if self.carer is not None and day >= self.home_days and self.carer.away > 10 ** 8:
            self.carer = None                                          # grown up: the caregiver moves out
            if self.hut is not None and self.g[self.door] == BLOCK:
                self.g[self.door] = GRASS
            return
        if self.carer is None:
            visit = 0.3 if day < 10 else 0.15 if day < 60 else 0.05   # parents are around all childhood
            if self.with_carer and phase(self.t) in ("day", "sunset") and self.rng.random() < visit / 20:
                p = self._free()
                if p is not None:
                    self.carer = Being(CARER, p, 20, -1)
                    self.carer.away = int(self.rng.integers(60, 200))
                    self.carer.holds = self.rng.choice(["nothing", "fish", "gem"])
            return
        c = self.carer
        c.away -= 1
        ph = phase(self.t)
        if self.hut is not None and c.away > 10 ** 8:                  # living at home
            inside = lambda p: max(abs(p[0] - self.hut[0]), abs(p[1] - self.hut[1])) <= 1
            if ph in ("sunset", "night") and not inside(c.pos):
                self._step_toward(c, self.hut)
                if self.dist(c.pos, self.door) <= 1 and self.g[self.door] == GRASS:
                    c.pos = (self.hut[0] + 1, self.hut[1])
                return
            if ph == "night" and inside(c.pos):
                if inside(self.pos) and self.g[self.door] == GRASS and self.being_at(self.door) is None:
                    self.g[self.door] = BLOCK                          # the caregiver closes the door
                return
            if ph in ("dawn", "day") and self.g[self.door] == BLOCK:
                self.g[self.door] = GRASS                              # ... and opens it in the morning
            if ph == "day" and inside(c.pos) and self.t % 3 == 0:
                c.pos = (self.door[0] + 1, self.door[1]) if self.cell((self.door[0] + 1, self.door[1])) == GRASS \
                    and self.being_at((self.door[0] + 1, self.door[1])) is None else c.pos
        if c.away <= 0:
            self.carer = None
            return
        foe = [b for b in self.beings if b.kind in (ZOMBIE, CREEPER) and self.dist(b.pos, self.pos) <= 5]
        if foe:
            self.ev["tone"] = self.ev["tone"] or 2                    # alarmed: "watch out!"
            f = foe[0]
            if self.dist(c.pos, f.pos) <= 1:
                f.hp -= 2
                if f.hp <= 0:
                    self._kill(f, "carer")
                    self.ev["carer_did"] = "killed"
            else:
                self._step_toward(c, f.pos)
        elif self.dist(c.pos, self.pos) > 3:
            self._step_toward(c, self.pos)
        else:
            self._wander(c)
        if self.rng.random() < 0.006 and self.dist(c.pos, self.pos) <= 3:
            self.inv["fish"] += 1
            self.ev["gift"] = True
            self.ev["tone"] = self.ev["tone"] or 1

    # ---------------------------------------------------------------- one moment
    def step(self, act):
        self.ev = self._new_events()
        ev = self.ev
        self.t += 1
        ph = phase(self.t)
        if self.t % DAY == SUNSET:
            self.sunset_phi = float(self.rng.normal(0, 0.4))           # every sunset is a bit different
        if self.fatigue > 380 and self.rng.random() < 0.3:
            act = 10                                                   # too tired: the body does not obey
        f = self.front()
        fc = self.cell(f)
        fb = self.being_at(f)
        if act == 0 and fc == GRASS and fb is None:
            self.pos = f
        elif act == 12:
            dy, dx = DIRS[self.dir]
            p = (self.pos[0] - dy, self.pos[1] - dx)
            if self.cell(p) == GRASS and self.being_at(p) is None:
                self.pos = p
        elif act == 1:
            self.dir = (self.dir - 1) % 4
        elif act == 2:
            self.dir = (self.dir + 1) % 4
        elif act == 3:
            if fb is not None and fb.kind == CARER:
                ev["tone"] = 3                                         # "don't hit me!"
            elif fb is not None:
                fb.hp -= 1
                ev["hurt"].append((("mycat" if fb.tamed else "cat") if fb.kind == CAT else
                                   {ZOMBIE: "zombie", CREEPER: "creeper"}[fb.kind], fb.id, 1, "self"))
                if fb.kind == CAT and self.carer is not None and self.dist(self.carer.pos, self.pos) <= 6:
                    ev["tone"] = 3                                     # "don't hurt the cat!"
                if fb.hp <= 0:
                    self._kill(fb, "self")
            elif fc == TREE:
                self.g[f] = GRASS
                self._gain("log")
                if self.rng.random() < 0.35:
                    self._gain("apple")
                q = self._free()
                if q is not None:
                    self.g[q] = TREE
            elif fc == STONE:
                self.g[f] = GRASS
                self._gain("cobble")
            elif fc in (BLOCK, CHEST):
                own = int(self.owner[f])
                items = self.chests.pop(f, {})
                ev["destroyed"].append((f, int(fc), own, dict(items), "self"))
                for k, v in items.items():
                    self.inv[k] = self.inv.get(k, 0) + v
                self.g[f], self.owner[f] = GRASS, 0
                self._gain("cobble" if fc == BLOCK else "log")
        elif act == 4 and fc == GRASS and fb is None and (self.inv["cobble"] or self.inv["log"]):
            self.inv["cobble" if self.inv["cobble"] else "log"] -= 1
            self.g[f], self.owner[f] = BLOCK, 1
            ev["placed"] = f
        elif act == 5:
            foods = [k for k in FOOD if self.inv.get(k)]
            if foods and self.hunger < 20:
                k = foods[int(self.rng.integers(len(foods)))]
                self.inv[k] -= 1
                self.hunger = min(20, self.hunger + FOOD[k])
                ev["ate"] = k
                if k == "rotten_flesh" and self.rng.random() < 0.8:
                    self.nausea = 30
        elif act == 6:
            if fc == WATER and fb is None:
                if self.rng.random() < 0.3:
                    self._gain("fish")
                    ev["caught"] = True
            elif fb is not None and fb.kind == CAT and self.inv["fish"]:
                self.inv["fish"] -= 1
                if not fb.tamed:
                    fb.tamed = True
                    ev["tamed"] = fb.id
                ev["sounds"].add("purr")
            elif fb is not None and fb.kind == CARER:
                ev["tone"] = 1                                         # a hug
            elif fc == CHEST:
                box = self.chests.setdefault(f, {})
                for k in list(self.inv):
                    if self.inv[k]:
                        box[k] = box.get(k, 0) + self.inv[k]
                        self.inv[k] = 0
        elif act == 7 and fc == CHEST:
            for k, v in self.chests.get(f, {}).items():
                self.inv[k] = self.inv.get(k, 0) + v
            self.chests[f] = {}
        elif act == 8 and fc == GRASS and fb is None and self.inv["log"] >= 4:
            self.inv["log"] -= 4
            self.g[f], self.owner[f] = CHEST, 1
            self.chests[f] = {}
            ev["placed"] = f
        elif act == 9 and ph == "night":
            ev["slept"] = True
            self.fatigue = 0
            for _ in range(8):                                         # time flies while asleep
                self._world_tick(asleep=True)
                self.t += 1
        self.fatigue += 1
        self._world_tick()
        # the body
        if self.t % (8 if self.nausea else 15) == 0:
            self.hunger = max(0, self.hunger - 1)
        self.nausea = max(0, self.nausea - 1)
        if self.hunger == 0 and self.t % 10 == 0:
            self._hurt_self(1, "hunger")
        if self.hunger >= 16 and self.t % 12 == 0:
            self.hp = min(20, self.hp + 1)
        if self.hp <= 0:
            ev["died"] = True
            self.deaths += 1
            self.hp, self.hunger, self.fatigue, self.nausea = 20, 20, 0, 0
            self.inv = {k: 0 for k in self.inv}
            self.pos = self.spawn_point if self.being_at(self.spawn_point) is None else self._free()
        return self.obs(look=act == 11)

    def _world_tick(self, asleep=False):
        ev, ph = self.ev, phase(self.t)
        if self.mobs:
            nz = sum(b.kind == ZOMBIE for b in self.beings)
            nc = sum(b.kind == CREEPER for b in self.beings)
            if ph == "night" and nz < 2 and self.rng.random() < 0.03:
                self._spawn(ZOMBIE)
            if nc < 1 and self.rng.random() < (0.012 if ph == "night" else 0.0015):
                self._spawn(CREEPER)
        if sum(b.kind == CAT for b in self.beings) < 3 and self.rng.random() < 0.002:
            self._spawn(CAT, near_water=True)
        for b in list(self.beings):
            if b not in self.beings:
                continue
            d = self.dist(b.pos, self.pos)
            if b.kind == ZOMBIE:
                if ph == "day":
                    self._kill(b, "sun")
                    continue
                if d <= 5:
                    ev["sounds"].add("groan")
                if abs(b.pos[0] - self.pos[0]) + abs(b.pos[1] - self.pos[1]) == 1:
                    b.cool -= 1
                    if b.cool <= 0:
                        self._hurt_self(2, "zombie")
                        b.cool = 4
                elif self.t % 2 == 0:
                    self._step_toward(b, self.pos)
            elif b.kind == CREEPER:
                if d <= 1 or (b.fuse and d <= 2):
                    b.fuse = b.fuse + 1 if b.fuse else 1
                    ev["sounds"].add("hiss")
                    if b.fuse > 3:
                        self.beings.remove(b)
                        self.explode(b.pos)
                        continue
                else:
                    b.fuse = 0
                    if self.t % 2 == 0:
                        self._step_toward(b, self.pos) if d <= 12 else self._wander(b)
            elif b.kind == CAT:
                if b.tamed:
                    if b.away > 0 and self.carer is not None:
                        b.away -= 1
                        ev["cat_with_carer"] = True
                        if self.dist(b.pos, self.carer.pos) > 1:
                            self._step_toward(b, self.carer.pos)
                    elif d > 2 and self.t % 2 == 0:
                        self._step_toward(b, self.pos)
                    elif d <= 1 and self.rng.random() < 0.15:
                        ev["sounds"].add("purr")
                    if self.carer is not None and b.away == 0 and self.rng.random() < 0.004:
                        b.away = 25                                   # the cat goes to play with the caregiver
                elif self.inv["fish"] and d <= 8 and self.t % 2 == 0:
                    self._step_toward(b, self.pos)                     # cats come to whoever holds fish (as in Minecraft)
                elif self.t % 3 == 0:
                    self._wander(b)
        self._carer_step()

    # ---------------------------------------------------------------- senses
    def sky(self, look):
        """What the eyes see of the sky: 8 colour bins when looking up, else one coarse bin.
        Colours: 0 dark, 1 blue, 2 white (cloud), 3 yellow, 4 orange, 5 red, 6 pink/purple, 7 star."""
        x, ph = self.t % DAY, phase(self.t)
        if ph == "day":
            v = np.where(self.rng.random(8) < 0.25, 2, 1)             # clouds: random every time
        elif ph == "night":
            v = np.where(self.stars, 7, 0)
        elif ph == "sunset":
            s = (x - SUNSET) / (NIGHT - SUNSET)
            v = np.clip(3 + (np.arange(8) / 8 * 3 + s * 2 + self.sunset_phi).astype(int), 3, 6)
            if not self.sunset_structure:
                v = self.rng.integers(3, 7, 8)
        else:
            s = (x - DAWN) / (DAY - DAWN)
            v = np.clip(6 - (np.arange(8) / 8 * 2 + s * 2).astype(int), 4, 6)
        if look:
            return v.astype(np.int64)
        return np.array([int(np.bincount(v, minlength=8).argmax())], np.int64)

    def view(self):
        dy, dx = DIRS[self.dir]
        ry, rx = DIRS[(self.dir + 1) % 4]
        v = np.empty(25, np.int64)
        for a in range(5):
            for b in range(5):
                p = (self.pos[0] + dy * a + ry * (b - 2), self.pos[1] + dx * a + rx * (b - 2))
                being = self.being_at(p)
                if being is None:
                    v[a * 5 + b] = self.cell(p)
                else:
                    v[a * 5 + b] = MYCAT if (being.kind == CAT and being.tamed) else being.kind
        return v

    def obs(self, look=False):
        return {"view": self.view(), "sky": self.sky(look), "walls": self.walls(),
                "hp": self.hp, "hunger": self.hunger, "fatigue": self.fatigue, "nausea": int(self.nausea > 0),
                "inv": dict(self.inv), "ev": self.ev, "t": self.t, "pos": self.pos, "dir": self.dir,
                "carer_holds": getattr(self.carer, "holds", None) if self.carer is not None else None,
                "near": [(("mycat" if b.tamed else "cat") if b.kind == CAT else
                          {ZOMBIE: "zombie", CREEPER: "creeper"}[b.kind], b.id, self.dist(b.pos, self.pos))
                         for b in self.beings if self.dist(b.pos, self.pos) <= 6]
                + ([("carer", -1, self.dist(self.carer.pos, self.pos))]
                   if self.carer is not None and self.dist(self.carer.pos, self.pos) <= 6 else [])}
