"""
Brain server for Minecraft: the SynapseBrain-Agent learns while it plays.

The Mineflayer bot (bot.js) sends one JSON line per decision:
    {"obs": [25 block classes], "inv": logs_in_inventory, "reward": r, "done": false}
and gets back one line: {"action": a}  (0 forward, 1 turn left, 2 turn right, 3 dig, 4 wait).

    python3 brain_server.py [--port 5555] [--load brain_mc.npz]
The brain's synapses are saved to brain_mc.npz every 2000 steps and on exit, so learning
carries over between sessions.
"""
import argparse
import json
import os
import socketserver
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
from brain_agent import BrainAgent  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--port", type=int, default=5555)
p.add_argument("--load", default="brain_mc.npz")
p.add_argument("--eps", type=float, default=0.1, help="exploration at the start (decays to 0.02)")
p.add_argument("--curiosity", type=float, default=0.05, help="intrinsic reward for surprise (sparse rewards)")
p.add_argument("--no-fear", action="store_true", help="switch the amygdala off")
args = p.parse_args()

agent = BrainAgent(5, curiosity=args.curiosity, emotions=not args.no_fear, fear=not args.no_fear, mood=False)
if os.path.exists(args.load):
    z = np.load(args.load)
    agent.W[:], agent.F[:], agent.steps = z["W"], z["F"], int(z["steps"])
    if agent.FQ is not None and "FQ" in z.files:
        agent.FQ[:] = z["FQ"]
    print(f"loaded {args.load}: {agent.steps} steps of experience", flush=True)


def save():
    extra = {"FQ": agent.FQ} if agent.FQ is not None else {}
    np.savez(args.load, W=agent.W, F=agent.F, steps=agent.steps, **extra)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        print("bot connected", flush=True)
        prev = None  # (cells, action)
        total, t0 = 0.0, time.time()
        for line in self.rfile:
            m = json.loads(line)
            obs = (np.array(m["obs"], np.int64), min(int(m.get("inv", 0)), 7), int(m.get("goal", 0)))
            eps = max(0.02, args.eps * (1 - agent.steps / 20000))
            a, cells, qv = agent.act(obs, eps)
            if prev is not None:
                agent.learn(prev[0], prev[1], float(m["reward"]), obs, cells, qv, a, bool(m.get("done")))
            prev = None if m.get("done") else (cells, a)
            total += float(m["reward"])
            self.wfile.write((json.dumps({"action": a}) + "\n").encode())
            if agent.steps % 200 == 0:
                print(f"step {agent.steps}: reward so far {total:.1f} "
                      f"({agent.steps / max(time.time() - t0, 1e-9):.1f} steps/s)", flush=True)
            if agent.steps % 2000 == 0:
                save()
        save()
        print("bot disconnected, brain saved", flush=True)


socketserver.ThreadingTCPServer.allow_reuse_address = True

if __name__ == "__main__":
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), Handler) as srv:
        print(f"brain listening on 127.0.0.1:{args.port}", flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            save()
