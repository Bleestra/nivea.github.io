"""
Can a brain learn logical chains and skills by itself? CraftWorld, the same reward for everyone.

  flat   : BrainAgent - one striatum, TD(lambda), fear (the brain that already plays Minecraft)
  mind   : Mind - concept neurons, learned chain synapses, goal-conditioned skill synapses with
           hindsight replay, reasoning by spreading activation, competence/self-knowledge
Measured per block of lives: tech level reached (0..9, 9 = iron pickaxe), how often the iron
pickaxe is made, and how many steps it takes to get out of a cave / a pit to the sky.
    python3 chain_bench.py [lives=120] [seeds=3]
"""
import sys
import time

import numpy as np

from brain_agent import BrainAgent
from craftworld import CraftWorld, ACTIONS
from mind import Mind


def life(env, agent, kind):
    obs = env.reset()
    born, esc = env.born_in, None
    prev = None
    done = False
    while not done:
        if kind == "mind":
            a = agent.step(obs, env.state(), prev[1] if prev else 0.0)
            obs2, r, done = env.step(a)
            prev = (a, r)
        else:
            a, cells, qv = agent.act(obs, max(0.03, 0.2 * (1 - agent.steps / 40000)))
            if prev is not None:
                agent.learn(prev[0], prev[1], prev[2], obs, cells, qv, a, False)
            obs2, r, done = env.step(a)
            prev = (cells, a, r)
        if esc is None and env.state()["sky"]:
            esc = env.t
        obs = obs2
    if kind == "mind":
        agent.step(obs, env.state(), prev[1], done=True)
    else:
        agent.learn(prev[0], prev[1], prev[2], obs, prev[0], agent.q(prev[0]), 0, True)
    return env.tech(), born, esc if esc is not None else env.life


def run(kind, lives, seed):
    env = CraftWorld(seed=seed)
    agent = Mind(len(ACTIONS), seed=seed) if kind == "mind" else BrainAgent(len(ACTIONS), seed=seed, emotions=True, mood=False)
    out = [life(env, agent, kind) for _ in range(lives)]
    return out, agent


if __name__ == "__main__":
    lives = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    blk = lives // 4
    for kind in ("flat", "mind"):
        t0 = time.time()
        res = [run(kind, lives, s) for s in range(seeds)]
        print(f"\n{kind}  ({time.time() - t0:.0f}s)")
        for b in range(4):
            rows = [x for out, _ in res for x in out[b * blk:(b + 1) * blk]]
            tech = np.mean([t for t, _, _ in rows])
            iron = np.mean([t >= 9 for t, _, _ in rows])
            cave = [e for _, k, e in rows if k == "cave"]
            pit = [e for _, k, e in rows if k == "pit"]
            print(f"  lives {b * blk + 1:3d}-{(b + 1) * blk:3d}: tech {tech:4.2f}/9  iron pickaxe {iron * 100:5.1f}%  "
                  f"out of cave {np.median(cave):5.0f} steps  out of pit {np.median(pit):5.0f} steps")
        if kind == "mind":
            m = res[0][1]
            print("  learned chains (read out of the synapses):")
            for line in m.why(m.idx.get("have:iron_pick", 0)):
                print("    " + line)
