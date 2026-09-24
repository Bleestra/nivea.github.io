"""Standard deep-RL baseline: Double DQN (MLP 256-256, replay buffer, target network, Adam)."""
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


def encode(obs):
    v, inv = obs[0], obs[1]
    x = np.zeros(25 * 6 + 8, np.float32)
    x[np.arange(25) * 6 + v] = 1
    x[150 + inv] = 1
    return x


class DQN:
    def __init__(self, n_actions, seed=0, gamma=0.97, lr=1e-3, buf=50_000, batch=64, sync=500, every=1):
        torch.manual_seed(seed)
        self.rng = np.random.default_rng(seed)
        mk = lambda: nn.Sequential(nn.Linear(158, 256), nn.ReLU(), nn.Linear(256, 256), nn.ReLU(),
                                   nn.Linear(256, n_actions))
        self.net, self.tgt = mk(), mk()
        self.tgt.load_state_dict(self.net.state_dict())
        self.opt = torch.optim.Adam(self.net.parameters(), lr=lr)
        self.nA, self.g, self.B, self.sync = n_actions, gamma, batch, sync
        self.S = np.zeros((buf, 158), np.float32)
        self.S2 = np.zeros((buf, 158), np.float32)
        self.A = np.zeros(buf, np.int64)
        self.R = np.zeros(buf, np.float32)
        self.D = np.zeros(buf, np.float32)
        self.n, self.i, self.cap, self.steps, self.every = 0, 0, buf, 0, every

    def act(self, obs, eps):
        x = encode(obs)
        if self.rng.random() < eps:
            return int(self.rng.integers(self.nA)), x
        with torch.no_grad():
            return int(self.net(torch.from_numpy(x)[None]).argmax()), x

    def learn(self, x, a, r, obs2, done):
        k = self.i
        self.S[k], self.A[k], self.R[k], self.S2[k], self.D[k] = x, a, r, encode(obs2), float(done)
        self.i = (self.i + 1) % self.cap
        self.n = min(self.n + 1, self.cap)
        self.steps += 1
        if self.n < 1000 or self.steps % self.every:
            return
        idx = self.rng.integers(self.n, size=self.B)
        s, s2 = torch.from_numpy(self.S[idx]), torch.from_numpy(self.S2[idx])
        a_, r_, d_ = torch.from_numpy(self.A[idx]), torch.from_numpy(self.R[idx]), torch.from_numpy(self.D[idx])
        with torch.no_grad():
            best = self.net(s2).argmax(1, keepdim=True)
            y = r_ + self.g * (1 - d_) * self.tgt(s2).gather(1, best).squeeze(1)
        q = self.net(s).gather(1, a_[:, None]).squeeze(1)
        loss = F.smooth_l1_loss(q, y)
        self.opt.zero_grad()
        loss.backward()
        self.opt.step()
        if self.steps % self.sync == 0:
            self.tgt.load_state_dict(self.net.state_dict())
