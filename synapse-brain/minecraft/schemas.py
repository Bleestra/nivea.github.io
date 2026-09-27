"""
What my hands do to the thing they are aimed at - learned, never told, and general: not "planks come of
crafting" (a fact about planks), but "crafting T gives me T when the book shows I can make T" (a fact about
crafting, true of every T). After a few cases it holds for things I have never aimed at: wanting a table, with
planks in the bag, I make the table - I do not go exploring the world; wanting a log, I go at the tree I see.

The body says what each action was aimed at (the target the brain chose) and what came of it. Counted per
(action, what came of it, what was true of the target before):

  what came of it   got     I have the very thing I aimed at (crafting it, taking it)
                    yield   I have something that came of it (breaking it, felling it)
                    reach   I am close enough to touch it (walking to it)
                    killed  it fell by my hand
  what was true     can_craft (the book shows I can make it now), see, reach, have, at_table
"""
import json
import os

KINDS = ("craft_target", "mine_target", "approach", "attack", "take")
OUTCOMES = ("got", "yield", "reach", "killed")


def relations(m, target):
    """What was true of the target before the action: can I make it, do I see it, can I touch it, have I it."""
    rel = set()
    if target in (m.get("craftable") or []):
        rel.add("can_craft")
    for name, d, *_ in m.get("seen", []):
        if name == target:
            rel.add("see")
            if d <= 4:
                rel.add("reach")
    if (m.get("items") or {}).get(target):
        rel.add("have")
    return frozenset(rel)


class Schemas:
    def __init__(self, kind_of=None):
        self.n = {}                                   # "action|outcome|relations" -> [tries, it came]
        self.kind_of = kind_of or (lambda x: x)
        self.aimed = None                             # the last aimed action: (kind, target, relations, bag)

    @staticmethod
    def _key(kind, out, rel):
        return f"{kind}|{out}|{','.join(sorted(rel))}"

    def aim(self, kind, target, m):
        """An action goes out aimed at target: remember what was true of it and what I had."""
        self.aimed = (kind, target, relations(m, target), dict(m.get("items") or {})) if kind in KINDS and target else None

    def outcome(self, m):
        """The next moment: what came of the last aimed action (learned for every kind of outcome)."""
        if self.aimed is None:
            return
        kind, target, rel, bag = self.aimed
        self.aimed = None
        now = m.get("items") or {}
        gained = [k for k, v in now.items() if v > bag.get(k, 0)]
        got = {                                           # what came of it - that was not so before
            "got": any(k == target or self.kind_of(k) == self.kind_of(target) for k in gained),
            "yield": bool(gained) and kind in ("mine_target", "attack"),
            "reach": "reach" not in rel and any(name == target and d <= 3 for name, d, *_ in m.get("seen", [])),
            "killed": any(str(x[0]) == target and len(x) > 3 and x[3] == "self"
                          for x in (m.get("fev") or {}).get("deaths", [])),
        }
        for out in OUTCOMES:
            for k in (kind, "*"):                         # (and over all actions: how often it comes anyway)
                rec = self.n.setdefault(self._key(k, out, rel), [0, 0])
                rec[0] += 1
                rec[1] += int(got[out])

    def p(self, kind, out, rel):
        """How sure: how often it came of this action - if clearly more often than of any action there (else a
        coincidence: crafting while a log happened to come near does not bring logs near)."""
        rec = self.n.get(self._key(kind, out, rel))
        if rec is None or rec[0] < 3:
            return None
        p = (rec[1] + 0.5) / (rec[0] + 1.0)
        pool = self.n.get(self._key("*", out, rel))
        if pool is not None and pool[0] > rec[0]:
            others = (pool[1] - rec[1] + 0.5) / (pool[0] - rec[0] + 1.0)
            if p < others + 0.25:
                return None
        return p

    def plan(self, goal, m, yields=None, least=0.5):
        """For a step of my plan (have:X, reach:X, see:X, killed:X): the action, and what to aim it at, that by
        what I have learned does it here - or None. -> (kind, target, how sure)."""
        what, _, x = goal.partition(":")
        cands = []
        if what == "have":
            craftable = m.get("craftable") or []
            same = [k for k in craftable if k == x or self.kind_of(k) == x]
            cands.append(("got", same[0] if same else x))
            if yields is not None:
                seen = [s[0] for s in m.get("seen", [])]
                src, here = yields.source(x, seen)
                if src is not None and not src.startswith("mob:"):
                    block, _, tool = src.partition("@")       # (stone gives cobblestone to a pickaxe: only if I have one)
                    bag = m.get("items") or {}
                    if not tool or tool == "hand" or any(self.kind_of(k) == tool for k in bag):
                        cands.append(("yield", block))
                src, here = yields.source(x, ["mob:" + s for s in seen])
                if src is not None and here:
                    cands.append(("yield", src[4:]))
        elif what in ("reach", "see"):
            cands.append(("reach", x))
        elif what == "killed":
            cands.append(("killed", x))
        best = None
        for out, target in cands:
            rel = relations(m, target)
            for kind in KINDS:
                p = self.p(kind, out, rel)
                if p is not None and p >= least and (best is None or p > best[2]):
                    best = (kind, target, p)
        return best

    def save(self, path):
        tmp = path + ".saving"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.n, f)
        os.replace(tmp, path)

    def load(self, path):
        if os.path.exists(path):
            self.n = json.load(open(path, encoding="utf-8"))
