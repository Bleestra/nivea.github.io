"""
What each thing gives me when I break it (learned, never told): the body reports every block my hands broke
and what came into my bag within a second after (maybe nothing). Counted per block: "oak log gave me an oak
log 20 times of 20", "grass gave me dirt". When a step of my plan is to have something, my hands aim at what
gave it to me before - not at whatever happens to be in sight.
"""
import json
import os


class Yields:
    def __init__(self, kind_of=None):
        self.n = {}                         # block -> times broken
        self.got = {}                       # block -> {item: times it came}
        self.kind_of = kind_of or (lambda x: x)

    def learn(self, block, gained, tool=None):
        """What breaking it gave me - and with what in my hand (stone gives nothing to a bare hand, cobblestone
        to a pickaxe): counted for the block, and for the block with that tool."""
        for key in ([block] + ([f"{block}@{tool}"] if tool else [])):
            self.n[key] = self.n.get(key, 0) + 1
            g = self.got.setdefault(key, {})
            for item in set(gained) | {self.kind_of(x) for x in gained}:
                g[item] = g.get(item, 0) + 1

    def tell(self, key, items, n=2):
        """What I read it gives (the reference): as if seen n times - my own breaking confirms or overturns it."""
        if key not in self.n:
            self.n[key] = n
            self.got[key] = {i: n for i in items}

    def p(self, block, item):
        """How often breaking it gave me this (as if once it gave nothing: a single lucky time is not sure - and
        once is never enough: something lying there came into my bag just as I broke it)."""
        k = self.got.get(block, {}).get(item, 0)
        return k / (self.n.get(block, 0) + 1.0) if k >= 2 else 0.0

    def source(self, item, seen=(), least=0.3):
        """What to break to get it: of the things in sight the surest; else the surest I know (to go and look
        for). None when nothing ever gave it to me often enough."""
        known = [(self.p(b, item), b) for b in self.got if item in self.got[b]]
        known = [(p, b) for p, b in known if p >= least]
        if not known:
            return None, False
        here = [(p, b) for p, b in known if b.split("@")[0] in seen]     # ("stone@wooden_pickaxe": stone)
        if here:
            return max(here)[1], True
        return max(known)[1], False

    def save(self, path):
        tmp = path + ".saving"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"n": self.n, "got": self.got}, f, ensure_ascii=False)
        os.replace(tmp, path)

    def load(self, path):
        if os.path.exists(path):                          # (what I read and never lived yet stays)
            d = json.load(open(path, encoding="utf-8"))
            for k, v in d.get("n", {}).items():
                self.n[k] = v
                self.got[k] = d.get("got", {}).get(k, {})
