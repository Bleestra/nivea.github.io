"""
Real-time learning in MiniCraft: SynapseBrain-Agent vs Double DQN, same world seeds,
same exploration schedule (epsilon 0.3 -> 0.02 over the first 20k steps), 60k steps.

    python3 rl_bench.py [steps] [seeds]
"""
import os
import sys
import time

import numpy as np
import torch

from brain_agent import BrainAgent
from dqn_baseline import DQN
from minicraft import MiniCraft

torch.set_num_threads(os.cpu_count())


def eps_at(t):
    return max(0.02, 0.3 - 0.28 * t / 20000)


def run(kind, steps, seed):
    env = MiniCraft(seed=seed)
    obs = env.reset()
    rng = np.random.default_rng(seed)
    if kind == "brain":
        ag = BrainAgent(5, seed=seed)
    elif kind.startswith("dqn"):
        kw = dict(x.split("=") for x in kind.split(":")[1:])
        ag = DQN(5, seed=seed, **{k: float(v) if "." in v or "e" in v else int(v) for k, v in kw.items()})
    ep_r, ep_rewards, t0 = 0.0, [], time.perf_counter()
    if kind == "brain":
        a, cells, qv = ag.act(obs, eps_at(0))
    for t in range(steps):
        if kind == "brain":
            obs2, r, done = env.step(a)
            a2, cells2, qv2 = ag.act(obs2, eps_at(t))
            ag.learn(cells, a, r, obs2, cells2, qv2, a2, done)
            a, cells, qv = a2, cells2, qv2
        elif kind == "random":
            obs2, r, done = env.step(int(rng.integers(5)))
        else:
            a, x = ag.act(obs, eps_at(t))
            obs2, r, done = env.step(a)
            ag.learn(x, a, r, obs2, done)
        ep_r += r
        obs = obs2
        if done:
            ep_rewards.append(ep_r)
            ep_r = 0.0
            obs = env.reset()
            if kind == "brain":
                a, cells, qv = ag.act(obs, eps_at(t))
    return np.array(ep_rewards), (time.perf_counter() - t0) / steps


def main():
    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 60_000
    seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    res = {}
    kinds = sys.argv[3].split(",") if len(sys.argv) > 3 else ["random", "brain", "dqn"]
    for kind in kinds:
        curves, dts = [], []
        for s in range(seeds):
            c, dt = run(kind, steps, s)
            curves.append(c)
            dts.append(dt)
            print(f"{kind} seed {s}: last-20 episodes {c[-20:].mean():6.2f}, {dt * 1e6:7.0f} us/step", flush=True)
        n = min(len(c) for c in curves)
        res[kind] = (np.mean([c[:n] for c in curves], 0), np.mean(dts))
    print("\nmean episode reward (300 steps each), by training stage")
    n = min(len(v[0]) for v in res.values())
    marks = [n // 10, n // 4, n // 2, n - 1]
    print(f"{'':8}" + "".join(f"{'ep ' + str(m + 1):>10}" for m in marks) + f"{'us/step':>10}")
    for kind, (c, dt) in res.items():
        sm = [c[max(0, m - 9) : m + 1].mean() for m in marks]  # mean of the 10 episodes up to m
        print(f"{kind:8}" + "".join(f"{v:10.2f}" for v in sm) + f"{dt * 1e6:10.0f}")


if __name__ == "__main__":
    main()
