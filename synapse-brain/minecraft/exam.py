"""
Exams in the real game: the same tasks, in the same places, for any brain - so that whether a change helps is
a number, not an impression.

A player "Examinee" joins the running world (python world.py) with the Synapse body, far from the living AIs.
Its brain is the real brain_server, started on a COPY of someone's memory (their life is not touched) and on a
frozen COPY of the code (the code can change while the exams run). Or a newborn, or a random brain to compare
with. Each task is staged through the server console (RCON) and measured through it as well - the same for
every brain: what is in the bag, health, food, deaths, where, in game ticks (the world's pace changes).

  wood    from nothing to stone: a forest, an empty bag, day. Log, planks, table, wooden pickaxe, cobblestone,
          stone pickaxe - when each came first.
  eat     hungry (food 6) with three apples in the bag: does it eat?
  forage  hungry with nothing: does it find something to eat?
  night   an empty bag at dusk in the forest: does it live to the morning, how much does it get hurt?
  pit     at the bottom of a shaft 4 deep: how soon is it out?

    python exam.py --subject random --tasks wood,eat,pit --places 3
    python exam.py --subject newborn --knowledge none
    python exam.py --subject Synapse3          # a copy of Synapse3's memory as it is now
    python exam.py --report                    # the table of everything measured so far
"""
import argparse
import json
import os
import random
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import time

from actions import ACTIONS
from rcon import Rcon

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
WORLD = os.path.join(HERE, "world")
EXAMS = os.path.join(WORLD, "exams")
FROZEN = os.path.join(WORLD, "exams", "code-frozen")   # (one frozen code for every exam, whichever world)
SERVER = {"dir": os.path.join(WORLD, "server"), "port": 25565, "rcon": 25575, "own": False}


def own_server(seed="synapse-exams-1", tick=40):
    """A world of its own for the exams (world/exam_server, a fixed seed, port 25566): exams there set the time and
    dig the ground without touching the living. Its server is started here and stopped when the exams end."""
    import secrets
    import subprocess

    d = os.path.join(WORLD, "exam_server")
    os.makedirs(d, exist_ok=True)
    main = os.path.join(WORLD, "server")
    for name in ("server.jar", "libraries", "versions"):              # the same game, not downloaded again
        src, dst = os.path.join(main, name), os.path.join(d, name)
        if os.path.exists(src) and not os.path.exists(dst):
            (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, dst)
    open(os.path.join(d, "eula.txt"), "w").write("eula=true\n")
    pw_path = os.path.join(d, "rcon.txt")
    if not os.path.exists(pw_path):
        open(pw_path, "w").write(secrets.token_hex(12))
    props = {"online-mode": "false", "spawn-protection": "0", "difficulty": "easy", "gamemode": "survival",
             "server-port": "25566", "max-players": "4", "view-distance": "6", "enforce-secure-profile": "false",
             "level-seed": seed, "enable-rcon": "true", "rcon.port": "25576", "rcon.password": open(pw_path).read().strip(),
             "motd": "Synapse exams"}
    with open(os.path.join(d, "server.properties"), "w", encoding="utf-8") as f:
        f.write("".join(f"{k}={v}\n" for k, v in props.items()))
    proc = subprocess.Popen(["java", "-Xmx2G", "-Xms512M", "-jar", "server.jar", "nogui"], cwd=d, stdin=subprocess.PIPE,
                            stdout=open(os.path.join(d, "server.log"), "a"), stderr=subprocess.STDOUT)
    import socket

    for _ in range(300):
        try:
            socket.create_connection(("127.0.0.1", 25576), timeout=1).close()
            break
        except OSError:
            time.sleep(1)
    SERVER.update({"dir": d, "port": 25566, "rcon": 25576, "own": True})
    try:                                             # the exams' world may run faster (no one lives there)
        from rcon import Rcon

        rc = Rcon(open(pw_path).read().strip(), port=25576)
        rc(f"tick rate {tick}")
        rc(f"gamerule keepInventory true")
        rc.close()
    except Exception as e:
        log("exam world pace:", e)
    return proc
NAME, PORT = "Examinee", 5610
PY = sys.executable
BASE_X, BASE_Z, STEP = 6000, 6000, 1500           # the places: forests near (6000 + 1500 i, 6000)

TASKS = {
    "wood": {"limit": 24000, "time": 1000, "goals": ["log", "planks", "crafting_table", "wooden_pickaxe", "cobblestone",
                                                    "stone_pickaxe"], "done": "stone_pickaxe"},
    "eat": {"limit": 6000, "time": 1000, "hungry": True, "give": ["apple 3"], "goals": ["ate"], "done": "ate"},
    "forage": {"limit": 24000, "time": 1000, "hungry": True, "goals": ["ate"], "done": "ate"},
    "night": {"limit": 11000, "time": 12500, "goals": ["morning"], "done": "morning"},
    "pit": {"limit": 6000, "time": 1000, "pit": 4, "goals": ["out"], "done": "out"},
}
KINDS = {"log": r"_log$|_stem$", "planks": r"_planks$"}


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


# ---------------------------------------------------------------- what the console says
class Console:
    def __init__(self):
        self.rc = Rcon(open(os.path.join(SERVER["dir"], "rcon.txt")).read().strip(), port=SERVER["rcon"])
        self.lock = threading.Lock()

    def __call__(self, cmd):
        with self.lock:
            return self.rc(cmd)

    def number(self, cmd):
        m = re.findall(r"(-?\d+(?:\.\d+)?)[fdb]?\s*$", self(cmd).strip())
        return float(m[0]) if m else None

    def online(self):
        return NAME in self("list")

    def gametime(self):
        return int(self.number("time query gametime") or 0)

    def bag(self):
        """The Examinee's inventory: {item: count}."""
        text = self(f"data get entity {NAME} Inventory")
        items = {}
        for m in re.finditer(r"count: (\d+)", text):
            idm = re.compile(r'id: "minecraft:([a-z0-9_]+)"').search(text, m.end())
            if idm:
                items[idm.group(1)] = items.get(idm.group(1), 0) + int(m.group(1))
        return items

    def pos(self):
        m = re.findall(r"(-?\d+\.?\d*)d", self(f"data get entity {NAME} Pos"))
        return tuple(float(x) for x in m[:3]) if len(m) >= 3 else None

    def health(self):
        return self.number(f"data get entity {NAME} Health")

    def food(self):
        return self.number(f"data get entity {NAME} foodLevel")

    def deaths(self):
        m = re.findall(r"has (\d+)", self(f"scoreboard players get {NAME} exam_deaths"))
        return int(m[0]) if m else 0


# ---------------------------------------------------------------- the places (the same for every brain)
def places(con, n):
    path = os.path.join(EXAMS, "places.json")
    got = json.load(open(path)) if os.path.exists(path) else []
    while len(got) < n:
        bx, bz = BASE_X + STEP * len(got), BASE_Z
        m = re.findall(r"\[(-?\d+), [^,]+, (-?\d+)\]", con(f"execute positioned {bx} 64 {bz} run locate biome minecraft:forest"))
        got.append([int(m[0][0]), int(m[0][1])] if m else [bx, bz])
        os.makedirs(EXAMS, exist_ok=True)
        json.dump(got, open(path, "w"))
    return got[:n]


R, DOWN, UP = 24, 10, 24                          # the ground kept for each place: 48 x 48, 10 below to 24 above
STORE = 100000                                     # where its copy is kept (far out: x + 100 000)


def start_of(con, i, center):
    """The exact block each place starts on - dry land, found once and kept (places.json), so that every brain
    begins on the same block - and a copy of the ground around it, to put back before each exam (what one brain
    cut down or dug, the next one finds whole)."""
    path = os.path.join(EXAMS, "starts.json")
    starts = json.load(open(path)) if os.path.exists(path) else {}
    if str(i) in starts:
        return starts[str(i)]
    for attempt in range(16):
        con(f"spreadplayers {center[0]} {center[1]} 0 {16 + 8 * attempt} false {NAME}")
        time.sleep(1.0)
        p = con.pos()
        if p is None:
            continue
        x, y, z = int(p[0] // 1), int(p[1] // 1), int(p[2] // 1)
        wet = any("passed" in con(f"execute if block {x} {y + dy} {z} minecraft:water") for dy in (-1, 0, 1))
        if not wet and y >= 62:
            break
    else:
        return None
    ground(con, x, y, z, keep=True)
    starts[str(i)] = [x, y, z]
    json.dump(starts, open(path, "w"))
    log(f"place {i}: starts on {x} {y} {z} (dry), its ground kept")
    return starts[str(i)]


def ground(con, x, y, z, keep=False):
    """Copy the ground around the start away (keep) or back (the next exam finds it whole)."""
    for ax in (x, x + STORE):
        con(f"forceload add {ax - R} {z - R} {ax + R} {z + R}")
    time.sleep(2.0)
    for k in range(3):                                # three slabs (the game clones at most 32768 blocks at once)
        z1, z2 = z - R + 16 * k, min(z - R + 16 * k + 15, z + R - 1)
        a = f"{x - R} {y - DOWN} {z1} {x + R - 1} {y + UP} {z2}"
        b = f"{x - R + STORE} {y - DOWN} {z1} {x + R - 1 + STORE} {y + UP} {z2}"
        said = con(f"clone {a} {x - R + STORE} {y - DOWN} {z1}") if keep else con(f"clone {b} {x - R} {y - DOWN} {z1}")
        if not said.startswith("Success"):
            log("clone:", said)
    con(f"kill @e[type=item,x={x - R},y={y - DOWN},z={z - R},dx={2 * R},dy={DOWN + UP},dz={2 * R}]")
    con(f"kill @e[type=experience_orb,x={x - R},y={y - DOWN},z={z - R},dx={2 * R},dy={DOWN + UP},dz={2 * R}]")
    for ax in (x, x + STORE):
        con(f"forceload remove {ax - R} {z - R} {ax + R} {z + R}")


# ---------------------------------------------------------------- the subjects
def freeze_code(run_dir):
    """The code as it is now, for the exam's brain: agent/, minecraft/*.py, the reference and the guide. When a
    frozen version is set (exams/code-frozen, with its name in VERSION), every exam uses that one: a battery of
    exams that runs for hours compares brains, not the edits made meanwhile."""
    frozen = FROZEN
    if os.path.exists(frozen):
        return frozen
    code = os.path.join(run_dir, "code")
    if os.path.exists(code):
        return code
    shutil.copytree(os.path.join(PROJECT, "agent"), os.path.join(code, "agent"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    mc = os.path.join(code, "minecraft")
    os.makedirs(mc)
    for f in os.listdir(HERE):
        if f.endswith(".py") or f == "world.json":
            shutil.copy(os.path.join(HERE, f), mc)
    for d in ("knowledge", "guide"):
        if os.path.exists(os.path.join(HERE, d)):
            shutil.copytree(os.path.join(HERE, d), os.path.join(mc, d))
    shutil.copytree(os.path.join(PROJECT, "vision"), os.path.join(code, "vision"), ignore=shutil.ignore_patterns("__pycache__"))
    return code


def commit():
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=PROJECT, capture_output=True, text=True).stdout.strip()
        return rev + ("+changes" if dirty else "")
    except OSError:
        return None


def code_version():
    v = os.path.join(FROZEN, "VERSION")
    return open(v).read().strip() if os.path.exists(v) else commit()


class Subject:
    """A brain for the Examinee: a copy of someone's memory, a newborn, or random."""

    def __init__(self, kind, run_dir, knowledge, fresh, memory=None):
        self.kind, self.run_dir, self.fresh = kind, run_dir, fresh
        self.knowledge = knowledge
        self.proc, self.srv = None, None
        self.pristine = memory or os.path.join(run_dir, kind, "pristine")   # (memory: an earlier copy, to compare
                                                                            # code versions on the very same mind)
        self.life = os.path.join(run_dir, kind, "life")
        if kind not in ("random", "newborn") and not os.path.exists(self.pristine):
            src = os.path.join(WORLD, "life", kind)
            os.makedirs(self.pristine)
            for f in ("brain.npz", "self.json"):
                if os.path.exists(os.path.join(src, f)):
                    shutil.copy(os.path.join(src, f), self.pristine)
            shutil.copytree(os.path.join(src, "growing"), os.path.join(self.pristine, "growing"))
            log(f"copied {kind}'s memory as it is now")
        if kind == "newborn":
            os.makedirs(self.pristine, exist_ok=True)

    def start(self):
        if self.kind == "random":
            self._random()
            return
        if self.fresh or not os.path.exists(self.life):
            if os.path.exists(self.life):
                shutil.rmtree(self.life)
            shutil.copytree(self.pristine, self.life)
        code = freeze_code(self.run_dir)
        d = self.life
        cmd = [PY, "-u", os.path.join(code, "minecraft", "brain_server.py"), "--port", str(PORT),
               "--load", os.path.join(d, "brain.npz"), "--self", os.path.join(d, "self.json"),
               "--limbic", os.path.join(d, "growing"), "--name", NAME, "--telemetry", os.path.join(d, "telemetry")]
        env = dict(os.environ, PYTHONIOENCODING="utf-8", SYNAPSE_KNOWLEDGE=json.dumps(self.knowledge),
                   SYNAPSE_WORLD=json.dumps({"exam": True}))
        self.out = open(os.path.join(self.run_dir, self.kind, "brain.log"), "a", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, cwd=os.path.join(code, "minecraft"), stdout=self.out, stderr=subprocess.STDOUT,
                                     env=env, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

    def _random(self):
        rng = random.Random(0)

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    for line in self.rfile:
                        m = json.loads(line)
                        n = int(m.get("n_actions", len(ACTIONS)))
                        self.wfile.write((json.dumps({"action": rng.randrange(n)}) + "\n").encode())
                except ConnectionError:                      # the body went away (the next task, or the end)
                    pass

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads, block_on_close = True, False      # stopping never waits for the body to hang up
        self.srv = Server(("127.0.0.1", PORT), Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait()
            self.proc = None
        if self.srv is not None:
            self.srv.shutdown()
            self.srv.server_close()
            self.srv = None

    def alive(self):
        return self.srv is not None or (self.proc is not None and self.proc.poll() is None)

    def stats(self):
        """How the brain chose during the exam (from its telemetry), if it keeps one."""
        p = os.path.join(self.life, "telemetry", "live.json")
        if self.kind == "random" or not os.path.exists(p):
            return None
        try:
            L = json.load(open(p, encoding="utf-8"))
        except ValueError:
            return None
        D = L.get("decisions", [])
        oks = [d["last"].get("ok") for d in D if d.get("last")]
        from collections import Counter
        return {"ok_share": round(sum(bool(o) for o in oks) / max(1, len(oks)), 2),
                "how": dict(Counter(d.get("how") for d in D)), "top": Counter(d["raw"] for d in D).most_common(5)}


# ---------------------------------------------------------------- one task in one place
def stage(con, task, place, i):
    t = TASKS[task]
    start = start_of(con, i, place)
    if start is None:
        log(f"no dry start near {place}")
        return None
    px, py, pz = start
    con(f"gamemode survival {NAME}")
    con(f"clear {NAME}")
    con(f"effect clear {NAME}")
    con("weather clear")
    con(f"time set {t['time']}")
    ground(con, px, py, pz)                           # the place as it was, whoever was here before
    con(f"tp {NAME} {px + 0.5} {py} {pz + 0.5}")
    time.sleep(1.0)
    p = con.pos()
    if p is None or abs(p[0] - px) > 8 or abs(p[2] - pz) > 8:     # (the brain acts meanwhile: a few steps)
        log(f"the Examinee is not at the start: {p}")
        return None
    said = con(f"spawnpoint {NAME} {px} {py} {pz}")
    if not said.startswith("Set"):
        log("spawnpoint:", said)
    con(f"effect give {NAME} minecraft:instant_health 1 10 true")
    con(f"effect give {NAME} minecraft:saturation 2 20 true")
    time.sleep(2.5)
    if t.get("hungry"):
        con(f"effect give {NAME} minecraft:hunger 60 255 true")
        for _ in range(120):
            f = con.food()
            if f is not None and f <= 6:
                break
            time.sleep(0.5)
        con(f"effect clear {NAME}")
    stage.food0 = con.food()                          # (before the food is given: a quick one eats at once,
    for g in t.get("give", []):                       # before run_task could look)
        con(f"give {NAME} {g}")
    if t.get("pit"):
        d = t["pit"]
        con(f"fill {px} {py - d} {pz} {px} {py - 1} {pz} air")
        con(f"tp {NAME} {px + 0.5} {py - d} {pz + 0.5}")
    return (px, py, pz)


def run_task(con, subject, task, place, i):
    t = TASKS[task]
    spot = stage(con, task, place, i)
    if spot is None:
        return None
    t0, wall0 = con.gametime(), time.time()
    deaths0 = con.deaths()
    food0 = getattr(stage, "food0", None)
    food0 = con.food() or 0 if food0 is None else food0
    first = {}
    hurt, hp_prev = 0.0, con.health() or 20.0
    while True:
        time.sleep(1.0)
        if not subject.alive():
            first["brain_died"] = con.gametime() - t0
            break
        now = con.gametime() - t0
        bag = con.bag()
        for g in t["goals"]:
            if g in first:
                continue
            pat = KINDS.get(g)
            have = any(re.search(pat, k) for k in bag) if pat else bag.get(g, 0) > 0
            if g == "ate":
                f = con.food()
                have = f is not None and f > food0
            elif g == "out":
                p = con.pos()
                have = p is not None and p[1] >= spot[1] - 0.2
            elif g == "morning":
                have = now >= t["limit"] - 50 and con.deaths() == deaths0
            if have:
                first[g] = now
        hp = con.health()
        if hp is not None:
            hurt += max(0.0, hp_prev - hp)
            hp_prev = hp
        if time.time() - getattr(run_task, "said", 0) > 120:        # still going: where, what it has
            run_task.said = time.time()
            p = con.pos()
            log(f"  {task} {now} ticks: at {tuple(round(v) for v in p) if p else '?'}, hp {hp}, "
                f"steps {first}, bag {dict(list(bag.items())[:6])}")
        if t["done"] in first or now >= t["limit"]:
            break
    ok = t["done"] in first
    return {"subject": subject.kind, "task": task, "place": i, "xz": place, "ok": ok, "first": first,
            "ticks": con.gametime() - t0, "wall_s": round(time.time() - wall0), "deaths": con.deaths() - deaths0,
            "hurt": round(hurt, 1), "bag": dict(sorted(con.bag().items(), key=lambda kv: -kv[1])[:12]),
            "brain": subject.stats(), "knowledge": subject.knowledge, "code": code_version(), "t": time.strftime("%Y-%m-%d %H:%M"),
            "world": "own" if SERVER["own"] else "main"}


# ---------------------------------------------------------------- the report
def report():
    path = os.path.join(EXAMS, "results.jsonl")
    if not os.path.exists(path):
        print("no exams yet")
        return
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    table = {}
    for r in rows:
        table.setdefault((r["subject"], r.get("label", ""), r["task"]), []).append(r)
    print(f"{'subject':24} {'task':7} {'passed':>7}  median ticks to each step (of those that got there)  deaths  hurt")
    for (who, label, task), rs in sorted(table.items()):
        goals = TASKS[task]["goals"]
        med = []
        for g in goals:
            v = sorted(r["first"][g] for r in rs if g in r["first"])
            med.append(f"{g}:{v[len(v) // 2]}({len(v)})" if v else f"{g}:-")
        name = who + (f" [{label}]" if label else "")
        print(f"{name:24} {task:7} {sum(r['ok'] for r in rs):>3}/{len(rs):<3}  {' '.join(med)}  "
              f"{sum(r['deaths'] for r in rs)}  {sum(r['hurt'] for r in rs):.0f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--subject", default="random", help="random, newborn, or an AI's name (a copy of its memory)")
    p.add_argument("--tasks", default="wood,eat,forage,night,pit")
    p.add_argument("--places", type=int, default=3)
    p.add_argument("--knowledge", default="own", help="own (the AI's channels), all, none")
    p.add_argument("--keep", action="store_true", help="one life through all tasks (else a fresh copy for each)")
    p.add_argument("--label", default="", help="a name for this variant (e.g. the change being measured)")
    p.add_argument("--memory", default=None, help="an earlier copy of the memory (exams/<run>/<name>/pristine)")
    p.add_argument("--report", action="store_true")
    p.add_argument("--own-server", action="store_true", help="exams in a world of their own (while the living sleep)")
    p.add_argument("--tick", type=int, default=40, help="the pace of the exams' own world (ticks a second)")
    a = p.parse_args()
    if a.report:
        report()
        return
    import knowledge
    import native_client

    cfg = json.load(open(os.path.join(HERE, "world.json"), encoding="utf-8"))
    if a.knowledge == "none" or (a.knowledge == "own" and a.subject == "newborn"):
        k = {c: False for c in knowledge.CHANNELS}
    elif a.knowledge == "all":
        k = {c: True for c in knowledge.CHANNELS}
    else:
        ai = next((x for x in cfg["ais"] if x["name"] == a.subject), {})
        k = knowledge.merged(cfg, ai)
    global EXAMS
    server = None
    if a.own_server:                                 # a world of its own: its places, its starts, its results
        EXAMS = os.path.join(WORLD, "exams", "own")
        os.makedirs(EXAMS, exist_ok=True)
        server = own_server(tick=a.tick)
    jar = os.path.join(FROZEN, "mod", native_client.MOD_JAR)
    if os.path.exists(jar):                          # the body of the frozen version too, not today's build
        os.environ["SYNAPSE_MOD_JAR"] = jar
    con = Console()
    con("scoreboard objectives add exam_deaths deathCount")
    spots = places(con, a.places)
    run_dir = os.path.join(EXAMS, time.strftime("%Y%m%d-%H%M%S") + "-" + a.subject)
    os.makedirs(run_dir)
    subject = Subject(a.subject, run_dir, k, fresh=not a.keep, memory=a.memory)
    log(f"exam of {a.subject} ({a.label or 'no label'}), code {commit()}, knowledge shut: "
        f"{[c for c, v in k.items() if not v] or 'none'}; places {spots}")
    client = None
    results = open(os.path.join(EXAMS, "results.jsonl"), "a", encoding="utf-8")
    try:
        for task in a.tasks.split(","):
            for i, place in enumerate(spots):
                subject.start()
                if client is None:
                    client = native_client.launch(NAME, "127.0.0.1", SERVER["port"], PORT, eyes=False,
                                                  resolution="480x270", game=native_client.game_dir(NAME),
                                                  peers=[x["name"] for x in cfg["ais"]], max_fps=30, render_distance=6,
                                                  background=True, step_ms=int(cfg.get("step_ms", 20)))
                for _ in range(600):
                    if con.online():
                        break
                    time.sleep(1)
                time.sleep(20 if subject.kind != "random" else 3)     # the brain wakes up (its memory loads)
                r = run_task(con, subject, task, place, i)
                if r is not None:
                    r["label"] = a.label
                    results.write(json.dumps(r, ensure_ascii=False) + "\n")
                    results.flush()
                    log(f"{task} @ place {i}: {'PASSED' if r['ok'] else 'no'} in {r['ticks']} ticks ({r['wall_s']} s); "
                        f"steps {r['first']}; deaths {r['deaths']}, hurt {r['hurt']}")
                if not a.keep:
                    subject.stop()
    finally:
        subject.stop()
        if client is not None:
            client.terminate()
            native_client.close(native_client.game_dir(NAME))
        results.close()
        con("clear " + NAME)
        if server is not None:                       # the exams' own world goes to sleep too
            try:
                con("stop")
                server.wait(timeout=60)
            except Exception:
                server.kill()
    report()


if __name__ == "__main__":
    main()
