"""
Mind: logical chains, skills, reasoning and self-knowledge as learned synapses.

Nothing here is a rule about the world. There are only populations of neurons and plasticity:

  concept neurons  (entorhinal/hippocampal)   one neuron per thing the agent has ever noticed about
                   itself: "I have planks", "I see the sky", "I am free (not stuck)"... A neuron is
                   grown the first time the thing happens (neurogenesis). An EVENT is a neuron's onset
                   (the value goes up: got one more log, came out under the sky).
  chain synapses   (prefrontal-hippocampal)   C[p, e]: how reliably concept p was active just before
                   event e happened. Learned by a running average each time e happens; compared with
                   how often p is active at all (lift). Strong, specific synapses = learned
                   preconditions: "logs are obtained only under the sky", "a stone pickaxe comes only
                   after I have cobblestone and sticks". These are the logical chains.
  skill synapses   (basal ganglia, goal-conditioned)   G[cell x goal, action]: how to make event g
                   happen from here. Learned by TD while pursuing g, and by hindsight replay: whenever
                   ANY event happens, the hippocampus replays the last steps and teaches the skill for
                   that event ("this is how I got out of the pit"). One set of synapses holds every
                   skill; nothing is stored as a program.
  reasoning        (prefrontal spreading activation)   desire flows backwards through the chain
                   synapses from a target to the concepts that are missing, until it reaches something
                   that can be done now; that becomes the current subgoal. The same activity, read
                   out, is the explanation: "I want an iron pickaxe; for that I need ingots; ...".
  self-knowledge   (anterior cingulate / insula)   competence neurons: how often I succeed when I
                   try each goal; and a curiosity about myself - goals I have tried rarely or fail at
                   are the most interesting. The value of an event (dopamine) is learned too.
  action-outcome   (dorsomedial striatum, goal-directed system) which ACTION made an event happen and
                   in which context: 'facing a tree + hit -> a log'. Counted from a few experiences;
                   when the context is there and the action worked before, it is chosen directly.
  habits           the flat striatum (BrainAgent) keeps learning from reward all the time, acts
                   when there is no plan (exploring, discovering new events) and gently biases
                   the skills (habit=0.3).
"""
import os
from collections import deque

import numpy as np

from brain_agent import BrainAgent

GMASK = (1 << 21) - 1


class Mind:
    def __init__(self, n_actions, seed=0, gamma=0.95, alpha=0.3, budget=60, trace=60, n_concepts=512,
                 explore_steps=40, habit=0.3, **flat_kw):
        self.nA, self.g, self.alpha, self.budget = n_actions, gamma, alpha, budget
        self.rng = np.random.default_rng(seed + 7)
        flat_kw.setdefault("emotions", True)
        flat_kw.setdefault("mood", False)
        self.flat = BrainAgent(n_actions, seed=seed, **flat_kw)
        self.G = np.full((GMASK + 1, n_actions), 0.0, np.float32)     # skill synapses
        E = n_concepts
        self.names, self.idx = [], {}
        self.C = np.zeros((E, E), np.float32)      # chain synapses C[pre, event]
        self.base = np.zeros(E, np.float32)        # how often each concept is active at all
        self.nev = np.zeros(E, np.int64)           # how many times each event happened
        self.R = np.zeros(E, np.float32)           # learned value of each event (dopamine)
        self.Rc = np.zeros((E, 4), np.float32)     # ... in each context (e.g. day / dusk / night / danger)
        self.nc = np.zeros((E, 4), np.float32)
        self.succ_c = np.zeros((E, 4), np.float32)  # competence in each context too: sunsets happen only at dusk
        self.tries_c = np.zeros((E, 4), np.float32)
        self.ctx = 0
        self.succ = np.zeros(E, np.float32)       # competence: successes / attempts per goal
        self.tries = np.zeros(E, np.float32)
        self.val = np.zeros(E, np.float32)         # current concept values
        self.recent = deque(maxlen=trace)          # hippocampus: the last moments (cells, a, next, events)
        self.memory = deque(maxlen=20000)          # and a longer store for replay
        self.goal, self.target, self.goal_t, self.explore_left = None, None, 0, 0
        self.goal_ctx = 0
        self.explore_steps = explore_steps
        self.habit = habit                         # how much habits (flat striatum) bias a skill
        self._last = self._fprev = None            # the previous moment (for learning)
        self.thought = ""
        self.steps = 0
        self.newborn = True
        self.planning = True                       # the prefrontal cortex can be switched on later (development)
        self.last_outcome = None                   # True: the plan failed, False: it succeeded, None: nothing
        self.last_fq = None
        self.ao = {}                               # (event, action) -> [successes, context counts, attempts]

    # ---------------------------------------------------------------- concept neurons
    def _neuron(self, name):
        if name not in self.idx:
            if len(self.names) >= len(self.C):
                return None
            self.idx[name] = len(self.names)
            self.names.append(name)
        return self.idx[name]

    def perceive(self, state):
        """state: {concept: value}. Returns the events (neurons whose value went up)."""
        new = np.zeros_like(self.val)                  # what is not perceived now is not true now
        for k, v in state.items():
            i = self._neuron(k)
            if i is not None:
                new[i] = float(v)
        ev = np.nonzero(new > self.val + 1e-9)[0]
        before = self.val > 0
        self.val = new
        return ev, before

    def pre(self, e, min_n=3):
        """Learned preconditions of event e: concepts reliably (and specifically) active before it."""
        if self.nev[e] < min_n:
            return np.zeros(0, np.int64)
        n = len(self.names)
        c = self.C[:n, e]
        ok = c >= 0.9
        ok[e] = False
        return np.nonzero(ok)[0]

    # ---------------------------------------------------------------- skills
    def gkeys(self, cells, g):
        return ((cells * 0x9E3779B1 + (int(g) + 1) * 0x85EBCA77) >> 7) & GMASK

    def _q_update(self, cells, a, nxt, evs, g, lr):
        """One-step Q-learning of the skill 'make g happen' on one remembered moment."""
        k = self.gkeys(cells, g)
        q = self.G[k, a].sum()
        tgt = 1.0 if g in evs else self.g * self.G[self.gkeys(nxt, g)].sum(0).max()
        self.G[k, a] += lr * (tgt - q) / len(k)

    def _hindsight(self, e):
        """Replay the last moments backwards: this is how event e is made to happen."""
        for cells, a, nxt, evs in reversed(self.recent):
            self._q_update(cells, a, nxt, evs, e, self.alpha)

    def _replay(self, n=16):
        """Hippocampal replay while living: random old moments, for the current goal and for random
        known goals - skills keep improving, actions that bring no progress fade."""
        if len(self.memory) < 50:
            return
        known = np.nonzero(self.nev[:len(self.names)] > 0)[0]
        if len(known) == 0:
            return
        for _ in range(n):
            cells, a, nxt, evs = self.memory[int(self.rng.integers(len(self.memory)))]
            g = self.goal if (self.goal is not None and self.rng.random() < 0.5) else int(self.rng.choice(known))
            self._q_update(cells, a, nxt, evs, g, self.alpha * 0.5)

    # ---------------------------------------------------------------- action -> outcome (goal-directed)
    def _ao_learn(self, ev, before, a):
        n = len(self.names)
        for e in ev:
            rec = self.ao.get((int(e), a))
            if rec is None:
                rec = self.ao[(int(e), a)] = [0.0, np.zeros(len(self.C), np.float32), 0.0]
            rec[0] += 1
            rec[1][:n] += before[:n]

    def _ao_need(self, rec):
        return np.nonzero(rec[1] / rec[0] >= 0.9)[0]

    def _ao_attempt(self, a, active):
        for (e, aa), rec in self.ao.items():
            if aa == a and rec[0] >= 2 and active[self._ao_need(rec)].all():
                rec[2] += 1

    def ao_plan(self, g, active):
        """The action that made g happen before in the context I am in now (or None)."""
        best, bp = None, 0.25
        for (e, a), rec in self.ao.items():
            if e != g or rec[0] < 2:
                continue
            if not active[self._ao_need(rec)].all():
                continue
            p = rec[0] / (rec[2] + 1.0)
            if p > bp:
                best, bp = a, p
        return best

    # ---------------------------------------------------------------- what I was told
    def tell(self, claims, values, source="книга"):
        """Beliefs from reading or from someone's words: weak chain synapses and expected values
        that experience will confirm or override (as if seen a few times, not certain)."""
        self.told = getattr(self, "told", {})
        for target, pres in claims:
            e = self._neuron(target)
            if e is None:
                continue
            for p in pres:
                i = self._neuron(p)
                if i is not None:
                    self.C[i, e] = max(self.C[i, e], 0.95)
            self.nev[e] = max(self.nev[e], 3)
            self.told[target] = source
        for c, v in values.items():
            e = self._neuron(c)
            if e is None:
                continue
            self.nev[e] = max(self.nev[e], 1)
            self.R[e] = max(self.R[e], v)
            self.Rc[e] = np.maximum(self.Rc[e], v)
            self.nc[e] = np.maximum(self.nc[e], 2)
            self.told[c] = source

    # ---------------------------------------------------------------- reasoning
    @property
    def comp(self):
        """How sure I am that I can do it (Laplace estimate from my own history)."""
        return (self.succ + 1) / (self.tries + 2)

    def desire(self, active):
        """Value of each thing I could want: learned value (dopamine) + curiosity about myself
        (goals I have rarely tried are interesting: what can I do?)."""
        n = len(self.names)
        seen = self.nev[:n] > 0
        known = self.nc[:n, self.ctx] >= 2                # in this context I know how good it is
        val = np.where(known, self.Rc[:n, self.ctx], 0.3 * self.R[:n])   # unsure how good it is here
        d = np.maximum(val, 0) + 0.15 / np.sqrt(1 + self.tries[:n])
        d[~seen | active[:n]] = -1
        return d

    def reason(self, active, target):
        """Spread desire backwards through chain synapses; return (subgoal, chain) or (None, chain)."""
        act = {target: 1.0}
        frontier, chain, ready = [target], [], []
        for _ in range(12):
            nxt = []
            for e in frontier:
                missing = [p for p in self.pre(e) if not active[p]]
                if not missing:
                    ready.append(e)
                for p in missing:
                    if p not in act:
                        act[p] = act[e] * 0.9
                        chain.append((e, p))
                        nxt.append(p)
            frontier = nxt
            if not frontier:
                break
        if not ready:
            return None, chain
        return max(ready, key=lambda e: act[e] * (0.3 + self.comp[e])), chain

    def deliberate(self, active):
        """Think: for the things I want most, what can I do now that leads there, and how likely
        am I to manage it? Choose the best (target, next step)."""
        d = self.desire(active)
        if len(d) == 0 or d.max() <= 0:
            return None
        comp = self.comp
        n = len(self.names)
        tc = self.tries_c[:n, self.ctx]
        comp = np.where(tc >= 2, (self.succ_c[:n, self.ctx] + 1) / (tc + 2), comp[:n])
        best, bs = None, 0.0
        for t in np.argsort(-d)[:8]:
            if d[t] <= 0:
                break
            sub, chain = self.reason(active, t)
            if sub is None:
                continue
            depth = 1 + sum(1 for _ in chain)
            score = d[t] * comp[sub] * 0.9 ** depth * (0.8 + 0.4 * self.rng.random())
            if score > bs:
                best, bs = (t, sub, chain), score
        if best is None or bs < getattr(self, "min_desire", 0.0):
            return None                                # nothing worth the effort: habits and curiosity act
        self.target = best[0]
        self.thought = self.explain(best[0], best[2], best[1])
        return best[1]

    def explain(self, t, chain, sub):
        name = self.names
        parts = [f"хочу {name[t]}"]
        for e, p in chain[:6]:
            parts.append(f"для «{name[e]}» нужно «{name[p]}»")
        parts.append(f"сейчас делаю: {name[sub]}")
        return "; ".join(parts)

    def why(self, e):
        """What I have learned about how to get e (the chain, read out of the synapses)."""
        out, seen, stack = [], set(), [(e, 0)]
        while stack:
            x, depth = stack.pop()
            if x in seen or depth > 10:
                continue
            seen.add(x)
            ps = self.pre(x)
            if len(ps):
                out.append(f"{self.names[x]} ← " + " + ".join(self.names[p] for p in ps))
            stack += [(p, depth + 1) for p in ps]
        return out

    # ---------------------------------------------------------------- one moment of life
    def step(self, obs, state, r, done=False, explore=0.1, value=None, ctx=0):
        self.ctx = ctx
        ev, before = self.perceive(state)
        n = len(self.names)
        active = self.val > 0
        self.base[:n] += 0.005 * (active[:n] - self.base[:n])
        if self.newborn:                                 # waking up is not an event
            ev, self.newborn = ev[:0], False
        for e in ev:                                     # something happened
            if not before[e]:                            # it became true: what made it possible?
                self.nev[e] += 1
                lr = max(1.0 / self.nev[e], 0.05)
                self.C[:n, e] += lr * (before[:n] - self.C[:n, e])
                v = r if value is None else value         # how good it was for me, all things considered
                self.R[e] += lr * (v - self.R[e])
                self.nc[e, ctx] += 1
                self.Rc[e, ctx] += max(1.0 / self.nc[e, ctx], 0.05) * (v - self.Rc[e, ctx])
        cells = self.flat.cells(obs)
        if self._last is not None and len(ev):
            self._ao_learn(ev, before, self._last[1])
        if self._last is not None:                       # remember the moment that just passed
            tr = (self._last[0], self._last[1], cells, frozenset(int(e) for e in ev))
            self.recent.append(tr)
            self.memory.append(tr)
        for e in ev:
            self._hindsight(e)                           # every time: how did I do that?
        # the current plan: success, failure or keep going
        reached = self.goal is not None and self.goal in ev
        self.last_outcome = False if reached else (True if self.goal is not None and self.steps - self.goal_t > self.budget else None)
        if reached:
            self.succ[self.goal] += 1
            self.succ_c[self.goal, self.goal_ctx] += 1
        elif self.goal is not None and (self.steps - self.goal_t > self.budget or done):
            self.explore_left = self.explore_steps       # it did not work: look around a bit
        self._replay()
        if reached or done or (self.goal is not None and self.steps - self.goal_t > self.budget):
            self.goal = None
        if done:
            self.explore_left = 0
        if self.goal is None and self.explore_left <= 0 and not done and self.planning:
            self.goal = self.deliberate(active)
            self.goal_t = self.steps
            if self.goal is not None:
                self.tries[self.goal] += 1
                self.goal_ctx = self.ctx
                self.tries_c[self.goal, self.ctx] += 1
                if self.tries_c[self.goal, self.ctx] > 30:
                    self.tries_c[self.goal, self.ctx] *= 0.97
                    self.succ_c[self.goal, self.ctx] *= 0.97
                if self.tries[self.goal] > 30:           # old experience fades: people change
                    self.tries[self.goal] *= 0.97
                    self.succ[self.goal] *= 0.97
        # act: a skill if there is a plan, else habits and exploration
        a_flat, fcells, fq = self.flat.act(obs, explore if self.goal is None else 0.0)
        self.last_fq, self.last_cells = fq, fcells
        if self.goal is not None:
            q = self.G[self.gkeys(cells, self.goal)].sum(0) + self.habit * (fq - fq.max())
            if self.flat.emo:
                q = q + self.flat.fear_veto(cells)                         # fear still vetoes (contingency)
            eps = 0.03 + 0.2 * (1 - self.comp[self.goal])
            a = int(self.rng.integers(self.nA)) if self.rng.random() < eps else int(np.argmax(q + self.rng.random(self.nA) * 1e-6))
            direct = self.ao_plan(self.goal, active)     # I know what does it, and I can do it here
            if direct is not None and self.rng.random() > 0.1:
                a = int(direct)
        else:
            self.explore_left -= 1
            a = a_flat
        if self._fprev is not None:                      # habits learn from reward all the time
            c0, a0 = self._fprev
            self.flat.learn(c0, a0, r, obs, fcells, fq, a, done)
        self._ao_attempt(a, active)
        self._fprev = None if done else (fcells, a)
        self._last = None if done else (cells, a)
        if done:
            self.recent.clear()
            self.val[:] = 0
            self.newborn = True
        self.steps += 1
        return a

    # ---------------------------------------------------------------- memory
    def save(self, path):
        extra = {"FQ": self.flat.FQ, "FB": self.flat.FB} if self.flat.FQ is not None else {}
        np.savez(path, G=self.G, C=self.C, base=self.base, nev=self.nev, R=self.R, Rc=self.Rc, nc=self.nc, succ_c=self.succ_c, tries_c=self.tries_c, succ=self.succ,
                 tries=self.tries, names=np.array(self.names, dtype=object), W=self.flat.W, F=self.flat.F,
                 steps=self.steps, **extra)

    def load(self, path):
        if not os.path.exists(path):
            return False
        z = np.load(path, allow_pickle=True)
        na = min(z["G"].shape[1], self.nA)
        self.G[:, :na] = z["G"][:, :na]
        for k in ("C", "base", "nev", "R", "succ", "tries", "Rc", "nc", "succ_c", "tries_c"):
            if k in z.files:
                getattr(self, k)[...] = z[k]
        self.names = list(z["names"])
        self.idx = {k: i for i, k in enumerate(self.names)}
        self.flat.W[:, :na], self.flat.F[:] = z["W"][:, :na], z["F"]
        if self.flat.FQ is not None and "FQ" in z.files:
            self.flat.FQ[:, :na] = z["FQ"][:, :na]
        if self.flat.FB is not None and "FB" in z.files:
            if z["FB"].shape == self.flat.FB.shape:
                self.flat.FB[:] = z["FB"]
        self.steps = int(z["steps"])
        return True
