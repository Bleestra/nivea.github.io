"""
Childhood: grow the brain in MiniCraft (same senses and actions as the Minecraft bot) and save
its synapses, so that in Minecraft it starts with the basic skills (walk to trees, dig them,
fear lava) instead of from zero.

    python3 pretrain.py [steps] [out.npz]
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
from brain_agent import BrainAgent  # noqa: E402
from minicraft import MiniCraft  # noqa: E402

steps = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
out = sys.argv[2] if len(sys.argv) > 2 else "brain_mc.npz"
ag = BrainAgent(5, curiosity=0.0, emotions=True, fear=True, mood=False)
worlds = [(0.62, 0.14, 0.12, 0.06, 0.06), (0.72, 0.03, 0.08, 0.12, 0.05)]
env = MiniCraft(seed=0, p=worlds[0])
obs = env.reset()
eps = lambda t: max(0.02, 0.3 - 0.28 * t / (steps / 3))
a, c, q = ag.act(obs, eps(0))
ep, rewards = 0.0, []
for t in range(steps):
    o2, r, d = env.step(a)
    a2, c2, q2 = ag.act(o2, eps(t))
    ag.learn(c, a, r, o2, c2, q2, a2, d)
    a, c, q = a2, c2, q2
    ep += r
    if d:
        rewards.append(ep)
        ep = 0.0
        env = MiniCraft(seed=len(rewards), p=worlds[len(rewards) % 2])  # many different worlds
        obs = env.reset()
        a, c, q = ag.act(obs, eps(t))
print(f"childhood: {steps} steps, last 20 episodes reward {np.mean(rewards[-20:]):.1f}")
np.savez(out, W=ag.W, F=ag.F, FQ=ag.FQ, steps=ag.steps)
print("saved", out)
