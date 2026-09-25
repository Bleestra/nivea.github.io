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
p.add_argument("--voice", default="", help="trained language brain (train_voice.py) to answer in chat")
p.add_argument("--mind", default="", help="mind.npz: learned chains, skills, reasoning, self-knowledge (needs --self)")
p.add_argument("--limbic", default="", help="directory: the whole growing brain with feelings (mind + limbic system; needs --self)")
args = p.parse_args()

N_ACT = 41 if args.self else 5  # full player repertoire of bot.js (see ACTIONS there)
mind = None
child = None
if args.limbic:
    import feel_bridge  # noqa: E402
    from mind_bridge import ru_thought, state_from, talk  # noqa: E402

    child = feel_bridge.MCChild(N_ACT)
    if feel_bridge.load(child, args.limbic):
        print(f"grown brain loaded: age {child.age}, {len(child.mind.names)} concepts, "
              f"stage «{__import__('limbic').STAGE_NAMES[child.limbic.stage()]}»", flush=True)
    mind = child.mind
    agent = mind.flat
elif args.mind:
    from mind import Mind  # noqa: E402
    from mind_bridge import ru_thought, state_from, talk  # noqa: E402

    mind = Mind(N_ACT, curiosity=args.curiosity, fear=not args.no_fear, emotions=not args.no_fear)
    agent = mind.flat  # habits: the same striatum as before (childhood skills are kept)
else:
    agent = BrainAgent(N_ACT, curiosity=args.curiosity, emotions=not args.no_fear, fear=not args.no_fear, mood=False)
voice = None
if args.voice and os.path.exists(args.voice):
    from voice import Voice

    voice = Voice(args.voice)
    print("voice loaded", flush=True)
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
    vc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "visual_cortex.npz")
    if os.path.exists(vc):
        cortex.syn[:] = np.load(vc)["syn"]
        print("visual cortex loaded (developed)", flush=True)
if os.path.exists(args.load):
    z = np.load(args.load)
    na = min(z["W"].shape[1], N_ACT)  # a brain grown with fewer actions keeps what it knows
    agent.W[:, :na], agent.steps = z["W"][:, :na], int(z["steps"])
    nf = min(z["F"].shape[1], agent.F.shape[1])
    agent.F[:, :nf] = z["F"][:, :nf]
    if agent.FQ is not None and "FQ" in z.files:
        agent.FQ[:, :na] = z["FQ"][:, :na]
    if agent.FQ is not None and "FB" in z.files:
        if z["FB"].shape == agent.FB.shape:
            agent.FB[:] = z["FB"]
    print(f"loaded {args.load}: {agent.steps} steps of experience", flush=True)
if child is None and mind is not None and mind.load(args.mind):
    print(f"mind loaded: {len(mind.names)} concepts, {int(mind.nev.sum())} events remembered", flush=True)
teacher = None
if cortex is not None:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vision"))
    from teacher import SensorTeacher  # noqa: E402

    teacher = SensorTeacher(cortex.n)
    tpath = os.path.splitext(args.load)[0] + "_eyes.npz"
    if os.path.exists(tpath):
        teacher.load(tpath)


core = None
if child is not None:
    from brain_core import Grown  # noqa: E402

    core = Grown(child, me, voice)


def save():
    extra = {"FQ": agent.FQ, "FB": agent.FB} if agent.FQ is not None else {}
    np.savez(args.load, W=agent.W, F=agent.F, steps=agent.steps, **extra)
    if child is not None:
        feel_bridge.save(child, args.limbic)
        try:                                              # a line of the life log: is he growing?
            prog = os.path.join(os.path.dirname(os.path.abspath(args.limbic)), "progress.csv")
            new = not os.path.exists(prog)
            with open(prog, "a") as f:
                if new:
                    f.write("time,age,stage,concepts,advancements,known_items,deaths,feeling\n")
                L = child.limbic
                f.write(f"{time.strftime('%Y-%m-%d %H:%M')},{child.age},{L.stage()},{len(child.mind.names)},"
                        f"{len(me.me.get('advancements', [])) if me else 0},{len(me.me['known_items']) if me else 0},"
                        f"{len(me.me.get('deaths', [])) if me else 0},{L.say().split(' — ')[0]}\n")
        except Exception as e:
            print("progress log:", e, flush=True)
    elif mind is not None:
        mind.save(args.mind)
    if teacher is not None:
        teacher.save(os.path.splitext(args.load)[0] + "_eyes.npz")
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
        last_target, last_said = None, 0.0
        if child is not None:
            core.new_body()
        total, t0 = 0.0, time.time()
        for line in self.rfile:
            m = json.loads(line)
            obs = (np.array(m["obs"], np.int64), min(int(m.get("inv", 0)), 7), int(m.get("goal", 0)))
            n_msg += 1
            if args.eyes and eyes is None and n_msg == 5:  # the viewer starts after the bot spawns
                eyes = Eyes(args.eyes)
                print("eyes open", flush=True)
            code = None
            frame = None
            if eyes:
                frame = eyes.look()
                if frame is not None and cortex is not None:
                    code = cortex(retina(frame), plasticity=True)  # the cortex keeps developing live
                    # the direct senses teach the eyes; blind: act from what the eyes perceive
                    pg, ps, pt = teacher.teach(code, obs[0], int(m.get("sky", 0)), obs[2] // 4)
                    if args.blind:
                        obs = (pg, obs[1], pt * 4 + 2)
                        m["sky"] = ps
                    obs = obs + (code,)
                if frame is not None and args.record:
                    rec.append((frame, obs[0].copy(), obs[2]))
                    if len(rec) >= 500:
                        save_rec(rec)
                        rec = []
            if len(obs) == 3:
                obs = obs + (None,)
            say, reward = None, float(m["reward"])
            if me and child is None:  # the reward comes from inside: novelty, places, hunger, pain, advancements
                reward, say = me.feel(m)
                # inner senses + touch/balance all around + sky + the feeling of being stuck
                inner = me.drives(m) + list(m.get("around", [])) + [m.get("sky", 0), m.get("stuck", 0)]
                obs = obs + ([int(x or 0) for x in inner],)  # a sense not ready yet (at spawn) reads 0
            for user, text in (m.get("heard", []) if child is None else []):  # someone spoke to us
                if child is not None and not say:
                    say = feel_bridge.talk(child, text)  # feelings, loves, fears
                if mind is not None and not say:
                    say = talk(mind, text)  # questions about itself and about how to do things
                if voice and not say:
                    say = voice.reply(text, me)
                if me:
                    me.note(f"{user} сказал: «{text}»" + (f"; я ответил: «{say}»" if say else ""), None)
            done = bool(m.get("done"))
            if child is not None:
                forced = None
                force = os.environ.get("FORCE_FILE")                # the experimenter's hand (for staged experiments)
                if force and os.path.exists(force):
                    parts = open(force).read().split()
                    if parts:
                        forced = int(parts[0])
                        left = int(parts[1]) - 1 if len(parts) > 1 else 0
                        if left > 0:
                            open(force, "w").write(f"{forced} {left}")
                        else:
                            os.remove(force)
                        print(f"[forced] action {forced}", flush=True)
                a, tgt, say2, o = core.decide(m, frame if eyes else None, forced)
                say = say or say2
                fev = m.get("fev") or {}
                if fev.get("trades") or fev.get("traded") or any(k in ("villager", "golem") for k, _, _ in o["near"]):
                    vs = [x for x in o["near"] if x[0] in ("villager", "golem")]
                    print(f"[village] step {agent.steps} action {a} near {vs[:3]} trades {fev.get('trades', [])[:3]} "
                          f"traded {fev.get('traded')} indoors {child.concepts(o).get('indoors')} "
                          f"feel {child.limbic.say()[:60]}", flush=True)
            elif mind is not None:
                a = mind.step(obs, state_from(m), reward, done, explore=me.exploration() if me else 0.1)
                if mind.target is not None and mind.target != last_target and time.time() - last_said > 60:
                    last_target, last_said = mind.target, time.time()
                    thought = ru_thought(mind)
                    if me:
                        me.note("думаю: " + thought, None)
                    say = say or thought
            else:
                eps = me.exploration() if me else max(0.02, args.eps * (1 - agent.steps / 20000))
                a, cells, qv = agent.act(obs, eps)
                if prev is not None:
                    agent.learn(prev[0], prev[1], reward, obs, cells, qv, a, done)
                prev = None if done else (cells, a)
            total += reward
            reply = {"action": a}
            if child is not None and tgt is not None:
                reply["target"] = tgt                                 # where a motor program is aimed
            if say:
                reply["say"] = say
                print("says:", say, flush=True)
            self.wfile.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())
            if agent.steps % 200 == 0:
                print(f"step {agent.steps}: reward so far {total:.1f} "
                      f"({agent.steps / max(time.time() - t0, 1e-9):.1f} steps/s)", flush=True)
            if agent.steps % 2000 == 0:
                save()
                if teacher is not None:
                    print("eyes agree with the senses:", teacher.report(), flush=True)
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
