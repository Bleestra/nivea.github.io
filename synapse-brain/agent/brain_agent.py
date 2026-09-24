"""
SynapseBrain-Agent: acting and learning in real time with the same brain services.

  sensory cortex : granule populations turn an observation into ~45 active cells out of 2^20
                   (single-cell detectors, local patches, the row ahead, random triplets,
                   the whole view) - sparse, hashed, no training needed.
  striatum       : every active cell has one synapse per action; Q(s,a) = sum over active cells.
  dopamine       : reward prediction error  delta = r + gamma*Q(s',a') - Q(s,a)
                   (temporal-difference learning, the classic model of dopamine neurons).
  eligibility    : synapses that were active in the last steps keep a fading trace, so a
                   reward also reaches the actions that led to it (three-factor rule).
  cerebellum     : forward model - predicts what will be in front after an action; its surprise
                   is an intrinsic reward (curiosity), which drives exploration.
Every update touches only active synapses: a step costs microseconds, learning is online.
"""
import numpy as np

MASK = (1 << 20) - 1


def _h(*xs):
    h = 1469598103934665603
    for x in xs:
        h = ((h ^ (int(x) + 0x9E37)) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return (h ^ (h >> 29)) & MASK


class BrainAgent:
    def __init__(self, n_actions, seed=0, gamma=0.97, lam=0.7, alpha=0.25, curiosity=0.0,
                 trace_len=30, init=0.02):
        self.nA, self.g, self.lam = n_actions, gamma, lam
        self.rng = np.random.default_rng(seed)
        self.W = np.full((MASK + 1, n_actions), init, np.float32)   # striatal synapses
        self.F = np.zeros((MASK + 1, 8), np.float32)                 # cerebellar forward model
        self.alpha, self.cur, self.K = alpha, curiosity, trace_len
        trip = np.random.default_rng(123).choice(25, (12, 3))
        self.trip = trip
        self.hist = []  # recent (cells, action) for eligibility traces
        self.prev = None
        self.steps = 0

    def cells(self, obs):
        v, inv = obs
        c = [_h(1, i, v[i]) for i in range(25)]
        c.append(_h(2, v[6], v[7], v[8]))                      # just ahead
        c.append(_h(3, *v[0:15]))                               # 3 rows ahead
        c.append(_h(4, v[7], v[12], v[17], v[22]))              # straight line ahead
        c.append(_h(5, *v))                                     # whole view
        c += [_h(6, k, v[a], v[b], v[d]) for k, (a, b, d) in enumerate(self.trip)]
        c.append(_h(7, inv, v[7]))
        c.append(_h(8))                                         # bias cell
        return np.array(c, np.int64)

    def q(self, cells):
        return self.W[cells].sum(0)

    def act(self, obs, eps):
        cells = self.cells(obs)
        qv = self.q(cells)
        if self.rng.random() < eps:
            a = int(self.rng.integers(self.nA))
        else:
            a = int(np.argmax(qv + self.rng.random(self.nA) * 1e-6))
        return a, cells, qv

    def learn(self, cells, a, r, next_obs, next_cells, next_q, next_a, done):
        # cerebellum: how surprising is what is now in front of us, given what we did?
        front = int(next_obs[0][7])
        key = (cells[:26] * 7 + a) & MASK
        pred = self.F[key].sum(0)
        p = np.exp(pred - pred.max())
        p /= p.sum()
        surprise = -np.log(p[front] + 1e-6)
        target = np.zeros(8, np.float32)
        target[front] = 1
        self.F[key] += 0.1 * (target - p) / 26
        r_total = r + self.cur * surprise / (1 + self.steps / 20000)
        # dopamine: reward prediction error, delivered along eligibility traces
        q_sa = self.W[cells, a].sum()
        target_q = r_total + (0.0 if done else self.g * next_q[next_a])
        delta = target_q - q_sa
        self.hist.append((cells, a))
        if len(self.hist) > self.K:
            self.hist.pop(0)
        lr = self.alpha / len(cells)
        decay = 1.0
        for cs, aa in reversed(self.hist):
            self.W[cs, aa] += lr * delta * decay
            decay *= self.g * self.lam
            if decay < 0.01:
                break
        if done:
            self.hist.clear()
        self.steps += 1
        return delta
