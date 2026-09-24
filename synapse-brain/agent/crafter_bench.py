"""
Crafter (Hafner 2021): an open 2D Minecraft with 22 achievements, from collecting wood to collecting
a diamond - a public yardstick for how far an agent gets in a Minecraft-like world by itself.

The whole brain (habits + mind + limbic system) plays through the 17 motor actions of the game
(move, do, sleep, place, make). Nothing about the game is written into the brain. Its senses: the
9x7 area around it as block/creature names (the same area the picture shows - published agents
see pixels instead, which is harder), what it faces, what it carries, health/food/drink/energy,
daylight. The game's achievements are felt as joy (like Minecraft's advancement messages).

Score (as in the paper): success rate of each achievement over all episodes of the run,
S = exp(mean(ln(1 + s_i))) - 1 (percent). Published at 1M steps: random 1.6, PPO 4.6,
Rainbow 4.3, DreamerV2 10.0, DreamerV3 14.5; human experts 50.5.

    python3 crafter_bench.py [steps=1000000] [seed=0]
"""
import sys
import time
from collections import Counter

import crafter
import numpy as np

from brain_agent import MASK, _h
from child import Child
from limbic import NAMES

CLS = ['none', 'water', 'grass', 'stone', 'path', 'sand', 'tree', 'lava', 'coal', 'iron', 'diamond', 'table',
       'furnace', 'player', 'cow', 'zombie', 'skeleton', 'arrow', 'plant']
IMPORTANT = [1, 3, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 18]
ITEMS = ['sapling', 'wood', 'stone', 'coal', 'iron', 'diamond', 'wood_pickaxe', 'stone_pickaxe', 'iron_pickaxe',
         'wood_sword', 'stone_sword', 'iron_sword']
WALK = {2, 4, 5}
KIND = {14: "animal", 15: "zombie", 16: "hostile", 17: "hostile"}


def crafter_cells(self, obs):
    """Sensory cells for Crafter (replaces the Minecraft ones; same kind of hashed sparse code)."""
    v, facing, nearest, inv, vit, feat, light = obs[0][8:], obs[1], obs[2], obs[3], obs[4], obs[5], obs[6]
    zdir = nearest.get(15, 0) or nearest.get(16, 0)
    c = [_h(2, facing), _h(3, 15, zdir)]                                  # [0] facing, [1] threat: the amygdala's cues
    c += [_h(1, i, int(x)) for i, x in enumerate(v)]
    c += [_h(3, k, d) for k, d in nearest.items()]
    c += [_h(4, i, x) for i, x in enumerate(inv)]
    c += [_h(5, i, x) for i, x in enumerate(vit)]
    tier = 3 if inv[8] else 2 if inv[7] else 1 if inv[6] else 0
    c.append(_h(6, facing, min(inv[1], 3), min(inv[2], 3), tier, min(inv[3], 1), min(inv[4], 1)))
    c.append(_h(9, facing, tier))
    c += [_h(10, k, d, tier) for k, d in nearest.items() if k in (6, 3, 8, 9, 10, 11, 12)]
    c += [_h(11, facing, i, x) for i, x in enumerate(vit)]
    c.append(_h(7, light))
    c += [_h(13, i, x) for i, x in enumerate(feat)]
    c.append(_h(8))
    return np.array(c, np.int64)


class CrafterChild(Child):
    def __init__(self, seed=0):
        super().__init__(17, seed=seed, taste={"food": 0.8, "water": 0.5}, items=ITEMS, eat_action=-1, wait_action=0,
                         kinds=["zombie", "hostile", "animal"], n_front=len(CLS))
        self.mind.flat.cells = crafter_cells.__get__(self.mind.flat)
        self.mind.flat.cue = lambda cells: cells[[0, 1]]
        self.mind.min_desire = float(__import__("os").environ.get("MIN_DESIRE", "0.3"))
        self.mind.flat.use_fear = __import__("os").environ.get("FEAR", "1") == "1"

    def senses(self, o):
        return o["obs"][:6] + (o["obs"][6],)

    def concepts(self, o):
        return o["state"]


class Body:
    """Turns Crafter's state into senses, concepts and the limbic system's report."""

    def __init__(self):
        self.prev = None

    def read(self, env, info, done, new_ach):
        p = env._player
        sem = info["semantic"]
        x, y = info["player_pos"]
        H, W = sem.shape
        view = np.zeros((9, 7), np.int64)
        for i in range(9):
            for j in range(7):
                a, b = x - 4 + i, y - 3 + j
                view[i, j] = sem[a, b] if 0 <= a < H and 0 <= b < W else 0
        fx, fy = x + p.facing[0], y + p.facing[1]
        facing = int(sem[fx, fy]) if 0 <= fx < H and 0 <= fy < W else 0
        nearest = {}
        for k in IMPORTANT:
            pts = np.argwhere(view == k)
            if len(pts):
                d = np.abs(pts[:, 0] - 4) + np.abs(pts[:, 1] - 3)
                q = pts[int(np.argmin(d))]
                dx, dy = int(np.sign(q[0] - 4)), int(np.sign(q[1] - 3))
                nearest[k] = (dx + 1) * 3 + (dy + 1) + 9 * min(int(d.min()) // 2, 3) + 1
        inv = info["inventory"]
        invv = [min(inv[k], 5) for k in ITEMS]
        vit = [inv["health"] // 3, inv["food"] // 3, inv["drink"] // 3, inv["energy"] // 3]
        light = int(env._world.daylight * 3)
        v = np.concatenate([[0] * 7, [facing], view.ravel()])
        feat = [2, 0, 0, 0, 0, 0, 0]
        obs = (v, facing, nearest, invv, vit, feat, light)
        st = {"have:" + k: inv[k] for k in ITEMS}
        for k in IMPORTANT:
            st["see:" + CLS[k]] = int((view == k).any())
        st["facing:" + CLS[facing]] = 1
        st.update({"fed": int(inv["food"] >= 5), "hydrated": int(inv["drink"] >= 5), "rested": int(inv["energy"] >= 5),
                   "healthy": int(inv["health"] >= 6), "dark": int(env._world.daylight < 0.3)})
        for k, n in info["achievements"].items():
            st["ach:" + k] = int(n > 0)
        # the limbic system's report
        prev = self.prev or dict(inv)
        hurt, got = [], [k for k in ITEMS if inv[k] > prev.get(k, 0)]
        near = []
        for obj in env._world.objects:
            d = abs(obj.pos[0] - x) + abs(obj.pos[1] - y)
            k = {"Cow": "animal", "Zombie": "zombie", "Skeleton": "hostile", "Arrow": "hostile"}.get(type(obj).__name__)
            if k and d <= 6:
                near.append((k, id(obj) % 100000, int(d)))
        if inv["health"] < prev["health"]:
            cause = min(((k, dd) for k, _, dd in near if k in ("zombie", "hostile")), key=lambda t: t[1], default=("hunger", 0))[0]
            hurt.append(("self", 0, 2 * (prev["health"] - inv["health"]), cause))
        ate = "food" if inv["food"] > prev["food"] else "water" if inv["drink"] > prev["drink"] else None
        walls = int(sum(view[4 + a, 3 + b] not in WALK for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b))
        o = {"obs": obs, "view": v, "sky": np.array([light]), "walls": walls, "hp": int(inv["health"] * 20 / 9),
             "hunger": int(min(inv["food"], inv["drink"]) * 20 / 9), "fatigue": (9 - inv["energy"]) * 50,
             "nausea": 0, "inv": {k: inv[k] for k in ITEMS}, "t": env._step, "pos": (int(x), int(y)),
             "dir": 0, "near": near, "carer_holds": None, "state": st, "lost_built": [], "night": light == 0,
             "ev": {"deaths": [], "hurt": hurt, "destroyed": [], "ate": ate, "caught": False, "tamed": None, "tone": 0,
                    "gift": False, "carer_did": None, "explosion": None, "sounds": set(), "died": done and inv["health"] <= 0,
                    "slept": inv["energy"] > prev["energy"] and p.sleeping, "placed": None, "got": got + new_ach,
                    "cat_with_carer": False}}
        self.prev = dict(inv)
        return o


def score(rates):
    r = np.array(list(rates.values())) * 100
    return float(np.exp(np.mean(np.log(1 + r))) - 1)


def run(steps=1_000_000, seed=0, log_every=50_000):
    env = crafter.Env(seed=seed)
    c = CrafterChild(seed)
    body = Body()
    ach_names = None
    episodes, cur, t0, n = [], None, time.time(), 0
    moments = []
    while n < steps:
        env.reset()
        obs, r, done, info = env.step(0)
        ach_names = ach_names or list(info["achievements"])
        body.prev, a, fb, inv, unlocked = None, None, 0, {}, set()
        while True:
            new = [k for k, v in info["achievements"].items() if v and k not in unlocked]
            unlocked.update(new)
            o = body.read(env, info, done, new)
            a = c.step(o, a, fb, inv, extra_reward=1.0 * len(new))
            for k in new:
                if not any(m[0] == k for m in moments):
                    moments.append((k, n, c.limbic.top(3, 0.2)))
            if done:
                break
            fb, inv = int(o["view"][7]), dict(o["inv"])
            obs, r, done, info = env.step(a)
            n += 1
        episodes.append(unlocked)
        if n // log_every != (n - env._step) // log_every or n >= steps:
            rates = {k: np.mean([k in e for e in episodes]) for k in ach_names}
            print(f"{n} steps, {len(episodes)} episodes, {n / (time.time() - t0):.0f} steps/s: score {score(rates):.1f}%  "
                  f"stage {c.limbic.stage()}  " + " ".join(f"{k.replace('collect_', 'c.').replace('make_', 'm.')}:{v * 100:.0f}"
                                                            for k, v in rates.items() if v > 0), flush=True)
    rates = {k: np.mean([k in e for e in episodes]) for k in ach_names}
    return score(rates), rates, episodes, moments, c


if __name__ == "__main__":
    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    s, rates, eps, moments, c = run(steps, seed)
    print(f"\nFINAL score {s:.2f}% over {len(eps)} episodes")
    for k, v in sorted(rates.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<20} {v * 100:5.1f}%")
    print("first time, and what it felt:")
    for k, n, feel in moments:
        print(f"  step {n:>7}: {k:<20} " + ", ".join(f"{NAMES[e]} {x:.2f}" for e, x in feel))
