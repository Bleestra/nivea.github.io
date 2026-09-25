"""
Brain server for Minecraft: the SynapseBrain-Agent learns while it plays.

The body - the Mineflayer bot (bot.js) or the Fabric mod in the real game client (../fabric-mod) -
sends one JSON line per decision:
    {"obs": [25 block classes], "inv": logs_in_inventory, "reward": r, "done": false, ...}
and gets back one line: {"action": a, "target": ..., "say": ..., "hud": {...}}.
The Fabric body also sends what its eyes see, straight from the game's renderer:
    "frame": base64 of raw BGR bytes, "frame_wh": [w, h]

    python3 brain_server.py [--port 5555] [--load brain_mc.npz] [--see] [--device auto|cpu|cuda]
The brain's synapses are saved to brain_mc.npz every 2000 steps and on exit, so learning
carries over between sessions. With --see on a GPU the visual cortex is the large one
(vision/visual_cortex_gpu.py); the rest of the brain stays on the CPU, where its small
sparse steps are faster (measured: 23 us per step on the CPU, 366 us on an RTX 3090).
"""
import argparse
import base64
import json
import os
import socketserver
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
from brain_agent import BrainAgent  # noqa: E402
from mind import swap_in  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--port", type=int, default=5555)
p.add_argument("--load", default="brain_mc.npz")
p.add_argument("--eps", type=float, default=0.1, help="exploration at the start (decays to 0.02)")
p.add_argument("--curiosity", type=float, default=0.05, help="intrinsic reward for surprise (sparse rewards)")
p.add_argument("--no-fear", action="store_true", help="switch the amygdala off")
p.add_argument("--eyes", default="", help="URL of the bot's first-person viewer, e.g. http://localhost:3007")
p.add_argument("--record", default="", help="directory to save (frame, senses) pairs for training vision")
p.add_argument("--see", action="store_true", help="eyes: the visual cortex sees, learns to recognise, the brain reacts")
p.add_argument("--blind", action="store_true", help="the same as --senses human")
p.add_argument("--senses", default="grow", choices=["full", "grow", "human"],
               help="with --see: full - direct senses + eyes; grow - the eyes take over as they learn (as a child); "
                    "human - only what a person has (vision, hearing, touch, the body, the HUD)")
p.add_argument("--name", default="", help="the name of a newborn (an existing self.json keeps its own)")
p.add_argument("--telemetry", default="", help="directory for the dashboard: live state, decisions, events, series")
p.add_argument("--self", default="", help="path of self.json: intrinsic motivation + autobiographical memory")
p.add_argument("--voice", default="", help="trained language brain (train_voice.py) to answer in chat")
p.add_argument("--mind", default="", help="mind.npz: learned chains, skills, reasoning, self-knowledge (needs --self)")
p.add_argument("--limbic", default="", help="directory: the whole growing brain with feelings (mind + limbic system; needs --self)")
p.add_argument("--device", default="cpu", choices=["auto", "cpu", "cuda"],
               help="where the live visual cortex computes: cpu (default - the GPU is busy drawing the game) or cuda")
p.add_argument("--neurons", type=int, default=131072, help="visual cortex size on the GPU")
p.add_argument("--retina", type=int, default=256, help="picture size the GPU retina sees (pixels per side)")
p.add_argument("--zones", type=int, default=8, help="the picture is understood in zones x zones (as the body's vis_labels)")
args = p.parse_args()
_hold = os.path.join(os.path.dirname(os.path.abspath(args.load)), "HOLD")
if os.path.exists(_hold):                                 # memory under maintenance: wake up when it is done
    print("waiting: HOLD (the memory is being worked on)", flush=True)
    while os.path.exists(_hold):
        time.sleep(1)
if args.device != "auto":
    os.environ["SYNAPSE_DEVICE"] = args.device
if args.blind:
    args.senses = "human"

from actions import ACTIONS  # noqa: E402

N_ACT = len(ACTIONS) if args.self else 5  # the whole player repertoire (bot.js has the first 41)
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
    if os.environ.get("EPISODIC", "1") == "1":            # every moment lived, within the project's disk budget
        import limits
        from episodic import Episodic, faiss

        mind.episodic = Episodic(os.path.join(args.limbic, "episodes"), room=limits.disk_room)
        print(f"episodic memory: {mind.episodic.n:,} moments lived"
              f"{'' if faiss is not None else ' (no faiss: exact search over the last moments)'}", flush=True)
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

    me = Self(args.self, name=args.name) if args.name else Self(args.self)
    print(f"I am {me.me['name']}, {me.me['age_steps']} steps old, I know {len(me.me['known_items'])} things",
          flush=True)
seeing = None
MODELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
if args.see:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vision"))
    from seeing import Seeing  # noqa: E402

    try:
        seeing = Seeing(os.path.splitext(args.load)[0], args.device, args.neurons, args.retina, MODELS, args.zones)
    except ImportError:                                  # no PyTorch: the eyes need it for recognition
        print("the eyes need PyTorch (pip install torch)", flush=True)
    if seeing:
        print(seeing.describe() + f"; senses: {args.senses}", flush=True)
tele = None
if args.telemetry:
    from telemetry import Telemetry  # noqa: E402

    tele = Telemetry(args.telemetry, args.senses if seeing else "no eyes")
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
    z.close()                                  # (an open file cannot be replaced by the next save on Windows)
    print(f"loaded {args.load}: {agent.steps} steps of experience", flush=True)
if child is None and mind is not None and mind.load(args.mind):
    print(f"mind loaded: {len(mind.names)} concepts, {int(mind.nev.sum())} events remembered", flush=True)
def frame_of(m):
    """What the body's eyes saw, if it sent a picture (the Fabric body does): uint8 BGR (h, w, 3)."""
    raw = m.get("frame")
    if not raw:
        return None
    w, h = m.get("frame_wh", (64, 64))
    buf = np.frombuffer(bytearray(base64.b64decode(raw)), np.uint8)
    return buf.reshape(h, w, 3) if buf.size == w * h * 3 else None


def small(frame):
    """The 64x64 picture the older parts of the brain expect (sky colours, recordings)."""
    if frame is None or frame.shape[:2] == (64, 64):
        return frame
    import cv2

    return cv2.resize(frame, (64, 64), interpolation=cv2.INTER_AREA)


def hud():
    """What the body shows above the game: who I am, what I feel, what I want."""
    if child is None:
        return None
    from limbic import STAGE_NAMES

    L, mi = child.limbic, child.mind
    step = mi.names[mi.goal] if getattr(mi, "goal", None) is not None else ""
    aim = mi.names[mi.intent] if getattr(mi, "intent", None) is not None else ""
    goal = (f"{aim} · шаг: {step}" if step and step != aim else aim) if aim else step      # what I decided, and the step
    t = int(me.me.get("lived_ticks", 0)) if me else 0                   # game time lived: 24000 ticks a day
    lived = f"{t // 24000} д {t % 24000 // 1000} ч" if t >= 24000 else f"{t // 1000} ч {t % 1000 * 60 // 1000} мин"
    return {"name": me.me["name"] if me else "Synapse", "age": int(child.age), "lived": lived, "stage": STAGE_NAMES[L.stage()],
            "feeling": L.say()[:160], "goal": goal}


core = None
if child is not None:
    from brain_core import Grown  # noqa: E402

    core = Grown(child, me, voice)


def grow():
    """The mind has no ceilings of its own; its skill synapses grow when crowded, within the PC's room."""
    m = child.mind if child is not None else mind
    if m is None:
        return
    try:
        import limits

        if m.grow_skills(limits.room_to_grow()):
            print(f"skills grew: {len(m.G):,} synapse rows ({m.G.nbytes / 2 ** 30:.1f} GB); "
                  f"concepts {len(m.names):,} (room {len(m.val):,})", flush=True)
    except Exception as e:
        print("grow:", e, flush=True)


def save():
    grow()
    extra = {"FQ": agent.FQ, "FB": agent.FB} if agent.FQ is not None else {}
    tmp = os.path.splitext(args.load)[0] + ".saving.npz"                    # aside, then swapped in
    np.savez(tmp, W=agent.W, F=agent.F, steps=agent.steps, **extra)
    swap_in(tmp, args.load)
    if child is not None:
        feel_bridge.save(child, args.limbic)
        try:                                              # a line of the life log: is he growing?
            prog = os.path.join(os.path.dirname(os.path.abspath(args.limbic)), "progress.csv")
            new = not os.path.exists(prog)
            with open(prog, "a", encoding="utf-8") as f:
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
    if seeing is not None:                                    # the eyes develop live: keep what they learned
        seeing.save()
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
        pace = {}                                              # where a moment's time goes (moving averages, ms)
        def lap(key, since):
            now_ = time.perf_counter()
            pace[key] = pace.get(key, (now_ - since) * 1000) * 0.9 + (now_ - since) * 100
            return now_
        for line in self.rfile:
            t_in = time.perf_counter()
            m = json.loads(line)
            t_in = lap("brain_read_ms", t_in)
            n_msg += 1
            if args.eyes and eyes is None and n_msg == 5:  # the viewer starts after the bot spawns
                eyes = Eyes(args.eyes)
                print("eyes open", flush=True)
            frame = frame_of(m)                                # the Fabric body sends what it sees
            if frame is None and eyes:
                frame = eyes.look()
            full_frame, percept = frame, None
            if frame is not None:
                if args.record:
                    rec.append((small(frame), np.array(m["obs"], np.int64), int(m.get("goal", 0))))
                    if len(rec) >= 500:
                        save_rec(rec)
                        rec = []
                if seeing is not None:
                    # the eyes see and learn to recognise (the direct senses and the rays only teach them);
                    # then, as the chosen senses say, what the eyes perceive replaces the direct senses
                    percept = seeing.look(frame, m)
                    seeing.apply(m, args.senses)
                    m["_vis_ids"] = percept["ids"]             # what is recognised where: cells for the habits
                    m["_motion"] = percept.get("motion")        # what moves, what comes closer
                frame = small(frame)
            t_in = lap("brain_eyes_ms", t_in)
            vis = np.array(percept["ids"], np.int64) if percept is not None else None
            obs = (np.array(m["obs"], np.int64), min(int(m.get("inv", 0)), 7), int(m.get("goal", 0)), vis)
            tgt = None
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
                a, tgt, say2, o = core.decide(m, frame, forced)
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
            t_in = lap("brain_think_ms", t_in)
            total += reward
            if a >= int(m.get("n_actions", N_ACT)):            # this body cannot do it (bot.js has 41 actions)
                a_body = 4
            else:
                a_body = a
            reply = {"action": a_body}
            if child is not None and tgt is not None:
                reply["target"] = tgt                                 # where a motor program is aimed
            if say:
                reply["say"] = say
                print("says:", say, flush=True)
            h = hud() if child is not None else None
            if m.get("want_hud") and h is not None:            # the Fabric body shows it above the game
                reply["hud"] = h
            self.wfile.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())
            if tele is not None:
                try:
                    m["_pace"] = {**(m.get("pace") or {}), **pace}
                    tele.moment(m, a, tgt, say, reward, h, full_frame, seeing, child, me)
                except Exception as e:                         # the dashboard must never stop a life
                    print("telemetry:", e, flush=True)
            if agent.steps % 200 == 0:
                print(f"step {agent.steps}: reward so far {total:.1f} "
                      f"({agent.steps / max(time.time() - t0, 1e-9):.1f} steps/s)", flush=True)
            lap("brain_rest_ms", t_in)
            if agent.steps % 2000 == 0:
                t_save = time.perf_counter()
                save()
                print(f"saved the brain in {time.perf_counter() - t_save:.1f} s", flush=True)
                if seeing is not None:
                    st = seeing.stats()
                    print(f"eyes: recognise {st['things'] * 100:.0f}% of zones ({st['vocabulary']} names), "
                          f"ground {st['ground'] * 100:.0f}%, sky {st['sky'] * 100:.0f}%, trust {st['trust']}", flush=True)
        if rec:
            save_rec(rec)
        save()
        if tele is not None:
            tele.flush()
        print("bot disconnected, brain saved", flush=True)


socketserver.ThreadingTCPServer.allow_reuse_address = True


def _on_term(*_):  # being stopped is not a reason to forget
    save()
    sys.exit(0)


import signal  # noqa: E402

signal.signal(signal.SIGTERM, _on_term)

def _watch_stop():
    """world.py asks a brain to go to sleep by leaving a STOP file next to its memory (on Windows a process
    cannot be sent SIGTERM): save everything, then exit."""
    import threading

    flag = os.path.join(os.path.dirname(os.path.abspath(args.load)), "STOP")

    def loop():
        while True:
            time.sleep(1.0)
            if os.path.exists(flag):
                os.remove(flag)
                print("asked to sleep: saving", flush=True)
                save()
                if tele is not None:
                    tele.offline()
                os._exit(0)
    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    _watch_stop()
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), Handler) as srv:
        print(f"brain listening on 127.0.0.1:{args.port}", flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            save()
