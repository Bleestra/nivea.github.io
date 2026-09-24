"""
Experiment: after the agent makes its first iron pickaxe it finds a book. Does reading about
diamonds make it get diamonds and a diamond pickaxe - and what does it feel?

CraftWorld with diamonds deep in the dark heart of the mountain (only an iron pickaxe mines them)
and a diamond pickaxe recipe. The book appears in the inventory after the iron pickaxe (every life).
Reading is an action ('read') the agent may or may not choose. Its text goes through reading.py
into the mind as beliefs. Control: a book of the same kind about something else (fishing).
The whole brain (habits + mind + limbic system) is the same as in LifeWorld.

    python3 diamond_bench.py [lives=200] [seeds=3]
"""
import sys
import time
from collections import Counter

import numpy as np

from child import Child
from craftworld import DIAMOND_ACTIONS, DIAMOND_ITEMS, CraftWorld
from limbic import NAMES
from reading import read

BOOK = ("Алмазы — самое ценное, что есть в недрах. Алмазы лежат глубоко в сердце горы, в темноте. "
        "Чтобы добыть алмаз, нужна железная кирка и нужно спуститься глубоко. "
        "Чтобы сделать алмазную кирку, нужны алмазы, палки и верстак. Алмазная кирка — самый лучший инструмент.")
OTHER = ("Рыбы живут в воде. Чтобы поймать рыбу, нужна удочка и терпение. Рыбу вкусно есть на закате. "
         "Лучшая наживка — червяк.")


class CraftChild(Child):
    def concepts(self, o):
        return o["state"]


def to_o(env, obs, got, done):
    v = obs[0]
    y, x = env.pos
    walls = sum(env.cell(y + a, x + b) not in (0, 7) for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b)
    st = env.state()
    return {"view": v, "sky": np.array([1 if st["sky"] else 0]), "walls": walls, "hp": 20, "hunger": 20,
            "fatigue": 0, "nausea": 0, "inv": dict(env.inv), "t": env.t, "pos": env.pos, "dir": env.dir,
            "near": [], "carer_holds": None, "state": st, "night": False,
            "ev": {"deaths": [], "hurt": [], "destroyed": [], "ate": None, "caught": False, "tamed": None,
                   "tone": 0, "gift": False, "carer_did": None, "explosion": None, "sounds": set(),
                   "died": done, "slept": False, "placed": None, "got": got, "cat_with_carer": False}}


def run(book, seed, lives, life_len=1500):
    env = CraftWorld(seed=seed, life=life_len, diamonds=True, book=book)
    c = CraftChild(len(DIAMOND_ACTIONS), seed=seed, taste={}, items=DIAMOND_ITEMS, eat_action=-1, wait_action=4, kinds=[])
    rows, moments, read_at = [], [], None
    for life in range(lives):
        obs = env.reset()
        a, fb, inv, r_prev, done, got, pending = None, 0, dict(env.inv), 0.0, False, [], None
        firsts = {}
        while True:
            o = to_o(env, obs, got, done)
            a = c.step(o, a, fb, inv, extra_reward=r_prev + 0.01)
            if pending:                                         # the feeling of the moment just after
                moments.append((life, pending, c.limbic.top(4, 0.2)))
                pending = None
            if done:
                break
            fb, inv = int(obs[0][7]), dict(env.inv)
            before = dict(env.inv)
            obs, r_prev, done = env.step(a)
            got = [k for k in env.inv if env.inv[k] > before.get(k, 0)]
            if env.just_read is not None:
                claims, values = read(env.just_read)
                c.mind.tell(claims, values)
                env.just_read = None
                if read_at is None:
                    read_at = life
                firsts.setdefault("read", env.t)
            for k in ("iron_pick", "diamond", "diamond_pick"):
                if k in got and k not in firsts:
                    firsts[k] = env.t
                    if k in ("diamond", "diamond_pick") and not any(m[1] == k for m in moments):
                        pending = k
        rows.append(firsts)
    return rows, read_at, moments, c


def main():
    lives = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    seeds = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else [0, 1, 2]
    books = {"diamonds": ("book about diamonds", BOOK), "fishing": ("book about fishing (control)", OTHER)}
    which = sys.argv[3].split(",") if len(sys.argv) > 3 else ["diamonds", "fishing"]
    for key in which:
        name, book = books[key]
        print(f"\n## {name}", flush=True)
        for seed in seeds:
            t0 = time.time()
            rows, read_at, moments, c = run(book, seed, lives)
            first_iron = next((i for i, r in enumerate(rows) if "iron_pick" in r), None)
            after = rows[first_iron:] if first_iron is not None else []
            n = max(1, len(after))
            q = len(after) // 2
            late = after[q:]
            print(f"seed {seed} ({time.time() - t0:.0f}s): first iron pickaxe in life {first_iron}; read the book first in life "
                  f"{read_at}; after the first iron pickaxe ({len(after)} lives): read in {sum('read' in r for r in after) / n:.0%}, "
                  f"diamond in {sum('diamond' in r for r in after) / n:.0%}, diamond pickaxe in "
                  f"{sum('diamond_pick' in r for r in after) / n:.0%} (second half: {sum('diamond_pick' in r for r in late) / max(1, len(late)):.0%})",
                  flush=True)
            for life, k, feel in moments:
                print(f"   life {life}: first {k} — feels " + ", ".join(f"{NAMES[e]} {x:.2f}" for e, x in feel))
            m = c.mind
            if "have:diamond_pick" in m.idx:
                print("   in its synapses: " + "; ".join(m.why(m.idx["have:diamond_pick"])[:3]))
            told = getattr(m, "told", {})
            if told:
                print("   believed from the book: " + ", ".join(told))


if __name__ == "__main__":
    main()
