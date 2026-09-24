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
p.add_argument("--eyes", default="", help="URL of the bot's first-person viewer, e.g. http://localhost:3007")
p.add_argument("--record", default="", help="directory to save (frame, senses) pairs for training vision")
p.add_argument("--see", action="store_true", help="feed the visual cortex code to the striatum")
p.add_argument("--blind", action="store_true", help="with --see: drop the direct block senses, act from vision")
p.add_argument("--self", default="", help="path of self.json: intrinsic motivation + autobiographical memory")
args = p.parse_args()

N_ACT = 7 if args.self else 5  # + craft something new, eat
agent = BrainAgent(N_ACT, curiosity=args.curiosity, emotions=not args.no_fear, fear=not args.no_fear, mood=False)
me = None
if args.self:
    from personality import Self

    me = Self(args.self)
    print(f"I am {me.me['name']}, {me.me['age_steps']} steps old, I know {len(me.me['known_items'])} things",
          flush=True)
agent.blind = args.blind
cortex = None
if args.see:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vision"))
    from visual_cortex import VisualCortex, retina  # noqa: E402

    cortex = VisualCortex(seed=1)
    vc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "visual_cortex.npz")
    if os.path.exists(vc):
        cortex.syn[:] = np.load(vc)["syn"]
        print("visual cortex loaded (developed)", flush=True)
if os.path.exists(args.load):
    z = np.load(args.load)
    na = min(z["W"].shape[1], N_ACT)  # a brain grown with fewer actions keeps what it knows
    agent.W[:, :na], agent.F[:], agent.steps = z["W"][:, :na], z["F"], int(z["steps"])
    if agent.FQ is not None and "FQ" in z.files:
        agent.FQ[:, :na] = z["FQ"][:, :na]
    print(f"loaded {args.load}: {agent.steps} steps of experience", flush=True)


def save():
    extra = {"FQ": agent.FQ} if agent.FQ is not None else {}
    np.savez(args.load, W=agent.W, F=agent.F, steps=agent.steps, **extra)
    if me:
        me.save()


class Eyes:
    """The brain's eyes: eyes.py (headless Chromium on the bot's first-person view) in its own process."""

    def __init__(self, url):
        import subprocess

        here = os.path.dirname(os.path.abspath(__file__))
        self.p = subprocess.Popen([sys.executable, os.path.join(here, "eyes.py"), url],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def look(self):
        try:
            self.p.stdin.write(b"x\n")
            self.p.stdin.flush()
            raw = self.p.stdout.read(64 * 64 * 3)
        except Exception:
            return None
        return np.frombuffer(raw, np.uint8).reshape(64, 64, 3) if len(raw) == 64 * 64 * 3 else None


def save_rec(rec):
    os.makedirs(args.record, exist_ok=True)
    k = len(os.listdir(args.record))
    np.savez_compressed(os.path.join(args.record, f"rec_{k:04d}.npz"), frames=np.array([r[0] for r in rec]),
                        grid=np.array([r[1] for r in rec]), goal=np.array([r[2] for r in rec]))
    print(f"saved {len(rec)} seen frames -> {args.record}", flush=True)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        print("bot connected", flush=True)
        eyes, n_msg = None, 0
        rec = []
        prev = None  # (cells, action)
        total, t0 = 0.0, time.time()
        for line in self.rfile:
            m = json.loads(line)
            obs = (np.array(m["obs"], np.int64), min(int(m.get("inv", 0)), 7), int(m.get("goal", 0)))
            n_msg += 1
            if args.eyes and eyes is None and n_msg == 5:  # the viewer starts after the bot spawns
                eyes = Eyes(args.eyes)
                print("eyes open", flush=True)
            code = None
            if eyes:
                frame = eyes.look()
                if frame is not None and cortex is not None:
                    code = cortex(retina(frame), plasticity=True)  # the cortex keeps developing live
                    obs = obs + (code,)
                if frame is not None and args.record:
                    rec.append((frame, obs[0].copy(), obs[2]))
                    if len(rec) >= 500:
                        save_rec(rec)
                        rec = []
            say, reward = None, float(m["reward"])
            if me:  # the reward comes from inside: novelty, places, hunger, pain
                reward, say = me.feel(m)
                obs = obs + ((None,) if len(obs) == 3 else ()) + (me.drives(m),)
            eps = me.exploration() if me else max(0.02, args.eps * (1 - agent.steps / 20000))
            a, cells, qv = agent.act(obs, eps)
            if prev is not None:
                agent.learn(prev[0], prev[1], reward, obs, cells, qv, a, bool(m.get("done")))
            prev = None if m.get("done") else (cells, a)
            total += reward
            reply = {"action": a}
            if say:
                reply["say"] = say
                print("says:", say, flush=True)
            self.wfile.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())
            if agent.steps % 200 == 0:
                print(f"step {agent.steps}: reward so far {total:.1f} "
                      f"({agent.steps / max(time.time() - t0, 1e-9):.1f} steps/s)", flush=True)
            if agent.steps % 2000 == 0:
                save()
        if rec:
            save_rec(rec)
        save()
        print("bot disconnected, brain saved", flush=True)


socketserver.ThreadingTCPServer.allow_reuse_address = True


def _on_term(*_):  # being stopped is not a reason to forget
    save()
    sys.exit(0)


import signal  # noqa: E402

signal.signal(signal.SIGTERM, _on_term)

if __name__ == "__main__":
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), Handler) as srv:
        print(f"brain listening on 127.0.0.1:{args.port}", flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            save()
