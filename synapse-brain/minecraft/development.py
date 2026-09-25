"""
The need to develop (competence, growth): innate, as in people - it feels good to be able to do more than
before, and it becomes uneasy when for a long time nothing grows.

  growth       joy when my abilities grow: a better tool tier than ever, a new step of the game's own path
               (the advancement tree a player sees with L), a new world entered;
  stagnation   a mild unease that grows while nothing new happens (no new thing, no new step), up to a limit;
  aspiration   the next step of the path becomes wanted: the first advancement I have not reached whose parent I
               have, and what it asks for (to hold iron, to enter the Nether...) gets an expected value;
  the guide    to learn how to get there, I read the guide (the Minecraft Wiki) about it, and about what that
               needs in turn - as a person opens a guide when they want to progress.

Nothing here says what to do: the path says where the game goes (it is shown to every player), the guide
says how the world works, and the mind decides by its own values and plans whether and when.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TIERS = ["wooden", "stone", "iron", "golden", "diamond", "netherite"]
TIER_RANK = {"wooden": 1, "stone": 2, "golden": 2, "iron": 3, "diamond": 4, "netherite": 5}
MAIN_PATH = ("story", "nether", "end")        # the game's main line first; the other trees after
ASPIRE = 0.7                                   # how much the next step is wanted
ASPIRE_MAX, ASPIRE_GROW = 3.0, 10000           # ... and how it grows while I stand still (an unmet need grows, as hunger)
GROWTH_JOY = 0.8
STAGNATION_AFTER, STAGNATION_MAX = 3000, 0.02  # moments without anything new; the unease per moment at most


def tier(items):
    best = 0
    for k in items:
        for t, r in TIER_RANK.items():
            if k.startswith(t + "_") and k.rsplit("_", 1)[-1] in ("pickaxe", "sword", "axe", "shovel", "helmet",
                                                               "chestplate", "leggings", "boots"):
                best = max(best, r)
    return best


class Development:
    def __init__(self, guide=None):
        path = os.path.join(HERE, "knowledge", "progress.json")
        self.path = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        self.guide = guide
        self.best_tier, self.worlds = 0, {"overworld"}
        self.last_growth, self.aimed, self.read = 0, None, set()
        self.step_title = ""

    # ---------------------------------------------------------------- the path
    def _depth(self, aid):
        d, a = 0, self.path.get(aid)
        while a is not None and a["parent"]:
            d, a = d + 1, self.path.get(a["parent"])
        return d

    def _order(self):
        trees = MAIN_PATH + ("adventure", "husbandry")
        return sorted(self.path, key=lambda aid: (trees.index(self.path[aid]["tree"]) if self.path[aid]["tree"] in trees else 9,
                                                  self._depth(aid)))

    def reached(self, me, items):
        """Steps I have reached: announced advancements, or everything they ask for I have already had."""
        done = set(me.me.get("advancements", [])) if me else set()
        for aid, a in self.path.items():
            if a["wants"] and all(any(self._have(c, items) for c in alts) for alts in a["wants"]):
                done.add(aid)
        return done

    def _have(self, concept, items):
        kind, _, what = concept.partition(":")
        return what in items if kind == "have" else what in self.worlds if kind == "in" else False

    def _passed(self, aid, done):
        """A step without things to get (e.g. 'follow an eye of ender') is passed when its parent is."""
        a = self.path.get(aid)
        if a is None or aid in done:
            return True
        return not a["wants"] and (a["parent"] is None or self._passed(a["parent"], done))

    def next_step(self, done):
        """The first step of the path not reached yet, whose parent is reached."""
        for aid in self._order():
            a = self.path[aid]
            if a["wants"] and aid not in done and (a["parent"] is None or self._passed(a["parent"], done)):
                return aid
        return None

    # ---------------------------------------------------------------- one moment
    def moment(self, m, child, me, age):
        """Returns (reward, [(kind, words)]) - what growing (or not) feels like this moment."""
        reward, events = 0.0, []
        items = (me.me.get("known_items", {}) if me else m.get("items", {}))
        t = tier(items)
        if t > self.best_tier:
            if self.best_tier > 0 or t > 1:
                reward += GROWTH_JOY
                events.append(("develop", f"Я стал сильнее: инструменты уровня {TIERS[min(t, 6) - 1] if t else ''}"))
            self.best_tier, self.last_growth = t, age
        dim = str(m.get("dim", "overworld"))
        if dim not in self.worlds:
            self.worlds.add(dim)
            reward += GROWTH_JOY
            self.last_growth = age
            events.append(("develop", f"Я попал в новый мир: {dim}"))
        if m.get("advancements"):
            self.last_growth = age
        if m.get("_unease", 0) > 0.3 and "safe_night" not in self.read:    # afraid in the dark: what does the guide say?
            events += self.study("safe_night", child, depth=2)
        idle = age - self.last_growth
        if idle > STAGNATION_AFTER:                       # nothing grows: the unease of standing still
            reward -= min(STAGNATION_MAX, 0.000005 * (idle - STAGNATION_AFTER))
            # ... and the wish to grow gets stronger, the longer it is not met
            want = min(ASPIRE_MAX, ASPIRE * (1 + (idle - STAGNATION_AFTER) / ASPIRE_GROW))
            if self.aimed in self.path and want >= getattr(self, "aspire_now", ASPIRE) + 0.3:
                self.aspire_now = want
                wants = {c: want for alts in self.path[self.aimed]["wants"] for c in alts}
                child.mind.tell([], wants, source="путь развития")
                events.append(("develop", f"Давно не расту — всё сильнее хочу «{self.step_title}» (желание {want:.1f})"))
        # aspiration: the next step of the path, and reading how to get there
        nxt = self.next_step(self.reached(me, items))
        if nxt and nxt != self.aimed:
            self.aimed, self.aspire_now = nxt, ASPIRE
            step = self.path[nxt]
            self.step_title = step["title"]
            wants = {c: ASPIRE for alts in step["wants"] for c in alts}
            child.mind.tell([], wants, source="путь развития")
            what = ", ".join(sorted({c.split(":", 1)[1] for c in wants}))[:120]
            events.append(("develop", f"Следующая ступень: «{step['title']}» — нужно {what}"))
            for alts in step["wants"]:
                for c in alts[:2]:
                    events += self.study(c, child, depth=2)
        return reward, events

    def study(self, concept, child, depth=2):
        """Read the guide about getting this, and about what that needs in turn (a little way down)."""
        if self.guide is None or concept in self.read or depth <= 0:
            return []
        self.read.add(concept)
        self.guide.refresh()
        found = self.guide.about(concept)
        if not found:
            return []
        claims = [c for c, _, _ in found]
        child.mind.tell(claims, {}, source="гайд")
        (_, pres), said, page = found[0]
        out = [("guide", f"Прочитал в гайде ({page}): «{said[:160]}»")]
        for c in {p for _, ps in claims for p in ps if p.startswith(("have:", "hold:"))}:
            out += self.study(c, child, depth - 1)
        return out

    def state(self):
        return {"best_tier": self.best_tier, "worlds": sorted(self.worlds), "last_growth": self.last_growth,
                "aimed": self.aimed, "read": sorted(self.read)[-200:]}

    def load(self, st):
        self.best_tier, self.worlds = st.get("best_tier", 0), set(st.get("worlds", ["overworld"]))
        self.last_growth, self.read = st.get("last_growth", 0), set(st.get("read", []))
