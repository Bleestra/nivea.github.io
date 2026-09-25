"""
Child: a whole brain that grows up - habits, mind (concepts, chains, skills, planning), limbic system.

Development follows a child's, by readiness rather than a clock:
  - newborn: high plasticity, lots of random movement (motor babbling), only simple feelings;
    no planning - the prefrontal cortex is not ready;
  - once expectations are learned (it can predict pain and pleasure): primary emotions, and the mind
    starts to set its own goals;
  - once it predicts the results of its own actions well (a self-model): self-conscious emotions;
  - once it has learned what its caregiver approves of: pride, shame and guilt.
Plasticity slowly decreases with age; sleep consolidates memories (replay); sadness makes the mind
replay (ruminate); boredom and interest raise exploration, sadness lowers it.
"""
import numpy as np

from limbic import Limbic
from mind import Mind

KINDS = ["zombie", "creeper", "cat", "mycat", "carer"]
SOUNDS = ["hiss", "boom", "groan", "purr"]


class Child:
    def __init__(self, n_actions, seed=0, taste=None, items=("log", "cobble", "apple", "fish", "rotten_flesh"),
                 eat_action=5, wait_action=10, kinds=KINDS, n_front=12):
        self.mind = Mind(n_actions, seed=seed, n_front=n_front)
        self.mind.urgent_ctx = (3, 7)             # danger (hungry or not): it may break into any intention
        self.mind.planning = False
        self.limbic = Limbic(seed, taste)
        self.items = list(items)
        self.feat = [2, 0, 0, 0, 0, 0, 0]
        self.prev = None          # (cells, action) for the self-model (cerebellar forward model)
        self.age = 0
        self.eat_action, self.wait_action, self.kinds = eat_action, wait_action, list(kinds)
        # dopamine says "better or worse than usual", not how good in absolute terms: the usual level
        # (tonic dopamine, the average reward of this life) is subtracted from what the mind and the habits learn
        self.relative_value = False
        self.r_avg, self.v_avg = 0.0, 0.0

    # ---------------------------------------------------------------- senses -> cells and concepts
    def senses(self, o):
        v = o["view"]
        nearest = min(o["near"], key=lambda x: x[2], default=None)
        goal = 0 if nearest is None or nearest[0] not in self.kinds else (self.kinds.index(nearest[0]) + 1) * 4 + min(3, nearest[2] // 2)
        sky = list(o["sky"]) + [8] * (8 - len(o["sky"]))
        ev = o["ev"]
        drives = ([o["hunger"] // 5, o["hp"] // 5, min(4, o["fatigue"] // 100), o["nausea"], o["walls"]] + sky
                  + [int(s in ev["sounds"]) for s in SOUNDS] + [ev["tone"]]
                  + [min(3, o["inv"].get(k, 0)) for k in self.items] + self.feat)
        return (v, min(o["inv"].get("log", 0), 7), goal, None, drives)

    def concepts(self, o):
        s = {"have:" + k: o["inv"].get(k, 0) for k in self.items}
        for k in self.kinds:
            s["near:" + k] = int(any(kind == k and d <= 2 for kind, _, d in o["near"]))
        if len(o["sky"]) == 8:
            s["sky:%d" % int(np.bincount(o["sky"], minlength=8).argmax())] = 1
        for k in (3, 5, 7):                            # touch: how closed-in I am (a perceptual category)
            s["walls>=%d" % k] = int(o["walls"] >= k)
        s["fed"] = int(o["hunger"] >= 18)
        s["healthy"] = int(o["hp"] >= 15)
        return s

    def _worth(self, state):
        """What the things I have and the state I am in are worth to me (learned, secondary values)."""
        m = self.mind
        n = len(m.names)
        if n == 0:
            return 0.0
        if getattr(self, "_v_age", -1) < 0 or self.age - self._v_age >= 500 or len(self._v) != n:
            v = m.instrumental(m.frontier(np.maximum(m.R[:n], 0)))
            means = getattr(m, "means_only", ())
            keep = ~m._mask(means) if means else np.ones(n, bool)
            self._v, self._v_age = np.minimum(v * keep, 3.0), self.age
        total = 0.0
        for k, x in state.items():
            if x <= 0:
                continue
            if k.startswith("stored:"):             # what I put away is still mine (object permanence)
                k = "have:" + k[7:]
            i = m.idx.get(k)
            if i is not None and i < n:             # more of a thing is worth more, but less and less:
                total += self._v[i] * 2.0 * (1.0 - 0.5 ** min(float(x), 30.0))   # 1, 1.5, 1.75 ... up to 2
        return total

    # ---------------------------------------------------------------- one moment
    def step(self, o, act_prev, front_before, inv_before, extra_reward=0.0):
        m, L = self.mind, self.limbic
        self.age += 1
        obs = self.senses(o)
        cells = m.flat.cells(obs)
        # the self-model: how well do I predict what my own action will put in front of me?
        if self.prev is not None:
            pc, pa = self.prev
            key = (pc[:26] * 7 + pa) & ((1 << 20) - 1)
            pred = m.flat.F[key].sum(0)
            p = np.exp(pred - pred.max())
            p /= p.sum()
            L.fm_surprise = float(-np.log(p[int(obs[0][7])] + 1e-6))
            L.fm_err += 0.001 * (float(p.argmax() != obs[0][7]) - L.fm_err)
        else:
            L.fm_surprise = 0.0
        q = m.flat.W[cells].sum(0)
        v_now = float(q.max())
        delta = 0.95 * v_now - getattr(self, "v_prev", 0.0)
        self.v_prev = v_now
        n = len(m.names)
        tried = m.tries[:n] >= 1
        competence = float(m.comp[:n][tried].mean()) if tried.any() else 0.3
        r, self.feat = L.feel(o, act_prev, front_before, cells, v_now, delta, inv_before, competence, m.last_outcome,
                              extra=extra_reward)
        obs = self.senses(o)                          # with the fresh feelings
        stage = L.stage()
        m.planning = stage >= 1                       # the prefrontal cortex matures
        m.alpha = 0.3 * (0.4 + 0.6 * np.exp(-self.age / 60000))
        E = L.e
        explore = float(np.clip(getattr(self, "explore_min", 0.03) + 0.3 * np.exp(-self.age / 15000) + 0.2 * E["boredom"] + 0.1 * E["interest"]
                                - 0.1 * E["sadness"], 0.02, 0.5))
        if o["ev"]["slept"]:
            L.sleep()
            m._replay(200)                            # sleep: consolidation
        if L.lingering["sadness"] > 0.3 or L.lingering["grief"] > 0.3:
            m._replay(8)                              # rumination: going over it again and again
        # context for values: what the sky looks like (bright / warm / dark) and whether danger is felt
        sky = int(np.bincount(o["sky"], minlength=8).argmax())
        ctx = 3 if E["fear"] > 0.3 or any(k in ("zombie", "creeper") and d <= 3 for k, _, d in o["near"]) else (0 if sky in (1, 2) else 1 if sky in (3, 4, 5, 6) else 2)
        if getattr(self, "hunger_ctx", False) and o["hunger"] < 12:
            ctx += 4                                  # the body's state is part of the situation: hungry
        value = L.appraised
        if getattr(self, "cortical_dopamine", False):
            # the cortex tells the midbrain what the present situation is worth for what it leads to (OFC -> VTA):
            # getting a means to something good feels good now, losing everything I carried hurts
            state = self.concepts(o)
            phi = self._worth(state)
            r += 0.95 * phi - getattr(self, "phi_prev", phi)
            self.phi_prev = phi
        # emotions come with innate action tendencies (Frijda): fear vetoes what hurt me (the amygdala), anger
        # urges me to strike the one I blame while he is near - an urge, not an order: the mind weighs it
        # with everything it has learned (and fear of what striking him cost me before still vetoes it)
        atk = getattr(self, "attack_action", None)
        if atk is not None:
            blamed_near = any(L.grudge(k) > 0.1 for k, _, d in o["near"] if d <= 8)
            m.tendency = np.zeros(m.nA, np.float32)
            m.tendency[atk] = E["anger"] if blamed_near else 0.0
        if self.relative_value:
            self.r_avg += 0.001 * (r - self.r_avg)
            self.v_avg += 0.001 * (value - self.v_avg)
            r, value = r - self.r_avg, value - self.v_avg
        a = m.step(obs, state if getattr(self, "cortical_dopamine", False) else self.concepts(o), r, done=bool(o["ev"]["died"]), explore=explore, value=value, ctx=ctx)
        # insula veto: food that once made me sick is refused unless I am starving (learned in one shot)
        if a == self.eat_action:
            foods = [k for k in ("apple", "fish", "rotten_flesh") if o["inv"].get(k)]
            bad = [L.aversion.get(("eat", f), 0.0) for f in foods]
            if foods and all(b < -0.2 for b in bad) and o["hunger"] > 3:
                a = self.wait_action
        self.prev = (m.last_cells, a)
        return a
