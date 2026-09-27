"""
Core v5: one model of the world, one planner over it, goals from needs and from what I can newly do.

What came before (v1-v4) knew "what leads to what" in eight places that disagreed (chains of what was around,
action-outcome records, schemas, yields, recipes, helpers, habits, routines) and let some fifteen voices vote on
every action. This core has one of each:

  the model   an operator is what my hands do to a kind of thing: (action, target) - "strike an oak log",
              "craft planks", "eat an apple", "explore". Every time I do one, what came of it is counted: which
              things became true (I see a cow, the table is at hand, I ate), what came into my bag and what left it.
              A condition is needed for an effect only when it was there every time the effect came AND the effect
              did not come, twice or more, when it was missing (the sky is always there when I eat, but I ate
              without it; a log is gone from my bag every time planks come - that is what planks are made of).
              What I read (the recipe book, the reference) is where the model starts: my own tries overrule it.
  the planner the cheapest way from what is true now to what I want, backwards through the model; every step
              comes with what I expect of it. Its first step is what I do; the next moment the way is planned
              again from where I am then.
  the goals   a need of my body first (hunger, the night) - as strong as the need; else something I have never
              had and can see a way to (curiosity for what my hands could newly do); else an experiment: an
              action I have never tried on something here; else I go and look around.

Nothing here says what to do in this world: which actions do what, and when, is learned; innate are the needs,
curiosity and how to put pieces of knowledge together.
"""
import heapq
import json
import math
import os
import random
from collections import deque

from actions import ACTIONS

TARGETED = ("approach", "mine_target", "craft_target", "attack", "goto_place")
CONDITIONS = ("have:", "hold:", "wear:", "see:", "reach:", "near:", "can_craft:", "at_table", "sky", "dark", "underground",
              "indoors", "deep", "day", "sheltered", "at_home", "walls>=", "hungry", "need:")
EFFECTS = ("have:", "hold:", "wear:", "see:", "reach:", "killed:", "stored:", "at_table", "ate", "safe_night", "sheltered",
           "at_home", "sky", "indoors", "walls>=", "relief:")
LIVED_SUCC = 3                # what an effect needs is judged from this many times it came (once may be chance)
LEAST_P = 0.1                 # a way less likely than this is not a way
KEEP = 40                     # tries remembered per operator (older ones fade: the world, my body change)
NEED_FAILS = 2                # an effect that did not come this often without a condition: the condition is needed
NEED_ON = 0.25                # a drive this strong is a need: felt (a condition "need:...") and acted on
SIT_KEEP = 12                 # tries remembered per operator in each situation (the night is not forgotten by day)
SIT_MAX = 64                  # situations remembered per operator (the least recent go)
RELIEF_P = 0.2                # an act that eased a need less often than this, here, is not what eases it
RISKY = 4.0                   # health an act cost here on average, above which I do not do it for curiosity
URGENT = 2.0                  # a need this strong takes risks (starving; the open night); a weaker one waits them out
KEEPS_THINGS = ("drop_item", "drop_junk", "store")   # a need is no reason to throw my things away


def situation(conds):
    """Where I am and how I feel, in a few words: under the sky, in the dark, walls round me, afraid, hungry -
    not what I see or carry. What an act does to me here (eases the fear, hurts) is remembered by this."""
    return frozenset(c for c in conds if c in ("sky", "dark", "day", "underground", "indoors", "deep", "sheltered", "at_home")
                     or c.startswith(("walls>=", "need:", "in:")))


def _is(name, prefixes):
    return any(name == p or name.startswith(p) for p in prefixes)


class Op:
    """What one kind of act does: tries (what was true, what came of it) and what I was told of it."""

    __slots__ = ("kind", "target", "tries", "prior", "n", "_cache", "by_sit")

    def __init__(self, kind, target):
        self.kind, self.target = kind, target
        self.tries = deque(maxlen=KEEP)      # (conditions, effects, used: {item: n}, ok, harm: health lost, 20 = died)
        self.prior = {}                      # effect -> (p, needs) - read, not lived
        self.n = 0                           # tries over my whole life
        self._cache = {}
        self.by_sit = {}                     # situation -> deque of (what eased or sheltered me, health lost)

    def learn(self, conds, effects, used, ok, harm=0.0):
        self.tries.append((frozenset(conds), frozenset(effects), dict(used), bool(ok), float(harm)))
        self.n += 1
        self._cache = {}
        self.remember(situation(conds), effects, harm)

    def remember(self, sit, effects, harm):
        recs = self.by_sit.pop(sit, None)
        if recs is None:
            recs = deque(maxlen=SIT_KEEP)
        recs.append((frozenset(e for e in effects if e.startswith("relief:") or e in ("safe_night", "sheltered")),
                     float(harm)))
        self.by_sit[sit] = recs                                  # (the most recent situation last)
        while len(self.by_sit) > SIT_MAX:
            self.by_sit.pop(next(iter(self.by_sit)))

    def risk(self, here=None):
        """What doing it cost my body, on average - here, if I have done it here (exploring by day: nothing; in the
        dark under the open sky: my life), else anywhere (a fight with a zombie bare-handed: a lot)."""
        same = self.by_sit.get(here) if here is not None else None
        if same is not None and len(same) >= 2:
            return sum(r[1] for r in same) / len(same)
        return sum(t[4] for t in self.tries) / len(self.tries) if self.tries else 0.0

    def effects(self):
        out = set(self.prior)
        for t in self.tries:
            out |= t[1]
        return out

    def needs(self, effect):
        """What must be true for this act to bring the effect: lived (there every time it came, and missing when
        it did not come - often enough to tell) and what it used up (a log for planks) - else what I read."""
        if effect in self._cache:
            return self._cache[effect]
        succ = [t for t in self.tries if effect in t[1]]
        need = {}
        if len(succ) >= LIVED_SUCC:                          # (from one or two times: only what it used up)
            common = set.intersection(*(set(c for c in t[0] if _is(c, CONDITIONS)) for t in succ))
            for c in common:
                if sum(1 for t in self.tries if c not in t[0] and effect not in t[1]) >= NEED_FAILS:
                    need[c] = 1
        if succ:
            for t in succ:                                   # what it used up: that is what it is made of
                for item, k in t[2].items():
                    key = "have:" + item
                    need[key] = max(need.get(key, 0), k)
        if effect in self.prior:                             # what I read holds until my own tries say otherwise
            for c in self.prior[effect][1]:
                name, _, k = c.partition("×")
                if name not in need or not succ:
                    need[name] = max(need.get(name, 0), int(k or 1))
        out = tuple(sorted(f"{c}×{k}" if c.startswith("have:") and k > 1 else c for c, k in need.items()))
        self._cache[effect] = out
        return out

    def p(self, effect, holds):
        """How likely it brings the effect when what it needs is there (my tries under those conditions, and what I
        read as if seen twice)."""
        need = [c.split("×")[0] for c in self.needs(effect)]
        succ = sum(1 for t in self.tries if effect in t[1])
        judged = succ >= LIVED_SUCC or effect in self.prior       # (conditions known: lived, or read)
        rel = [t for t in self.tries if all(c in t[0] for c in need)] if judged else list(self.tries)
        s = sum(1 for t in rel if effect in t[1])
        p0, w = (self.prior[effect][0], 2.0) if effect in self.prior else (0.3, 1.0)
        return (s + w * p0) / (len(rel) + w)


class Step:
    __slots__ = ("op", "effect", "p", "needs", "risk")

    def __init__(self, op, effect, p, needs, here=None):
        self.op, self.effect, self.p, self.needs = op, effect, p, needs
        self.risk = op.risk(here) if op.kind else 0.0

    def cost(self):
        """Tries it takes, and what it costs my body (two health points weigh as much as one more try)."""
        return 1.0 / max(self.p, 0.03) + self.risk / 2.0


class Core:
    def __init__(self, child, seed=0):
        self.child = child
        self.ops = {}                         # (kind, target) -> Op
        self.by_effect = {}                   # effect -> set of keys
        self.rng = random.Random(seed)
        self.had = set()                      # effects I have ever had (for curiosity: what is new)
        self.goal, self.goal_why, self.goal_t, self.goal_fails = None, "", 0, 0
        self.plan, self.step = [], None
        self.prev = None                      # (conditions, bag, (kind, target) meant) at the last action
        self.implied = {}                     # state -> {thing: [moments with it, of them the state held, moments
                                              # without it, of them the state held]} - "a table at hand whenever
                                              # there is one in my bag" (learned), or read (the guide)
        self.told_implied = {}                # state -> [needs] read
        self.moments = 0
        self._priors_done = False

    # ---------------------------------------------------------------- the model
    def op(self, kind, target):
        key = (kind, target)
        o = self.ops.get(key)
        if o is None:
            o = self.ops[key] = Op(kind, target)
        return o

    def _index(self, o):
        for e in o.effects():
            self.by_effect.setdefault(e, set()).add((o.kind, o.target))

    def tell(self, kind, target, effect, p, needs):
        """What I read: this act brings that, when these are there (a hypothesis my tries will test)."""
        o = self.op(kind, target)
        if effect not in o.prior:
            o.prior[effect] = (p, tuple(needs))
            o._cache = {}
            self.by_effect.setdefault(effect, set()).add((kind, target))

    def priors(self):
        """The model starts from what I may read (world.json "knowledge"): the recipe book, the reference."""
        c = self.child
        for item, (need, table) in getattr(c, "recipes_read", {}).items():
            self.tell("craft_target", c.kind_of(item), "have:" + c.kind_of(item), 0.9,
                      [f"have:{c.kind_of(k)}×{n}" for k, n in need.items()] + (["at_table"] if table else []))
        ys = getattr(c, "yields", None)
        if ys is not None:
            for src, got in ys.got.items():
                block, _, tool = src.partition("@")
                for item in got:
                    p = ys.p(src, item)
                    if p < 0.2:
                        continue
                    if block.startswith("mob:"):
                        self.tell("attack", block[4:], "have:" + c.kind_of(item), p * 0.8, ["see:" + block[4:]])
                    else:
                        self.tell("mine_target", block, "have:" + c.kind_of(item), p,
                                  ["see:" + block] + ([f"have:{tool}"] if tool and tool != "hand" else []))
        for food in getattr(c, "edible", ()):
            self.tell("eat", food, "ate", 0.9, ["have:" + food])
        mind = c.mind
        for e, ps in getattr(mind, "told_pre", {}).items():  # states that come of having something (read)
            name = mind.names[e] if e < len(mind.names) else None
            pre = [mind.names[p] for p in ps if p < len(mind.names)]
            if name and not name.startswith(("have:", "see:", "reach:")) and pre and all(p.startswith("have:") for p in pre):
                self.told_implied[name] = pre                # (a table at hand: of having one; a pig in sight never
                                                             # comes of the sky - that was the guide misread)
                                                             # what I have had in my life so far is not new to me
        n = len(mind.names)
        self.had |= {mind.names[i] for i in range(n) if mind.base[i] > 1e-6 and _is(mind.names[i], EFFECTS)}
        # (perceived, not only read: a book raises what I "saw" of a thing, never what I perceived)
        self._priors_done = True

    def learn(self, conds_before, bag_before, conds_now, bag_now, kind, target, ok, harm=0.0, relief=()):
        kind_of = self.child.kind_of
        gained, used = {}, {}
        for k in set(bag_before) | set(bag_now):
            d = bag_now.get(k, 0) - bag_before.get(k, 0)
            kk = kind_of(k)
            if d > 0:
                gained[kk] = gained.get(kk, 0) + d
            elif d < 0:
                used[kk] = used.get(kk, 0) - d
        effects = {c for c in conds_now if c not in conds_before and _is(c, EFFECTS)}
        effects |= {"have:" + k for k in gained}
        effects |= {"relief:" + d for d in relief}           # the need eased after it (the fear of the night went
                                                             # down: walls round me now)
        self.had |= {c for c in conds_now if _is(c, EFFECTS)}
        if kind == "eat" and "ate" in effects:               # what I ate is what the bite was of
            target = kind_of(str((self.child.m or {}).get("fev", {}).get("ate") or target or ""))
        if kind in ("drop_junk", "drop_item", "store", "place_block", "place_up", "pillar_up", "place_chest"):
            used = {}                                        # (what I put down or away was not what it made)
        o = self.op(kind, target if kind in TARGETED or kind == "eat" else None)
        if kind == "attack" and ok and not effects and isinstance(target, str) and "see:" + target in conds_now \
                and harm < 20:
            self._fight_harm = getattr(self, "_fight_harm", 0.0) + harm   # (what the fight costs so far)
            return None                                      # a blow landed and it still stands: a fight takes many
                                                             # blows - not yet an outcome, neither way
        if kind == "attack":
            harm, self._fight_harm = harm + getattr(self, "_fight_harm", 0.0), 0.0
        o.learn(conds_before, effects, used if effects else {}, ok, harm)   # (used up for nothing: not what it is made of)
        self._index(o)
        return effects

    # ---------------------------------------------------------------- what is true now
    def bag(self):
        kind_of = self.child.kind_of
        out = {}
        for k, v in ((self.child.m or {}).get("items") or {}).items():
            out[kind_of(k)] = out.get(kind_of(k), 0) + v
        return out

    def holds(self, c, conds, bag):
        name, _, n = c.partition("×")
        if name.startswith("have:"):
            return bag.get(name[5:], 0) >= int(n or 1)
        return name in conds

    def _watch_implied(self, conds):
        """Which of the states my acts need come of simply having something (seen moment by moment)."""
        states = getattr(self, "_need_states", None)
        if states is None or self.moments % 200 == 1:
            states = self._need_states = {n.split("×")[0] for o in self.ops.values() for e in o.effects()
                                          for n in o.needs(e) if not n.startswith(("have:", "see:", "reach:"))}
        items = [c for c in conds if c.startswith("have:")]
        for st in states:
            rec = self.implied.setdefault(st, {})
            on = st in conds
            for x in items:
                r = rec.setdefault(x, [0, 0, 0, 0])
                r[0] += 1
                r[1] += on
            for x, r in rec.items():
                if x not in conds:
                    r[2] += 1
                    r[3] += on

    def implies(self, st):
        """The things whose having makes the state true (lived: every time, and clearly less often without)."""
        out = [[x] for x, r in self.implied.get(st, {}).items()
               if r[0] >= 20 and r[1] >= 0.99 * r[0] and r[3] <= 0.5 * max(r[2], 1)]
        if st in self.told_implied:
            out.append(self.told_implied[st])
        return out

    # ---------------------------------------------------------------- the planner
    def ways(self, c, conds, bag):
        """Every act that (as far as I know) makes c true: learned and read, and the walks my memory allows."""
        name = c.split("×")[0]
        out = []
        sit = situation(conds)
        for key in self.by_effect.get(name, ()):
            o = self.ops[key]
            if o.kind in ("explore", "goto_place"):
                continue
            if name not in o.prior and sum(1 for t in o.tries if name in t[1]) < LIVED_SUCC:
                continue                                     # (it came once or twice after it: maybe chance - sand
                                                             # came into sight while I was fishing)
            p = o.p(name, conds)
            need = o.needs(name)
            if o.kind == "craft_target" and isinstance(o.target, str) and all(self.holds(n, conds, bag) for n in need):
                can = (self.child.m or {}).get("craftable")    # the recipe book shows what I can make right now: the
                if can is not None and not any(k == o.target or self.child.kind_of(k) == o.target for k in can):
                    p = min(p, 0.02)                           # acacia boat is not made of birch planks
            if p >= LEAST_P - 1e-9:                          # (2.8 / 28 is a tenth, whatever the floats say)
                out.append(Step(o, name, p, need, sit))
        what, _, x = name.partition(":")
        places = getattr(self.child, "places", None)
        m = self.child.m or {}
        if what in ("see", "reach") and x:
            spot = places.nearest(x, m, getattr(self.child, "age", None)) if places is not None else None
            if spot:
                o = self.op("goto_place", x)                 # where I remember it - the farther, the dearer (a tree
                here = m.get("pos") or spot                  # nearby before planks in a house 300 blocks away)
                far = math.sqrt(sum((a - b) ** 2 for a, b in zip(spot, here)))
                p = (o.p(name, conds) if o.tries else 0.6) / (1.0 + far / 48.0)
                out.append(Step(o, name, p, (), sit))
            if what == "reach":
                o = self.op("approach", x)
                out.append(Step(o, name, o.p(name, conds) if o.tries else 0.8, ("see:" + x,), sit))
            o = self.op("explore", None)                     # looking for it: as often as a walk showed it,
            seen = sum(1 for t in o.tries if name in t[1] or "see:" + x in t[1])   # and as common as it was
            mind = self.child.mind                           # around me all my life (cows often; a plant of
            j = mind.idx.get("see:" + x)                     # the End never)
            common = float(mind.base[j]) if j is not None and j < len(mind.base) else 0.0
            p0 = 0.01 + 0.3 * min(1.0, 5.0 * common)        # (what my life says, weighed as two walks: forty walks
            p = (seen + 2.0 * p0) / (len(o.tries) + 2.0)     # here with no potato in sight say more than that)
            out.append(Step(o, "see:" + x, p, (), sit))
        for need in self.implies(name):                      # it comes of having something: a free step
            out.append(Step(Op("", None), name, 0.95, tuple(need)))
        if name == "safe_night" and places is not None and places.home(m):
            o = self.op("goto_place", "home")                # where I once lay closed in at night: as safe as going
            safe = sum(1 for t in o.tries if "safe_night" in t[1])   # there proved (a hole whose roof I broke is not)
            p = (safe + 2.0 * 0.6) / (len(o.tries) + 2.0)
            if p >= LEAST_P - 1e-9:
                out.append(Step(o, "safe_night", p, (), sit))
        return out

    def make_plan(self, goal, conds, bag, max_nodes=3000, max_steps=16):
        """The cheapest way to the goal I can imagine from here, in the order it is done ([Step, ...] or None)."""
        if self.holds(goal, conds, bag):
            return []
        heap, k, seen = [(0.0, 0, (goal,), ())], 0, set()
        while heap and k < max_nodes:
            cost, _, open_, steps = heapq.heappop(heap)
            if not open_:
                return list(reversed(steps))
            c, rest = open_[0], open_[1:]
            if (open_, len(steps)) in seen or len(steps) >= max_steps:
                continue
            seen.add((open_, len(steps)))
            for st in self.ways(c, conds, bag):
                if c in st.needs or any(c.split("×")[0] == n.split("×")[0] for n in st.needs):
                    continue                                 # (what it needs is what it makes: no way)
                need = tuple(n for n in st.needs if not self.holds(n, conds, bag) and n not in rest)
                k += 1
                heapq.heappush(heap, (cost + st.cost(), k, need + rest, steps + (st,)))
        return None

    # ---------------------------------------------------------------- the goals
    def usefulness(self):
        """How many of the acts I know need a thing (planks, a table, a pickaxe open many ways; a button none)."""
        if getattr(self, "_use_t", -1) < 0 or self.moments - self._use_t > 300:
            use = {}
            for o in self.ops.values():
                for e in o.effects():
                    for n in o.needs(e):
                        name = n.split("×")[0]
                        use[name] = use.get(name, 0) + 1
            self._use, self._use_t = use, self.moments
        return self._use

    def candidates(self, conds, bag):
        """New things I could get: effects I have never had that some act I know (or read of) brings - the ones
        that open most ways first."""
        use = self.usefulness()
        out = [e for e in self.by_effect if e not in self.had and e.startswith(("have:", "killed:")) and e not in conds]
        self.rng.shuffle(out)
        now = []                                             # what one act of mine makes right here, first
        for e in out:
            if any(all(self.holds(n, conds, bag) for n in st.needs) for st in self.ways(e, conds, bag)
                   if st.op.kind not in ("explore", "goto_place")):
                now.append(e)
        rest = sorted((e for e in out if e not in now), key=lambda e: -use.get(e, 0))
        return now[:15] + rest[:10]

    def experiment(self, conds, need=False):
        """An act never tried here: on a thing I see, with a thing I have - what does it do? Under a need that
        nothing I know eases here: whatever I have never done in a place like this (in a pit at night, afraid: the
        block over my head that would not stick on open ground) - trial and error, as a cat in a box."""
        m = self.child.m or {}
        seen = [e[0] for e in m.get("seen", [])]
        options = []
        for x in seen:
            kind = "attack" if any(e[0] == x and len(e) > 2 and e[2] == "mob" for e in m.get("seen", [])) else "mine_target"
            if (kind, self.child.kind_of(x)) not in self.ops:
                options.append((kind, x))
        for x in m.get("craftable", []):
            if ("craft_target", self.child.kind_of(x)) not in self.ops:
                options.append(("craft_target", x))
        if need:                                             # (not throwing my things away: a need is no reason to)
            here = situation(conds)
            fresh = [(a, None) for a in ACTIONS if a not in TARGETED and a not in (
                "explore", "craft_new", "craft_gear", "read", "trade", "drop_item", "drop_junk", "store")
                and here not in getattr(self.ops.get((a, None)), "by_sit", {})]
            return self.rng.choice(fresh + options) if fresh or options else None
        plain = [a for a in ACTIONS if a not in TARGETED and a not in ("explore", "craft_new", "craft_gear", "read", "trade")
                 and (a, None) not in self.ops]
        if plain and self.rng.random() < 0.3:
            options.append((self.rng.choice(plain), None))
        return self.rng.choice(options) if options else None

    def eased_by_hand(self, goal):
        """Has anything I did myself, right where I was, ever eased this need (a block beside me eased the fear of
        the night)? Then it is eased here, by trying; if not (hunger), it is found elsewhere, by searching."""
        t = getattr(self, "_eased_t", {})
        if goal not in t or self.moments - t[goal][0] > 50:
            eases = "relief:" + goal
            t[goal] = (self.moments, any(o.target is None and o.kind for o in self.ops.values()
                                         for sit, recs in o.by_sit.items() if "need:" + goal in sit
                                         for r in recs if eases in r[0]))
            self._eased_t = t
        return t[goal][1]

    def trial(self, goal, conds, bag):
        """Under a need no way I know of meets: the act likeliest to ease it here, by what I have seen of it - what I
        never did here is a maybe (an even chance), what eased it is tried again, what did not is let go (how a cat
        learns the box: the night is short, what worked is done again at once). What I did elsewhere under this
        need counts half."""
        here, eases = situation(conds), "relief:" + goal
        arms = [(a, None) for a in ACTIONS if a not in TARGETED and a not in KEEPS_THINGS and a not in (
            "craft_new", "craft_gear", "read", "trade")]
        best = None
        for kind, target in arms:
            o = self.ops.get((kind, target))
            e = n = 0.0
            if o is not None:
                same = o.by_sit.get(here)
                if same:
                    e, n = sum(1 for r in same if eases in r[0]), len(same)
                else:
                    felt = [r for sit, recs in o.by_sit.items() if "need:" + goal in sit for r in recs]
                    e, n = 0.5 * sum(1 for r in felt if eases in r[0]), 0.5 * len(felt)
            score = (e + 1.0) / (n + 2.0) + 0.05 * self.rng.random() - (o.risk(here) / 20.0 if o is not None else 0.0)
            if best is None or score > best[0]:
                best = (score, (kind, target))
        return best[1] if best is not None else None

    def relief(self, goal, conds, bag):
        """What eased this need before and can be done here (the fear of the night went down after I dug in):
        the likeliest here, the least hurtful - an animal does what made the fear go away. Judged where I am when
        I have done it here (digging deeper in a pit eases nothing more), else wherever I felt this need."""
        best, here, eases = None, situation(conds), "relief:" + goal
        for o in self.ops.values():
            if not o.kind or o.kind in ("explore",) or not o.by_sit:
                continue
            felt = [r for sit, recs in o.by_sit.items() if "need:" + goal in sit for r in recs]
            if not any(sit for sit in o.by_sit if any(c.startswith("need:") for c in sit)):
                felt = [r for recs in o.by_sit.values() for r in recs]   # (from before I knew what I felt)
            if sum(1 for r in felt if eases in r[0]) < 2:
                continue                                     # (once may be the dawn coming)
            same = o.by_sit.get(here)
            pool = list(same) if same is not None and len(same) >= 2 else felt
            p = (sum(1 for r in pool if eases in r[0]) + 0.5) / (len(pool) + 1.0)
            need = o.needs(eases)
            if p < RELIEF_P or not all(self.holds(n, conds, bag) for n in need):
                continue
            score = p - o.risk(here) / 20.0
            if best is None or score > best[0]:
                best = (score, (o.kind, o.target))
        return best[1] if best is not None and best[0] > 0.05 else None

    def taste(self, goal, bag):
        """An act that met this need before (eating stilled hunger - berries), done with what I have and never
        tried it with (the porkchop in my bag): what a child does with a new thing when hungry."""
        kinds = {o.kind for o in self.ops.values() if o.kind and any(goal in t[1] for t in o.tries)}
        for kind in kinds:
            new = [x for x in bag if bag[x] > 0 and len(getattr(self.ops.get((kind, x)), "tries", ())) < 2]                 if kind == "eat" else []
            if new and self.rng.random() < 0.7:
                return (kind, self.rng.choice(new))
        return None

    def _note(self, text, what):
        mind = self.child.mind
        i = mind._neuron(what) if what else None
        mind._note(text, i)

    def choose_goal(self, conds, bag):
        drives = getattr(self.child.mind, "drives", {}) or {}
        needs = {k: v for k, v in drives.items() if v > NEED_ON}
        if needs:
            g = max(needs, key=needs.get)
            if g != self.goal:
                self._set_goal(g, "нужда")
            return
        if self.goal is not None and self.goal in getattr(self.child.mind, "drive_goals", ()):
            self._note("прошло", self.goal)                   # the need passed: back to my own wishes
            self.goal = None
        if self.goal is not None and self.goal_fails < 6 and not self.holds(self.goal, conds, bag):
            return                                            # what I decided, I keep at
        if self.moments < getattr(self, "_quiet_until", 0):
            self.goal = None
            return
        best, use = None, self.usefulness()
        for e in self.candidates(conds, bag):
            way = self.make_plan(e, conds, bag, max_nodes=800)
            if way:
                cost = sum(s.cost() for s in way) / (1.0 + use.get(e, 0))
                if best is None or cost < best[0]:
                    best = (cost, e)
        if best is not None:
            self._set_goal(best[1], "новое, и я вижу как")
        else:
            self.goal, self._quiet_until = None, self.moments + 20   # (nothing new within reach: look around first)

    def _set_goal(self, g, why):
        if self.goal is not None and self.goal != g:
            self._note(f"вместо «{self.goal}»: {why}", g)
        else:
            self._note(f"решил: {why}", g)
        self.goal, self.goal_why, self.goal_t, self.goal_fails = g, why, self.moments, 0

    # ---------------------------------------------------------------- one moment
    def decide(self, did):
        """Learn what my last act did; choose what to do now: (action index, target) or None."""
        c = self.child
        if not self._priors_done or self.moments % 500 == 0:
            self.priors()
        self.moments += 1
        conds = {k for k, v in (getattr(c, "_concepts", None) or {}).items() if v}
        conds |= {"need:" + k for k, v in (getattr(c.mind, "drives", {}) or {}).items() if v > NEED_ON}   # (felt)
        bag = self.bag()
        raw_bag = dict((c.m or {}).get("items") or {})
        self._watch_implied(conds)
        mind_ = c.mind
        if self.prev is not None:
            conds0, bag0, meant = self.prev
            done = getattr(c, "_executed", None)
            kind, target = done if done else meant
            if not isinstance(target, str) and target is not None:
                target = meant[1] if meant[0] == kind and isinstance(meant[1], str) else None   # (a place: by what is there)
            if did is not None and did >= 0 and did < len(ACTIONS) and ACTIONS[did] != kind:
                kind, target = ACTIONS[did], None                  # (what my body really did)
            ok = ((c.m or {}).get("act") or {}).get("ok", True)
            hp_now = float((c.m or {}).get("health", 20) or 0)
            died = bool((c.m or {}).get("died") or ((c.m or {}).get("fev") or {}).get("died"))
            harm = 20.0 if died else max(0.0, getattr(self, "_hp", hp_now) - hp_now)
            drives_now = dict(getattr(mind_, "drives", {}) or {})
            relief = [d for d, v in getattr(self, "_drives", {}).items() if v - drives_now.get(d, 0.0) >= 0.1 and not died
                      and (d in drives_now or d in conds)]      # (eased by what I did - not ended by the dawn)
            got = self.learn(conds0, bag0, conds, raw_bag, kind, c.kind_of(target) if isinstance(target, str) else target,
                             ok, harm, relief)
            if got is not None and self.step is not None and self.step.op.kind == kind:
                if self.step.effect in got or self.holds(self.step.effect, conds, bag):
                    self.goal_fails = 0
                else:
                    self.goal_fails += 1
        if self.goal is not None and self.holds(self.goal, conds, bag):
            self._note("добился", self.goal)
            self.goal = None
        self.choose_goal(conds, bag)
        mind = c.mind
        self.step, choice, how = None, None, "explore"
        if self.goal is not None:
            way = self.make_plan(self.goal, conds, bag)
            acts = [s for s in (way or []) if s.op.kind]     # (a state that comes of having: nothing to do)
            if acts:
                self.plan, self.step = acts, acts[0]
                choice, how = (self.step.op.kind, self.step.op.target), "plan"
            else:
                self.goal_fails += 1
        if choice is None:                                   # no way I know: a need makes me try things here,
            need_now = self.goal is not None and self.goal in getattr(mind, "drive_goals", ())   # not wander off
            ex = self.taste(self.goal, bag) if need_now else None
            if ex is None and need_now and self.eased_by_hand(self.goal):
                ex = self.trial(self.goal, conds, bag)
            if ex is None and need_now:
                ex = self.relief(self.goal, conds, bag)
            if ex is None:
                ex = self.experiment(conds, need_now) if self.rng.random() < (0.8 if need_now else 0.5) else None
            choice, how = (ex, "try") if ex else (("explore", None), "explore")
        need_now = self.goal is not None and self.goal in getattr(mind, "drive_goals", ())
        pressing = need_now and (getattr(mind, "drives", {}) or {}).get(self.goal, 0.0) >= URGENT
        if not pressing:                                     # for curiosity, or a need that can wait, I do not do
            o = self.ops.get(choice) or self.ops.get((choice[0], c.kind_of(choice[1]) if isinstance(choice[1], str) else None))
            risk = self.step.risk if self.step is not None else o.risk(situation(conds)) if o is not None else 0.0
            if risk >= RISKY:                                # what cost me dearly here (out of my pit in the night
                choice, how, self.step = ("wait", None), "rest", None   # to look for food: I stay till the day)
        kind, target = choice
        if kind == "goto_place" and isinstance(target, str):
            places = c.places
            spot = places.home(c.m) if target == "home" else places.nearest(target, c.m, getattr(c, "age", None))
            target = spot if spot else target
        a = ACTIONS.index(kind)
        g = mind._neuron(self.goal) if self.goal else None
        step_goal = mind._neuron(self.step.effect.split("×")[0]) if self.step is not None else g
        mind.intent, mind.goal, mind.target = g, step_goal, g
        mind.how, mind.chose = how, "plan" if how == "plan" else "try"
        if self.step is not None:
            words = " → ".join(self._words(s) for s in self.plan[:6]) + f" ⇒ {self.goal}"
            mind.thought = f"Хочу {self.goal} ({self.goal_why}). План: {words}"
            c.plan_steps[step_goal] = {"kind": kind, "target": self.step.op.target, "effect": self.step.effect}
            c.imagined = words
        else:
            mind.thought = "Здесь это мне дорого стоило — пережду" if how == "rest" else \
                f"Хочу {self.goal or 'узнать новое'}: не знаю как — " + ("пробую" if how == "try" else "ищу")
        c.aim_at = (kind, target, step_goal) if target is not None else None
        self.prev = (conds, raw_bag, (kind, target if not isinstance(target, list) else self.step.op.target if self.step else None))
        self._hp = float((c.m or {}).get("health", 20) or 0)
        self._drives = dict(getattr(mind, "drives", {}) or {})
        return a

    @staticmethod
    def _words(s):
        from actions import RU
        from recall import ru

        t = s.op.target if isinstance(s.op.target, str) else ""
        return (RU.get(s.op.kind, s.op.kind) + (" " + ru(t) if t else "")).strip()

    # ---------------------------------------------------------------- memory
    def save(self, path):
        data = {"ops": [[k[0], k[1], o.n, {e: list(v) for e, v in o.prior.items()},
                         [[sorted(t[0]), sorted(t[1]), t[2], t[3], t[4]] for t in o.tries],
                         [[sorted(sit), [[sorted(r[0]), r[1]] for r in recs]] for sit, recs in o.by_sit.items()]]
                        for k, o in self.ops.items()],
                "had": sorted(self.had), "goal": self.goal, "why": self.goal_why, "implied": self.implied}
        tmp = path + ".saving"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)

    def load(self, path):
        if not os.path.exists(path):
            return
        d = json.load(open(path, encoding="utf-8"))
        for kind, target, n, prior, tries, *rest in d.get("ops", []):
            o = self.op(kind, target)
            o.n = n
            o.prior = {e: (v[0], tuple(v[1])) for e, v in prior.items()}
            for t in tries:
                o.tries.append((frozenset(t[0]), frozenset(t[1]), t[2], t[3], t[4] if len(t) > 4 else 0.0))
            if rest:
                for sit, recs in rest[0]:
                    o.by_sit[frozenset(sit)] = deque(((frozenset(r[0]), r[1]) for r in recs), maxlen=SIT_KEEP)
            else:                                            # (a memory from before situations: its tries sorted in)
                for t in o.tries:
                    o.remember(situation(t[0]), t[1], t[4])
            self._index(o)
        self.had = set(d.get("had", []))
        self.implied = d.get("implied", {})
        self.goal, self.goal_why = d.get("goal"), d.get("why", "")
