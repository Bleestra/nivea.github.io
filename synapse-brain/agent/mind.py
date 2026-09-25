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

No fixed ceilings on thinking: concept neurons are grown for as long as there is memory (the arrays
double when full); chain synapses are kept sparse (a concept links to the few dozen things that come
before it, not to every concept), so a million concepts cost what their real links cost; reasoning
follows a chain backwards to its end, however long; the value of means flows back through every link;
patience with a goal is learned from how long it took before; the skill synapses double when they
get crowded, as far as the memory the brain is given allows (grow_skills).
"""
import os
import pickle
import time
from collections import deque

import numpy as np

from brain_agent import BrainAgent

GMASK = (1 << 21) - 1          # the skill synapses at birth; they grow (grow_skills)
FORGET = 0.01                  # a chain synapse weaker than this is gone (it is only kept sparse)
LIVED_N = 5                    # a condition I found myself counts after this many times (not a first coincidence)
NO_I, NO_V = np.zeros(0, np.int32), np.zeros(0, np.float32)
def swap_in(tmp, path, tries=10):
    """Put the freshly written file in place of the old one (a scanner may hold it for a moment on Windows)."""
    for k in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if k == tries - 1:
                raise
            time.sleep(0.3)


PER_CONCEPT = ("base", "nev", "R", "Rc", "nc", "succ_c", "tries_c", "succ", "tries", "val", "took")


class Mind:
    def __init__(self, n_actions, seed=0, gamma=0.95, alpha=0.3, budget=60, trace=200, n_concepts=4096,
                 explore_steps=40, habit=0.3, max_concepts=None, memory=100000, think=0.05, **flat_kw):
        self.nA, self.g, self.alpha, self.budget = n_actions, gamma, alpha, budget
        self.rng = np.random.default_rng(seed + 7)
        flat_kw.setdefault("emotions", True)
        flat_kw.setdefault("mood", False)
        self.flat = BrainAgent(n_actions, seed=seed, **flat_kw)
        self.G = np.full((GMASK + 1, n_actions), 0.0, np.float32)     # skill synapses
        self.gmask = GMASK
        self.gtouch = None                         # rows written since the table last doubled
        E = n_concepts                             # room at birth; it doubles whenever it is full
        self.max_concepts = max_concepts           # None: as many as memory holds
        self.think = think                         # seconds to weigh wishes in one deliberation (breadth, not depth)
        self.names, self.idx = [], {}
        self.cols = {}                             # chain synapses onto event e: (preceding concepts, strengths)
        self.told_pre = {}                         # event -> the conditions I was told (read, heard), not found myself
        self._edges = None                         # the strong ones, gathered (for the value of means)
        self._masks = {}                           # which concepts' names start with what
        self.took = np.zeros(E, np.float32)        # how many moments reaching each goal usually takes
        self.base = np.zeros(E, np.float32)        # how often each concept is active at all
        self.nev = np.zeros(E, np.int64)           # how many times each event happened
        self.R = np.zeros(E, np.float32)           # learned value of each event (dopamine)
        self.Rc = np.zeros((E, 8), np.float32)     # ... in each context (day / dusk / night / danger; x hungry or not)
        self.nc = np.zeros((E, 8), np.float32)
        self.succ_c = np.zeros((E, 8), np.float32)  # competence in each context too: sunsets happen only at dusk
        self.tries_c = np.zeros((E, 8), np.float32)
        self.ctx = 0
        self.succ = np.zeros(E, np.float32)       # competence: successes / attempts per goal
        self.tries = np.zeros(E, np.float32)
        self.val = np.zeros(E, np.float32)         # current concept values
        self.recent = deque(maxlen=trace)          # hippocampus: the last moments (cells, a, next, events, did it work)
        self.lam = 0.8                             # how fast the credit for an event fades, moment by moment back
        self.memory = deque(maxlen=memory)         # and a longer store for replay
        self.goal, self.target, self.goal_t, self.explore_left = None, None, 0, 0
        self.goal_ctx = 0
        self.explore_steps = explore_steps
        self.habit = habit                         # how much habits (flat striatum) bias a skill
        self._last = self._fprev = None            # the previous moment (for learning)
        self._last_goal, self.last_ok = None, None # the step the last action was for; did it work (the body says)
        self._same_n, self.external = 0, False     # how many times in a row the same action; was it given to me
        self.thought = ""
        self.steps = 0
        self.newborn = True
        self.planning = True                       # the prefrontal cortex can be switched on later (development)
        self.last_outcome = None                   # True: the plan failed, False: it succeeded, None: nothing
        self.last_fq = None
        self.ao = {}                               # (event, action) -> [successes, (concepts, counts), attempts]
        self._ao_a, self._ao_e = {}, {}            # the same records by action and by event
        self.a_count = np.zeros(n_actions, np.float32)   # how often I did each action at all
        self.a_ok, self.a_n = np.zeros(n_actions, np.float32), np.zeros(n_actions, np.float32)   # ... and it worked
        self._use, self._use_t = None, 0           # what each action brings, on the whole (cached)
        self.tried = {}                            # situation -> how often each action was tried there
        self.episodic = None                       # every moment lived (episodic.Episodic), if given one
        self._ep_prev, self.recalled = None, None
        self.helps = {}                            # goal -> [tries, successes, {concept: [tries with it, successes]}]
        self.helps_prior = {}                      # goal -> {concept: (tries, successes)} - what I read helps
        self.helper_kinds = None                   # which concepts can be helpers (None: any)
        self._goal_on = None                       # what was true when I set out for the current goal
        # intention (prefrontal working memory): what I have decided to do is kept, and is not given up for
        # a passing wish - only when done, when it keeps failing, when there is no way, or in danger
        self.intent, self.intent_t, self.intent_fails = None, 0, 0
        self.intent_saved = None                   # what I was doing before a danger broke in (to go back to)
        self.commit = 2.0                          # how much more a decided thing weighs than a new wish
        self.urgent_ctx = ()                       # contexts in which danger may break into any intention
        self.intent_log = deque(maxlen=50)         # (step, what happened to my intention, in words)

    # ---------------------------------------------------------------- concept neurons
    def _grow(self):
        """Neurogenesis has no ceiling: when the room for concepts is full, it doubles."""
        E = len(self.val)
        for k in PER_CONCEPT:
            x = getattr(self, k)
            y = np.zeros((2 * E,) + x.shape[1:], x.dtype)
            y[:E] = x
            setattr(self, k, y)

    def _neuron(self, name):
        if name not in self.idx:
            if self.max_concepts is not None and len(self.names) >= self.max_concepts:
                return None
            if len(self.names) >= len(self.val):
                self._grow()
            self.idx[name] = len(self.names)
            self.names.append(name)
        return self.idx[name]

    def _mask(self, prefixes):
        """Which concepts' names start with these prefixes (kept as neurons are grown; names never change)."""
        n = len(self.names)
        c = self._masks.get(prefixes, NO_I.astype(bool))
        if len(c) < n:
            add = np.fromiter((nm.startswith(prefixes) for nm in self.names[len(c):n]), bool, n - len(c))
            c = self._masks[prefixes] = np.concatenate([c, add])
        return c[:n]

    def perceive(self, state):
        """state: {concept: value}. Returns the events (neurons whose value went up)."""
        got = [(self._neuron(k), v) for k, v in state.items()]       # new neurons first: the room may grow
        new = np.zeros_like(self.val)                  # what is not perceived now is not true now
        for i, v in got:
            if i is not None:
                new[i] = float(v)
        ev = np.nonzero(new > self.val + 1e-9)[0]
        before = self.val > 0
        self.val = new
        return ev, before

    # ---------------------------------------------------------------- chain synapses (sparse)
    def chain(self, e):
        """The chain synapses onto event e: (preceding concepts, strengths)."""
        return self.cols.get(int(e), (NO_I, NO_V))

    def _learn_chain(self, e, on, lr):
        """Event e happened with the concepts `on` active just before: every synapse onto e moves towards
        'was it there' (a running average); a synapse that fades below FORGET is let go. When what I know
        causes e was all there, e is explained, and whatever else happened to be around gains little from it
        (blocking, Kamin): a coincidence does not become a cause just because it keeps coming along."""
        known = self.pre(e)
        explained = len(known) > 0 and bool(np.isin(known, on).all())
        idx, w = self.chain(e)
        u = np.union1d(idx, on).astype(np.int32)
        x = np.zeros(len(u), np.float32)
        x[np.searchsorted(u, idx)] = w
        there = np.zeros(len(u), np.float32)
        there[np.searchsorted(u, on)] = 1.0
        rate = np.full(len(u), lr, np.float32)
        if explained:
            rate[(there > 0) & ~np.isin(u, known)] *= 0.2
        x += rate * (there - x)
        keep = x >= FORGET
        strong = bool((w >= 0.9).any()) or bool((x >= 0.9).any())
        self.cols[int(e)] = (u[keep], x[keep])
        if strong:
            self._edges = None

    def _set_chain(self, p, e, s):
        """A belief (told, read): the synapse p -> e is at least s."""
        idx, w = self.chain(e)
        k = int(np.searchsorted(idx, p))
        if k < len(idx) and idx[k] == p:
            w = w.copy()
            w[k] = max(w[k], s)
        else:
            idx, w = np.insert(idx, k, p).astype(np.int32), np.insert(w, k, s).astype(np.float32)
        self.cols[int(e)] = (idx, w)
        self.told_pre.setdefault(int(e), set()).add(int(p))
        self._edges = None

    def _specific(self, e, idx, w):
        """Which synapses onto e are real conditions: reliable (>= 0.9), and either specific to e - there
        before it clearly more often than there at all (the sky, being in the overworld, a full stomach are
        there before everything and explain nothing) - or what I was told (a recipe; only my own experience
        can overturn it)."""
        told = self.told_pre.get(int(e), ())
        b = self.base[idx]
        lived = (w - b >= 0.2) & (w >= 2.0 * b) & (self.nev[e] >= LIVED_N)   # what I found myself: seen often enough
        spec = lived | np.fromiter((int(p) in told for p in idx), bool, len(idx))
        return (w >= 0.9) & (idx != e) & spec

    def strong_links(self):
        """All reliable synapses p -> e (strength >= 0.9, p != e), gathered: (p, e, strength, told). Whether
        each is specific is judged when used (how often things are there at all changes as I live)."""
        if self._edges is None:
            P, E, S, T = [NO_I], [NO_I], [NO_V], [NO_I.astype(bool)]
            for e, (idx, w) in self.cols.items():
                ok = (w >= 0.9) & (idx != e)
                if ok.any():
                    told = self.told_pre.get(e, ())
                    P.append(idx[ok])
                    E.append(np.full(int(ok.sum()), e, np.int32))
                    S.append(w[ok])
                    T.append(np.fromiter((int(p) in told for p in idx[ok]), bool, int(ok.sum())))
            self._edges = (np.concatenate(P), np.concatenate(E), np.concatenate(S), np.concatenate(T))
        return self._edges

    def pre(self, e, min_n=3):
        """Learned preconditions of event e: concepts reliably and specifically active before it."""
        if self.nev[e] < min_n:
            return np.zeros(0, np.int64)
        idx, w = self.chain(e)
        return idx[self._specific(e, idx, w)].astype(np.int64)

    # ---------------------------------------------------------------- skills
    def gkeys(self, cells, g):
        return ((cells * 0x9E3779B1 + (int(g) + 1) * 0x85EBCA77) >> 7) & self.gmask

    def grow_skills(self, room_bytes):
        """The skill synapses are a hashed table: when more than half of it is in use, skills start to
        share synapses and blur. Then it doubles - if the memory given to this brain allows. Nothing
        learned is lost: every synapse is copied into both halves, and later learning tells them apart."""
        if self.gtouch is None:                          # which synapse rows are in use (since the last doubling)
            self.gtouch = (self.G != 0).any(1)
        if float(self.gtouch.mean()) < 0.5 or self.G.nbytes > room_bytes:
            return False
        self.G = np.concatenate([self.G, self.G])
        self.gmask = len(self.G) - 1
        self.gtouch = np.zeros(len(self.G), bool)        # copies are not use; what is learned from now on is
        return True

    def _q_update(self, cells, a, nxt, evs, g, lr):
        """One-step Q-learning of the skill 'make g happen' on one remembered moment."""
        k = self.gkeys(cells, g)
        q = self.G[k, a].sum()
        tgt = 1.0 if g in evs else self.g * self.G[self.gkeys(nxt, g)].sum(0).max()
        self.G[k, a] += lr * (tgt - q) / len(k)
        if self.gtouch is not None:
            self.gtouch[k] = True

    def _hindsight(self, e):
        """Replay the last moments backwards: this is how event e is made to happen. The credit goes mostly to
        what I did just before it and fades with each moment further back (an eligibility trace, lam); an action
        that did nothing (the body said so) gets none. Longer ways are joined up later, by replay."""
        lr = self.alpha
        for cells, a, nxt, evs, *ok in reversed(self.recent):
            if lr < 0.01 * self.alpha:
                break
            if not (ok and ok[0] is False):
                self._q_update(cells, a, nxt, evs, e, lr)
            lr *= self.lam

    def _replay(self, n=16):
        """Hippocampal replay while living: random old moments, for the current goal and for random
        known goals - skills keep improving, actions that bring no progress fade."""
        if len(self.memory) < 50:
            return
        known = np.nonzero(self.nev[:len(self.names)] > 0)[0]
        if len(known) == 0:
            return
        for _ in range(n):
            cells, a, nxt, evs, *ok = self.memory[int(self.rng.integers(len(self.memory)))]
            if ok and ok[0] is False:                    # it did nothing: nothing to learn about doing it
                continue
            g = self.goal if (self.goal is not None and self.rng.random() < 0.5) else int(self.rng.choice(known))
            self._q_update(cells, a, nxt, evs, g, self.alpha * 0.5)

    # ---------------------------------------------------------------- action -> outcome (goal-directed)
    def _ao_learn(self, ev, before, a):
        on = np.nonzero(before[:len(self.names)])[0].astype(np.int32)
        for e in ev:
            rec = self.ao.get((int(e), a))
            if rec is None:
                rec = self.ao[(int(e), a)] = [0.0, (NO_I, NO_V), 0.0]
                self._ao_a.setdefault(a, []).append((int(e), rec))
                self._ao_e.setdefault(int(e), []).append((a, rec))
            rec[0] += 1
            idx, cnt = rec[1]                            # how often each concept was there when it worked
            u = np.union1d(idx, on).astype(np.int32)
            x = np.zeros(len(u), np.float32)
            x[np.searchsorted(u, idx)] = cnt
            x[np.searchsorted(u, on)] += 1
            rec[1] = (u, x)

    def _ao_need(self, rec):
        idx, cnt = rec[1]
        return idx[cnt / rec[0] >= 0.9].astype(np.int64)

    def _ao_index(self):
        self._ao_a, self._ao_e = {}, {}
        for (e, a), rec in self.ao.items():
            if not isinstance(rec[1], tuple):            # a brain from before: counts over every concept
                nz = np.nonzero(rec[1])[0]
                rec[1] = (nz.astype(np.int32), rec[1][nz].astype(np.float32))
            self._ao_a.setdefault(a, []).append((e, rec))
            self._ao_e.setdefault(e, []).append((a, rec))

    def _ao_attempt(self, a, active):
        for e, rec in self._ao_a.get(a, ()):
            if rec[0] >= 2 and active[self._ao_need(rec)].all():
                rec[2] += 1

    def ao_plan(self, g, active):
        """The action that made g happen before in the context I am in now (or None)."""
        base = self.nev[g] / max(1.0, self.steps)       # how often it happens anyway, whatever I do
        best, bp = None, max(0.05, 3 * base) if getattr(self, "contingency", False) else 0.25
        for a, rec in self._ao_e.get(int(g), ()):
            if rec[0] < 2:
                continue
            if not active[self._ao_need(rec)].all():
                continue
            p = rec[0] / (rec[2] + 1.0)
            if p > bp:
                best, bp = a, p
        return best

    def ao_lift(self, g):
        """The action that itself makes g happen: after it, g comes far more often than g comes at all
        (counted over all my life, whatever the context) - 'crafting gives things', 'taking a weapon puts it
        in my hand'; not what merely happened to be done around it."""
        base = self.nev[g] / max(1.0, self.steps)
        best, bl = None, 3.0
        for a, rec in self._ao_e.get(int(g), ()):
            if rec[0] < 3 or rec[0] < 0.2 * self.nev[g]:     # seen to work a few times, and a main way to it
                continue
            if (self.a_ok[a] + 1) / (self.a_n[a] + 2) < 0.3:   # an action that almost never does anything
                continue                                     # did not cause it (it came from elsewhere)
            lift = rec[0] / (self.a_count[a] + 1.0) / (base + 1e-6)
            if lift > bl:
                best, bl = a, lift
        return best

    def usefulness(self):
        """What each action brings, on the whole: the worth of what came of it, per time I did it. When I do not
        know how to do a step, the useful actions are tried first - not fidgeting with the hands."""
        if self._use is None or self.steps - self._use_t > 200:
            u = np.zeros(self.nA, np.float32)
            n = len(self.names)
            for (e, a), rec in self.ao.items():
                if e < n:
                    u[a] += rec[0] * max(float(self.R[e]), 0.0)
            self._use, self._use_t = u / (self.a_count + 1.0), self.steps
        return self._use

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
                if i is not None and i != e:
                    self._set_chain(i, e, 0.95)
            self.tell_helps([(target, pres)])                # and, if not needed after all, it still helps
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

    # ---------------------------------------------------------------- what makes things go better
    def tell_helps(self, claims, n=2.0, new=True):
        """What I read helps (a sword to fight): as if I had tried it n times with success - a prior that my own
        tries with and without it will confirm or overturn. new=False: only about things I already know of."""
        for target, pres in claims:
            e = self._neuron(target) if new else self.idx.get(target)
            if e is None:
                continue
            for p in pres:
                i = self._neuron(p) if new else self.idx.get(p)
                if i is not None and i != e and (not self.helper_kinds or p.startswith(self.helper_kinds)):
                    self.helps_prior.setdefault(e, {})[i] = (n, n)

    def mark_told(self, claims):
        """These conditions I have read (a brain from before did not keep which ones were read)."""
        for target, pres in claims:
            e = self.idx.get(target)
            for p in pres:
                if e is not None and p in self.idx:
                    self.told_pre.setdefault(e, set()).add(self.idx[p])
        self._edges = None

    def _helps_learn(self, g, ok):
        """A try at goal g is over: count it with each thing I had when I set out."""
        on, self._goal_on = self._goal_on, None
        if on is None:
            return
        h = self.helps.setdefault(int(g), [0.0, 0.0, {}])
        h[0] += 1
        h[1] += float(ok)
        for p in on:
            if not self.helper_kinds or self.names[p].startswith(self.helper_kinds):
                r = h[2].setdefault(int(p), [0.0, 0.0])
                r[0] += 1
                r[1] += float(ok)
        if h[0] > 100:                                  # old experience fades
            h[0], h[1] = h[0] * 0.98, h[1] * 0.98
            for r in h[2].values():
                r[0], r[1] = r[0] * 0.98, r[1] * 0.98

    def helpers(self, g, active):
        """Things that make g go better without being needed for it: with them I (or the book) managed it more
        often than without. -> [(concept, success with it, success without it)], the most helpful first."""
        n, s, per = self.helps.get(int(g), (0.0, 0.0, {}))
        prior = self.helps_prior.get(int(g), {})
        need = set(self.pre(g).tolist())
        out = []
        for p in set(per) | set(prior):
            if p >= len(active) or active[p] or p in need:
                continue
            n_p, s_p = per.get(p, (0.0, 0.0))
            pn, ps = prior.get(p, (0.0, 0.0))
            if not pn and (n_p < LIVED_N or n - n_p < 3):  # my own 'it goes better with it' needs enough tries
                continue                                    # with it and without it (not two lucky times)
            with_it = (s_p + ps + 1) / (n_p + pn + 2)
            without = (s - s_p + 1) / (max(n - n_p, 0.0) + 2)
            if n_p + pn >= 2 and with_it - without >= 0.2:
                out.append((p, with_it, without))
        return sorted(out, key=lambda x: -x[1] / x[2])[:3]

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
        if getattr(self, "secondary", False):
            val = self.instrumental(self.frontier(np.maximum(val, 0)))
        d = np.maximum(val, 0) + 0.15 / np.sqrt(1 + self.tries[:n])
        d[~seen | active[:n]] = -1
        means = getattr(self, "means_only", ())       # sensations are means, not things to want for themselves
        if means:
            d[self._mask(means)] = -1
        return d

    def frontier(self, v):
        """Curiosity about the unknown that is within reach: 'I could make something I have never had'
        is worth what discoveries have been worth to me so far."""
        nov = max(0.0, getattr(self, "first_v", 0.0))
        if nov <= 0:
            return v
        v = v.copy()
        for i in np.nonzero(self._mask(("can_craft:",))[:len(v)])[0]:
            h = self.idx.get("have:" + self.names[i][10:])
            if h is None or self.nev[h] == 0:
                v[i] = max(v[i], nov)
        return v

    def instrumental(self, v, g=0.7):
        """Secondary (conditioned) value: a thing is also worth what it leads to - money for what it buys,
        wood for what it becomes. Value flows backwards through the learned chains, fading at each link,
        through every link there is: it stops only when nothing changes any more."""
        n = len(v)
        p, e, s, told = self.strong_links()                              # p is a precondition of e,
        b = self.base[p]                                                 # specific to e (or read): there before it
        ok = (p < n) & (e < n) & (self.nev[e] >= 3) & (((s - b >= 0.2) & (s >= 2.0 * b) & (self.nev[e] >= LIVED_N)) | told)
        p, e = p[ok], e[ok]
        for _ in range(n + 1):                  # a simple chain is never longer than the concepts there are
            w = v.copy()
            np.maximum.at(w, p, g * v[e])
            if np.allclose(w, v):
                break
            v = w
        return v

    def reason(self, active, target):
        """Spread desire backwards through chain synapses, to the end of every chain, however long;
        return (subgoal, chain) or (None, chain). Each concept is visited once, so it always ends."""
        act = {target: 1.0}
        frontier, chain, ready = [target], [], []
        while frontier:
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
        if not ready:
            return None, chain
        return max(ready, key=lambda e: act[e] * (0.3 + self.comp[e])), chain

    @staticmethod
    def path(chain, t, sub):
        """The line of reasoning from the wish down to what I do now: [t, ..., sub]."""
        up = {p: e for e, p in chain}
        line = [sub]
        while line[-1] != t and line[-1] in up:
            line.append(up[line[-1]])
        return line[::-1]

    def deliberate(self, active):
        """Think: for the things I want most, what can I do now that leads there, and how likely
        am I to manage it? Choose the best (target, next step). Wishes are weighed from the strongest
        down for as long as a moment of thought lasts (self.think); each is followed to its end."""
        d = self.desire(active)
        if len(d) == 0 or d.max() <= 0:
            return None
        comp = self.comp
        n = len(self.names)
        tc = self.tries_c[:n, self.ctx]
        comp = np.where(tc >= 2, (self.succ_c[:n, self.ctx] + 1) / (tc + 2), comp[:n])
        danger = self.ctx in self.urgent_ctx
        if not danger and self.intent is None and self.intent_saved is not None:
            self.intent, self.intent_saved = self.intent_saved, None        # the danger is over: back to it
            self.intent_t, self.intent_fails = self.steps, 0
            self._note("вернулся к делу", self.intent)
        intent = self.intent if self.intent is not None and self.intent < n and d[self.intent] > 0 else None
        # a decided thing weighs more than a new wish; less after each failure (frustration); not at all in danger
        stick = 1.0 if danger else self.commit * 0.7 ** self.intent_fails
        order = np.argsort(-d)
        if intent is not None:                         # what I have set out to do is thought about first
            order = np.concatenate([[intent], order[order != intent]])
        best, bs, intent_way = None, 0.0, False
        t0 = time.perf_counter()
        for k, t in enumerate(order):
            if d[t] <= 0 or (k >= 8 and time.perf_counter() - t0 > self.think):
                break
            sub, chain = self.reason(active, t)
            if sub is None:
                continue
            intent_way = intent_way or t == intent
            plans = [(sub, chain, len(self.path(chain, t, sub)), 1.0, None)]   # straight at it, as I am now
            for h, p_with, p_without in self.helpers(t, active):    # or first get what makes it go better
                hs, hc = self.reason(active, h)
                if hs is not None:
                    plans.append((hs, hc + [(t, h)], len(self.path(hc, h, hs)) + 1, min(p_with / p_without, 4.0),
                                  (t, h, p_with, p_without)))
            noise = 0.8 + 0.4 * self.rng.random()
            for s_, c_, depth, gain, why in plans:
                score = d[t] * comp[s_] * 0.9 ** depth * gain * noise * (stick if t == intent else 1.0)
                if score > bs:
                    best, bs = (t, s_, c_, why), score
        if best is None or bs < getattr(self, "min_desire", 0.0):
            return None                                # nothing worth the effort: habits and curiosity act
        if best[0] != self.intent:                     # a new intention - and why the old one was let go
            old = self.intent
            if old is None:
                why = "решил"
            elif danger:
                why, self.intent_saved = "отвлёкся: опасность", old
            elif not intent_way:
                why = "не вижу пути к «%s»" % self.names[old]
            elif self.intent_fails >= 2:
                why = "не выходит «%s» (%d раз)" % (self.names[old], self.intent_fails)
            else:
                why = "важнее, чем «%s»" % self.names[old]
            self.intent, self.intent_t, self.intent_fails = best[0], self.steps, 0
            self._note(why, best[0])
        self.target = best[0]
        self.thought = self.explain(best[0], best[2], best[1], best[3])
        return best[1]

    def _soft(self, q):
        """A try, but among the sensible: the better an action seems, the likelier it is tried (not one of 60 at
        random - fishing, trading and hotbar keys when I want a table)."""
        z = (q - q.max()) / (0.25 * np.ptp(q) + 1e-3)
        p = np.exp(z)
        return int(self.rng.choice(len(q), p=p / p.sum()))

    def _note(self, why, t):
        self.intent_log.append((self.steps, f"{why} → {self.names[t]}" if t is not None else why))

    def explain(self, t, chain, sub, helper=None):
        name = self.names
        line = self.path(chain, t, sub)
        parts = [f"хочу {name[t]}"]
        for e, p in zip(line, line[1:]):
            if helper is not None and (e, p) == helper[:2]:
                parts.append(f"с «{name[p]}» выходит чаще ({helper[2]:.0%} против {helper[3]:.0%})")
            else:
                parts.append(f"для «{name[e]}» нужно «{name[p]}»")
        parts.append(f"сейчас делаю: {name[sub]}")
        return "; ".join(parts)

    def why(self, e):
        """What I have learned about how to get e (the whole chain, read out of the synapses)."""
        out, seen, stack = [], set(), [e]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            ps = self.pre(x)
            if len(ps):
                out.append(f"{self.names[x]} ← " + " + ".join(self.names[p] for p in ps))
            stack += list(ps)
        return out

    def patience(self, g):
        """How long I keep at a goal: what I am used to from the times I managed it (things that took
        long before are given long again), and never less than a first try gets (budget)."""
        return max(self.budget, 3.0 * float(self.took[g]))

    # ---------------------------------------------------------------- one moment of life
    def step(self, obs, state, r, done=False, explore=0.1, value=None, ctx=0):
        self.ctx = ctx
        ev, before = self.perceive(state)
        n = len(self.names)
        active = self.val > 0
        self.base[:n] += 0.005 * (active[:n] - self.base[:n])
        if self.newborn:                                 # waking up is not an event
            ev, self.newborn = ev[:0], False
        on = np.nonzero(before[:n])[0].astype(np.int32)  # what was true just before
        for e in ev:                                     # something happened
            if not before[e]:                            # it became true: what made it possible?
                self.nev[e] += 1
                lr = max(1.0 / self.nev[e], 0.05)
                self._learn_chain(e, on, lr)
                v = r if value is None else value         # how good it was for me, all things considered
                if self.nev[e] == 1:                         # a first time ever: how good are discoveries?
                    self.first_n = getattr(self, "first_n", 0) + 1
                    self.first_v = getattr(self, "first_v", 0.0) + (v - getattr(self, "first_v", 0.0)) / self.first_n
                    v -= getattr(self, "novelty", 0.0)       # the joy of discovering goes to discovering (curiosity),
                                                             # not to the thing: a new button is not a dear button
                self.R[e] += lr * (v - self.R[e])
                self.nc[e, ctx] += 1
                self.Rc[e, ctx] += max(1.0 / self.nc[e, ctx], 0.05) * (v - self.Rc[e, ctx])
        cells = self.flat.cells(obs)
        ep, recalled = self.episodic, None
        if ep is not None:                               # episodic memory: keep the moment that passed,
            key = ep.key(np.nonzero(active[:n])[0], cells)          # and recall the ones most like now
            if self._ep_prev is not None:
                ep.add(self._ep_prev[0], self._ep_prev[1], r, [int(e) for e in ev if not before[e]], done)
            recalled = self.recalled = ep.recall(key)
        if self._last is not None and getattr(self, "last_ok", None) is not None:   # the body said if it worked
            self.a_n[self._last[1]] += 1
            self.a_ok[self._last[1]] += float(self.last_ok)
        given = getattr(self, "external", False)         # it came from someone (a gift): not from what I did
        if self._last is not None and len(ev) and getattr(self, "last_ok", None) is not False and not given:
            self._ao_learn(ev, before, self._last[1])    # (an action that did nothing did not cause what came)
        if self._last is not None:                       # remember the moment that just passed
            tr = (self._last[0], self._last[1], cells, frozenset(int(e) for e in ev), getattr(self, "last_ok", None))
            self.recent.append(tr)
            self.memory.append(tr)
        for e in (ev if not given else ()):
            self._hindsight(e)                           # every time: how did I do that? (not when it was given)
        # the current plan: success, failure or keep going
        reached = self.goal is not None and self.goal in ev
        late = self.goal is not None and self.steps - self.goal_t > self.patience(self.goal)
        self.last_outcome = False if reached else (True if late else None)
        if reached:
            self.succ[self.goal] += 1
            self.succ_c[self.goal, self.goal_ctx] += 1
            dt, k = float(self.steps - self.goal_t), self.goal       # how long it took me this time
            self.took[k] = dt if self.took[k] == 0 else self.took[k] + 0.3 * (dt - self.took[k])
        elif self.goal is not None and (late or done):
            self.explore_left = self.explore_steps if self.intent is None else max(5, self.explore_steps // 4)   # look around a bit
            if late and self.intent is not None:
                self.intent_fails += 1                   # a step towards what I decided failed
        if self.intent is not None and self.intent in ev and not before[self.intent]:
            self._note("добился", self.intent)           # done: the intention is fulfilled
            self.intent = None
        self._replay()
        if reached or done or late:
            if self.goal is not None:
                self._helps_learn(self.goal, reached)    # with what I had, did it work?
            self.goal = None
        if done:
            self.explore_left = 0
        if self.goal is None and self.explore_left <= 0 and not done and self.planning:
            self.goal = self.deliberate(active)
            self.goal_t = self.steps
            if self.goal is not None:
                self._goal_on = np.nonzero(active[:n])[0]  # what I set out with
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
        urge = getattr(self, "tendency", None)           # innate action tendencies of emotions (set by the body's feelings)
        urge = urge if urge is not None and urge.any() else None
        if self.goal is not None:
            q = self.G[self.gkeys(cells, self.goal)].sum(0) + self.habit * (fq - fq.max())
            if recalled is not None:                     # in moments like this, what was followed by my goal
                q = q + recalled.toward(self.goal, self.nA)
            if urge is not None:                         # an emotion's urge, as strong as the values at stake
                q = q + urge * (np.ptp(q) + 0.1)
            if self.flat.emo:
                q = q + self.flat.fear_veto(cells)                         # fear still vetoes (contingency)
            if self._last is not None and getattr(self, "last_ok", None) and self.goal == self._last_goal and len(ev):
                q = q.copy()                             # it brought something a moment ago, for the same step: go on
                q[self._last[1]] += 0.25 * (np.ptp(q) + 0.1) * 0.7 ** self._same_n   # (less and less, the longer)
            u = self.usefulness()                        # not knowing how: the useful actions before fidgeting
            q = q + 0.5 * (np.ptp(q) + 0.05) * u / (u.max() + 1e-9)
            eps = 0.03 + 0.2 * (1 - self.comp[self.goal])
            tried = self.rng.random() < eps
            a = self._soft(q) if tried else int(np.argmax(q + self.rng.random(self.nA) * 1e-6))
            self.chose = "try" if tried else "plan"      # a random try within a plan is not a step of the plan
            direct = self.ao_plan(self.goal, active)     # I know what does it, and I can do it here
            if direct is None:
                direct = self.ao_lift(self.goal)         # ... or what does it anywhere
            if direct is not None and self.rng.random() > 0.1 and (urge is None or self.rng.random() > urge.max()):
                a, self.chose = int(direct), "plan"      # (a strong emotion can break into the plan)
        else:
            self.chose = "habit"
            self.explore_left -= 1
            worth = recalled.worth(self.nA) if recalled is not None else 0.0   # what came of each action before
            if urge is not None:
                worth = worth + urge * (np.ptp(fq) + 0.1)
            u = self.usefulness()
            v = fq + worth + 0.3 * (np.ptp(fq) + 0.05) * u / (u.max() + 1e-9)   # habits, memories, urges, usefulness
            a = self._soft(v) if self.rng.random() < explore else int(np.argmax(v + self.rng.random(self.nA) * 1e-6))
            k = getattr(self, "try_new", 0.0)
            if k > 0:                                    # directed curiosity: what have I not tried HERE?
                sit = hash(tuple(np.nonzero(active[:n])[0]))
                tried = self.tried.setdefault(sit, np.zeros(self.nA, np.float32))
                qb = (fq + self.flat.fear_veto(fcells) if self.flat.emo else fq.copy()) + worth
                a = int(np.argmax(qb + k / np.sqrt(1.0 + tried) + self.rng.random(self.nA) * 1e-6))
                if self.rng.random() < explore:
                    a = int(self.rng.integers(self.nA))
                tried[a] += 1
                if len(self.tried) > 200000:
                    self.tried.clear()
        if self._fprev is not None:                      # habits learn from reward all the time
            c0, a0 = self._fprev
            self.flat.learn(c0, a0, r, obs, fcells, fq, a, done)
            k = getattr(self, "habit_replay", 0)
            if k:                                        # ... and from replayed memories
                self.flat.remember(c0, a0, r, fcells, done)
                self.flat.replay(k)
        self._ao_attempt(a, active)
        self.a_count[a] += 1                             # how often I have done each action at all
        self._same_n = self._same_n + 1 if self._last is not None and a == self._last[1] else 0
        self._fprev = None if done else (fcells, a)
        self._last = None if done else (cells, a)
        self._last_goal = self.goal
        if ep is not None:
            self._ep_prev = None if done else (key, a)
        if done:
            self.recent.clear()
            self.val[:] = 0
            self.newborn = True
        self.steps += 1
        return a

    # ---------------------------------------------------------------- memory
    def save(self, path):
        extra = {"FQ": self.flat.FQ, "FB": self.flat.FB} if self.flat.FQ is not None else {}
        es = sorted(self.cols)                                                   # chain synapses, column by column
        cols = [self.cols[e] for e in es]
        tmp = os.path.splitext(path)[0] + ".saving.npz"                      # written aside, then swapped in:
        np.savez(tmp, G=self.G, chain_e=np.array(es, np.int32),                 # a crash mid-save cannot break memory
                 chain_len=np.array([len(i) for i, _ in cols], np.int32),
                 chain_p=np.concatenate([NO_I] + [i for i, _ in cols]), chain_w=np.concatenate([NO_V] + [w for _, w in cols]),
                 **{k: getattr(self, k) for k in PER_CONCEPT if k != "val"},
                 names=np.array(self.names, dtype=object), W=self.flat.W, F=self.flat.F,
                 steps=self.steps, first=np.array([getattr(self, "first_n", 0), getattr(self, "first_v", 0.0)]),
                 **({"gtouch": np.packbits(self.gtouch)} if self.gtouch is not None else {}), **extra)
        swap_in(tmp, path)
        for suffix, obj in (("_ao.pkl", self.ao),                                   # what my actions did (contingencies)
                            ("_helps.pkl", {"helps": self.helps, "prior": self.helps_prior, "told": self.told_pre,
                                           "intent": (self.intent, self.intent_saved), "a_count": self.a_count,
                                           "a_ok": self.a_ok, "a_n": self.a_n})):
            f_path = os.path.splitext(path)[0] + suffix
            with open(f_path + ".saving", "wb") as f:
                pickle.dump(obj, f)
            swap_in(f_path + ".saving", f_path)
        if self.episodic is not None:
            self.episodic.save()

    def load(self, path):
        if not os.path.exists(path):
            return False
        z = np.load(path, allow_pickle=True)
        g = z["G"]
        na = min(g.shape[1], self.nA)
        if len(g) != len(self.G):                                            # the skills had grown
            self.G = np.zeros((len(g), self.nA), np.float32)
            self.gmask = len(g) - 1
        self.G[:, :na] = g[:, :na]
        del g
        self.gtouch = np.unpackbits(z["gtouch"])[:len(self.G)].astype(bool) if "gtouch" in z.files else None
        self.names = list(z["names"])
        self.idx = {k: i for i, k in enumerate(self.names)}
        self._masks, self._edges = {}, None
        while len(self.val) < len(self.names):                               # room for everything I knew
            self._grow()
        for k in PER_CONCEPT:
            if k in z.files:
                x, y = getattr(self, k), z[k]
                m = min(len(x), len(y))
                if x.ndim == 2 and x.shape[1] != y.shape[1]:                  # older brains knew fewer contexts
                    x[:m, :y.shape[1]] = y[:m]
                else:
                    x[:m] = y[:m]
        n = len(self.names)
        self.cols = {}
        if "chain_e" in z.files:
            p, w, at = z["chain_p"], z["chain_w"], 0
            for e, ln in zip(z["chain_e"], z["chain_len"]):
                self.cols[int(e)] = (p[at:at + ln].astype(np.int32), w[at:at + ln].astype(np.float32))
                at += ln
        elif "C" in z.files:                                                 # a brain from before: a dense matrix
            C = z["C"][:n, :n]
            for e in range(n):
                nz = np.nonzero(C[:, e] >= FORGET)[0]
                if len(nz):
                    self.cols[e] = (nz.astype(np.int32), C[nz, e].astype(np.float32))
        self.flat.W[:, :na], self.flat.F[:] = z["W"][:, :na], z["F"]
        if self.flat.FQ is not None and "FQ" in z.files:
            self.flat.FQ[:, :na] = z["FQ"][:, :na]
        if self.flat.FB is not None and "FB" in z.files:
            if z["FB"].shape == self.flat.FB.shape:
                self.flat.FB[:] = z["FB"]
        self.steps = int(z["steps"])
        if "first" in z.files:
            self.first_n, self.first_v = int(z["first"][0]), float(z["first"][1])
        z.close()                                  # (an open file cannot be replaced by the next save on Windows)
        ao = os.path.splitext(path)[0] + "_ao.pkl"
        if os.path.exists(ao):
            with open(ao, "rb") as f:
                self.ao = pickle.load(f)
        self._ao_index()
        hp = os.path.splitext(path)[0] + "_helps.pkl"
        h = {}
        if os.path.exists(hp):
            with open(hp, "rb") as f:
                h = pickle.load(f)
            self.helps, self.helps_prior = h.get("helps", {}), h.get("prior", {})
            self.intent, self.intent_saved = h.get("intent", (None, None))          # what I had decided to do
            self.intent_t = self.steps
            for k in ("a_count", "a_ok", "a_n"):
                if k in h:
                    getattr(self, k)[:min(len(h[k]), self.nA)] = h[k][:self.nA]
        if not self.a_count.any():                      # a brain from before: the tries its records kept
            for (e, a), rec in self.ao.items():
                if a < self.nA:
                    self.a_count[a] = max(self.a_count[a], rec[2])
        if "told" in h:
            self.told_pre = h["told"]
        else:                                  # a brain from before: what was told and not lived since is still 0.95
            self.told_pre = {}
            for e, (idx, w) in self.cols.items():                          # (a thing to have, hold or wear;
                t = [int(p) for p in idx[np.abs(w - 0.95) < 1e-4]                # 0.95 by chance happens too)
                     if not self.helper_kinds or self.names[p].startswith(self.helper_kinds)]
                if t:
                    self.told_pre[e] = set(t)
        self._edges = None
        return True
