"""
Imagination: before acting, the mind plays the way to what it wants through in its head - made of the pieces it
has learned about its world - and so finds ways it has never gone. Nothing here says what to do in this world:
every piece is learned (or read in the recipe book); only how to put pieces together is innate.

  what my action brought before, and when   (action -> outcome: eating with chicken in the bag -> fed)
  what my hands do to what they are aimed at (schemas: crafting T gives T; striking T fells it)
  what each thing gives                      (yields: an oak log gives a log; a chicken leaves chicken)
  what things are made of                    (recipes read, and preconditions lived)
  where things are                           (places: chickens were over there)

Played backwards from the wish (what would make it true? and what would make THAT true?), the cheapest way
whose beginning I can do now wins; its first step is done, and the next moment the way is imagined again from
where I am then. Written down in words, so a person can see what it wants and why it does what it does.
"""
import heapq

LIVED = ("have:", "hold:", "wear:", "reach:", "see:", "at_table", "near:", "can_craft:")


class Op:
    __slots__ = ("effect", "kind", "target", "needs", "p", "why")

    def __init__(self, effect, kind, target, needs, p, why):
        self.effect, self.kind, self.target, self.needs, self.p, self.why = effect, kind, target, tuple(needs), p, why

    def words(self, ru):
        if self.kind == "goto_place":
            return "идти туда, где помню"
        t = self.target if isinstance(self.target, str) else ""
        return f"{ru(self.kind)}{' ' + ru(t) if t else ''}"


class Imagination:
    def __init__(self, child, actions, ru=lambda x: x):
        self.child, self.actions, self.ru = child, actions, ru
        self.last = None
        self.rel = {}          # each kind of step I took: [times, times it brought what I expected]
        import random
        self.rng = random.Random(0)

    # ---------------------------------------------------------------- what my steps really brought
    @staticmethod
    def key(kind, target, effect):
        t = target if isinstance(target, str) else ("place" if target is not None else "")
        return f"{kind}|{t}|{str(effect).split('×')[0]}"

    def trust(self, op):
        """A step that did not bring what I expected, again and again, is imagined as less likely (my own
        experience of it); one I have not taken yet keeps what I know of it."""
        r = self.rel.get(self.key(op.kind, op.target, op.effect))
        return 1.0 if not r else min(1.0, 2.0 * (r[1] + 1.0) / (r[0] + 2.0))

    def learned(self, kind, target, effect, ok):
        r = self.rel.setdefault(self.key(kind, target, effect), [0.0, 0.0])
        r[0] += 1
        r[1] += float(ok)
        if r[0] > 40:                                         # (old experience fades: the world changes)
            r[0], r[1] = r[0] * 0.97, r[1] * 0.97

    def state(self):
        mind = self.child.mind
        n = len(mind.names)
        return {mind.names[i] for i in (mind.val[:n] > 0).nonzero()[0]}

    def holds(self, c, st):
        """Is it true now? ("have:stick×2": two sticks in my bag, of that kind)"""
        if "×" not in c:
            return c in st
        name, n = c.split("×")
        x = name.partition(":")[2]
        kind = getattr(self.child, "kind_of", None) or (lambda k: k)
        bag = (self.child.m or {}).get("items") or {}
        return sum(v for k, v in bag.items() if k == x or kind(k) == x) >= int(n)

    def ops(self, c, st):
        """The ways I know to make c true (and what each needs first) - what I know how it works first: a
        coincidence I lived ("so it went before") only where nothing explains it, and only if it held up."""
        child = self.child
        mind, m = child.mind, (child.m or {})
        c0 = c.split("×")[0]
        what, _, x = c0.partition(":")
        i = mind.idx.get(c0)
        sc, ys, places = getattr(child, "schemas", None), getattr(child, "yields", None), getattr(child, "places", None)
        out = []
        if what == "have":
            read = getattr(child, "recipes_read", {}).get(x)
            if read:                                          # made of: the recipe book, with how many of each
                need, table = read
                pres = [f"have:{k}×{n}" for k, n in need.items()] + (["at_table"] if table else [])
            elif i is not None and not (ys is not None and any(ys.p(s_, x) >= 0.2 for s_ in ys.got)):
                pres = [mind.names[j] for j in mind.told_pre.get(int(i), ())] or                        [mind.names[j] for j in mind.pre(i) if mind.names[j].startswith(LIVED)]
            else:
                pres = []
            if pres:
                p = (sc.p("craft_target", "got", frozenset({"can_craft"})) if sc else None) or 0.6
                out.append(Op(c, "craft_target", x, pres, p, "сделать"))
            if ys is not None:                                # what gives it: a block broken, a creature felled
                with_tool = {k.split("@")[0] for k in ys.got if "@" in k}
                for src in ys.got:
                    p = ys.p(src, x)
                    if p < 0.2 or ("@" not in src and src in with_tool):   # (with what in hand tells more)
                        continue
                    if src.startswith("mob:"):
                        out.append(Op(c, "attack", src[4:], ["see:" + src[4:]], p * 0.7, "с него падает"))
                    else:                                     # (with what in hand: stone needs a pickaxe)
                        block, _, tool = src.partition("@")
                        needs = ["see:" + block] + ([f"have:{tool}"] if tool and tool != "hand" else [])
                        out.append(Op(c, "mine_target", block, needs, p, "из него добывается"))
        if c0 in ("ate", "fed"):                              # what I know can be eaten: in the bag, then eaten
            for food in sorted(getattr(child, "edible", ()))[:40]:
                out.append(Op(c, "eat", food, [f"have:{food}"], 0.9, "съесть"))
        elif what in ("see", "reach"):
            spot = places.nearest(x, m, getattr(child, "age", None)) if places is not None else None
            if spot:                                          # (where it hurt before: I would rather not)
                hurt = places.danger_near(spot, m)
                out.append(Op(c, "goto_place", spot, [], 0.2 if hurt else 0.7, "помню, где" + (" (там было больно)" if hurt else "")))
            if what == "reach":
                out.append(Op(c, "approach", x, ["see:" + x], 0.8, "подойти"))
            j = mind.idx.get("see:" + x)                    # how likely a search finds it: as common as it is
            common = float(mind.base[j]) if j is not None and j < len(mind.base) else 0.0
            out.append(Op(c, "explore", None, [], 0.03 + 0.25 * min(1.0, 5 * common), "поискать"))
        elif c0 == "safe_night" and places is not None:        # home: where I was safe at night before
            home = places.home(m)
            if home and "at_home" not in st:
                out.append(Op(c, "goto_place", home, [], 0.7, "домой"))
        elif what == "killed":
            out.append(Op(c, "attack", x, ["see:" + x], 0.6, "ударить"))
        elif what != "have" and i is not None:              # a state that comes of others (a table at hand:
            pres = [mind.names[j] for j in mind.told_pre.get(int(i), ())] or                    [mind.names[j] for j in mind.pre(i) if mind.names[j].startswith(LIVED)]
            if pres:                                          # when I have one)
                out.append(Op(c, "", None, pres, 0.95, "будет, когда есть"))
        if not out and i is not None:                         # nothing explains it: what my actions brought before
            base = mind.nev[i] / max(1.0, mind.steps)
            for a, rec in mind._ao_e.get(int(i), ()):
                if rec[0] < 3 or a >= len(self.actions):      # (twice may be chance)
                    continue
                p, p0 = mind.ao_effect(rec, base)
                if p < 0.4 or p < 2 * p0:
                    continue
                needs = [mind.names[j] for j in mind.ao_context(rec, i) if mind.names[j].startswith(LIVED)]
                out.append(Op(c, self.actions[a], None, needs, p, "так уже выходило"))
        kept = []
        for op in out:
            if op.kind:
                t = self.trust(op)
                if t < 0.15 and op.kind != "explore" and self.rng.random() > 0.1:   # it failed again and again: not
                    continue                                  # a way (now and then tried again - the world changes);
                                                              # searching is never ruled out: it is the last way to anything
                op.p *= t
            kept.append(op)
        return kept

    def plan(self, goal, max_nodes=3000, max_steps=16):
        """The cheapest way to goal I can imagine from here, in the order it is done: [Op, ...] (or None)."""
        st = self.state()
        if self.holds(goal, st):
            return []
        heap, k, done = [(0.0, 0, (goal,), ())], 0, set()
        while heap and k < max_nodes:
            cost, _, open_, steps = heapq.heappop(heap)
            if not open_:
                return list(reversed(steps))
            c, rest = open_[0], open_[1:]
            if (open_, len(steps)) in done:
                continue
            done.add((open_, len(steps)))
            if len(steps) >= max_steps:
                continue
            for op in self.ops(c, st):                        # (what a step needs must come of a step taken
                if c in op.needs:                             # before it - not of one that comes after it in
                    continue                                  # the plan: logs before planks, not "planks first")
                need = tuple(nd for nd in op.needs if not self.holds(nd, st) and nd not in rest)
                k += 1
                heapq.heappush(heap, (cost + 1.0 / max(op.p, 0.05), k, need + rest, steps + (op,)))
        return None

    def first_step(self, goal):
        """The first step of the way to goal I imagine now: (kind, target, how sure), and the way in words."""
        way = self.plan(goal)
        way = [o for o in (way or []) if o.kind]              # (states that come of others are not steps)
        if not way:
            return None, None
        op = way[0]
        words = " → ".join(o.words(self.ru) for o in way) + f" ⇒ {self.ru(goal.partition(':')[2] or goal)}"
        sure = 1.0
        for o in way:
            sure *= o.p
        self.last = way
        return (op.kind, op.target, max(0.5, min(0.9, op.p)), op.effect), \
            (words if len(way) > 1 or way[0].kind != "explore" else None)
