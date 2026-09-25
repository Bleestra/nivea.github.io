"""
One world, several Synapses: a Minecraft 1.21.4 server, a brain and a real game client for each AI, and the
dashboard (http://127.0.0.1:8765) to see what each decides, feels, sees and achieves - and who does better.

    python world.py --accept-eula          # the first time: downloads the server (Mojang EULA: https://aka.ms/MinecraftEULA)
    python world.py                        # then: as many AIs as this PC can hold (world.json: max_instances)
    python world.py --instances 2          # or exactly this many
    python world.py --dashboard-only       # only the dashboard (the AIs' lives stay on disk)
    python world.py --stop                 # from another window: everyone saves and falls asleep

The first AI plays in the big window you watch; the others play in small windows in the background (do not
minimise them: a minimised window draws nothing and its AI goes blind). Ctrl+C: every brain saves what it
learned and falls asleep, the clients and the server stop. Everything lives in minecraft/world/:
server/ (the world), life/<name>/ (each AI: synapses, feelings, memory, eyes, diary, telemetry).
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.join(HERE, "world")
PY = sys.executable
GROUP = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0   # Ctrl+C reaches only this script
CFG_VISION = {}                                                          # world.json "vision"
PER_AI = {"ram_gb": 5.0, "vram_gb": 1.2, "threads": 3}   # a brain with eyes (~2.4 GB, measured) + a game client (~2.5 GB)


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


# ---------------------------------------------------------------- the PC
def resources():
    """Free RAM, CPU threads and free video memory now."""
    ram_free = ram_total = None
    if os.name == "nt":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                        ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ave", ctypes.c_ulonglong)]
        ms = MS()
        ms.len = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        ram_free, ram_total = ms.avail / 2 ** 30, ms.total / 2 ** 30
    elif os.path.exists("/proc/meminfo"):
        info = dict(line.split(":", 1) for line in open("/proc/meminfo"))
        ram_free = int(info["MemAvailable"].split()[0]) / 2 ** 20
        ram_total = int(info["MemTotal"].split()[0]) / 2 ** 20
    vram = None
    try:
        import torch

        if torch.cuda.is_available():
            vram = torch.cuda.mem_get_info()[0] / 2 ** 30
    except Exception:
        pass
    return {"ram_free": ram_free, "ram_total": ram_total, "threads": os.cpu_count() or 4, "vram_free": vram}


def how_many(cfg, forced=None):
    want = min(int(cfg.get("max_instances", 4)), len(cfg["ais"]))
    if forced:
        return min(forced, len(cfg["ais"])), "задано вручную"
    r = resources()
    limits = {"max_instances": want}
    if r["ram_free"] is not None:
        limits["RAM"] = int((r["ram_free"] - cfg["server"].get("memory_gb", 4) - 1.5) // PER_AI["ram_gb"])
    if r["vram_free"] is not None:
        limits["VRAM"] = int(r["vram_free"] // PER_AI["vram_gb"])
    limits["CPU"] = int(r["threads"] // PER_AI["threads"])
    n = max(1, min(limits.values()))
    why = ", ".join(f"{k} {v}" for k, v in limits.items())
    ram = f"{r['ram_free']:.1f} of {r['ram_total']:.1f} GB RAM free" if r["ram_free"] else "RAM unknown"
    vram = f"{r['vram_free']:.1f} GB VRAM free" if r["vram_free"] else "no GPU"
    return n, f"{ram}, {vram}, {r['threads']} CPU threads -> limits: {why}"


# ---------------------------------------------------------------- the server
def port_open(port, host="127.0.0.1"):
    try:
        socket.create_connection((host, port), timeout=0.5).close()
        return True
    except OSError:
        return False


def wait_port(port, seconds, proc=None):
    for _ in range(int(seconds * 2)):
        if port_open(port):
            return True
        if proc is not None and proc.poll() is not None:
            return False
        time.sleep(0.5)
    return False


def prepare_server(cfg, accept_eula):
    s = cfg["server"]
    d = os.path.join(WORLD, "server")
    os.makedirs(d, exist_ok=True)
    eula = os.path.join(d, "eula.txt")
    if not (os.path.exists(eula) and "eula=true" in open(eula).read()):
        if not accept_eula:
            raise SystemExit("The server needs Mojang's EULA: read https://aka.ms/MinecraftEULA and run again with --accept-eula")
        open(eula, "w").write("eula=true\n")
    jar = os.path.join(d, "server.jar")
    if not os.path.exists(jar):
        get = lambda u: json.load(urllib.request.urlopen(u))
        man = get("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
        ver = get(next(v["url"] for v in man["versions"] if v["id"] == s["version"]))
        log("downloading the Minecraft server", s["version"])
        urllib.request.urlretrieve(ver["downloads"]["server"]["url"], jar)
    props = {"online-mode": "false", "spawn-protection": "0", "difficulty": s.get("difficulty", "easy"),
             "gamemode": "survival", "motd": "Synapse world", "server-port": str(s.get("port", 25565)),
             "max-players": "12", "view-distance": str(s.get("view_distance", 8)), "enforce-secure-profile": "false"}
    if s.get("seed"):
        props["level-seed"] = str(s["seed"])
    # the experimenter's console (selftest.py, experiments): RCON with a random password kept in server/rcon.txt
    pw_path = os.path.join(d, "rcon.txt")
    if not os.path.exists(pw_path):
        import secrets

        open(pw_path, "w").write(secrets.token_hex(12))
    props.update({"enable-rcon": "true", "rcon.port": "25575", "rcon.password": open(pw_path).read().strip(),
                  "broadcast-rcon-to-ops": "false"})
    path = os.path.join(d, "server.properties")
    old = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if "=" in line and not line.startswith("#"):
                k, v = line.rstrip("\n").split("=", 1)
                old[k] = v
    old.update(props)
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(f"{k}={v}\n" for k, v in old.items()))
    return d


def start_server(cfg, d):
    port = cfg["server"].get("port", 25565)
    if port_open(port):
        log(f"a server is already running on port {port}: using it")
        return None
    mem = cfg["server"].get("memory_gb", 4)
    out = open(os.path.join(d, "server.log"), "a", encoding="utf-8")
    p = subprocess.Popen(["java", f"-Xmx{mem}G", "-Xms1G", "-jar", "server.jar", "nogui"], cwd=d, stdin=subprocess.PIPE,
                         stdout=out, stderr=subprocess.STDOUT, creationflags=GROUP)
    log("starting the server (the first time it generates the world: a minute or two)...")
    if not wait_port(port, 300, p):
        raise SystemExit(f"the server did not start - see {os.path.join(d, 'server.log')}")
    log(f"server ready on port {port}")
    return p


def adapt_pace(cfg, ais, current):
    """As fast as the brains can keep up: while a brain thinks, the world goes on, so the world's pace is set so that
    the slowest brain's thinking (eyes + senses + brain + pause) lasts at most REACTION ticks - about a person's
    reaction time. A faster brain lets the world run faster. Returns the new tick rate (or the current one)."""
    REACTION = 5
    worst = 0.0
    for ai in ais:
        try:
            live = json.load(open(os.path.join(life_of(ai["name"]), "telemetry", "live.json"), encoding="utf-8"))
        except Exception:
            continue
        if not live.get("online") or live.get("step", 0) < 100:  # a brain just woken is still warming up
            continue
        p = live.get("pace", {})
        think = sum(float(p.get(k, 0) or 0) for k in ("eyes_ms", "senses_ms", "brain_ms", "wait_ms"))
        worst = max(worst, think)
    if worst <= 0:
        return current
    top = int(cfg["server"].get("max_tick_rate", cfg["server"].get("tick_rate", 20)))
    rate = int(max(20, min(top, REACTION * 1000.0 / worst)))
    if abs(rate - current) < max(5, current * 0.1):
        return current
    try:
        from rcon import Rcon

        rc = Rcon(open(os.path.join(WORLD, "server", "rcon.txt")).read().strip())
        rc(f"tick rate {rate}")
        rc.close()
        log(f"world pace {current} -> {rate} ticks/s (the slowest brain thinks {worst:.0f} ms = {worst * rate / 1000:.1f} ticks)")
        return rate
    except Exception as e:
        log("could not change the world's pace:", e)
        return current


def speed_up(cfg):
    """The world's pace: /tick rate (Minecraft 1.20.3+; the clients follow it). The brains learn per moment, not per
    second, so a faster world only means more life per hour; their reaction stays a few ticks, like a person's."""
    rate = int(cfg["server"].get("tick_rate", 20))
    rules = cfg["server"].get("gamerules", {})
    if rate == 20 and not rules:
        return
    try:
        from rcon import Rcon

        pw = open(os.path.join(WORLD, "server", "rcon.txt")).read().strip()
        rc = None
        for _ in range(30):
            try:
                rc = Rcon(pw)
                break
            except OSError:
                time.sleep(2)
        if rate != 20:
            log("world pace:", rc(f"tick rate {rate}") or f"{rate} ticks/s")
        for k, v in rules.items():                           # the world's rules (world.json "gamerules")
            log("rule:", rc(f"gamerule {k} {str(v).lower()}"))
        rc.close()
    except Exception as e:
        log("could not change the world's pace:", e)


# ---------------------------------------------------------------- the AIs
def life_of(name):
    return os.path.join(WORLD, "life", name)


def childhood():
    """The same childhood for everyone (MiniCraft, ~1 min, once): lives differ from here on."""
    c = os.path.join(WORLD, "life", "_childhood.npz")
    if not os.path.exists(c):
        os.makedirs(os.path.dirname(c), exist_ok=True)
        log("childhood in MiniCraft (once for the whole world, about a minute)...")
        subprocess.run([PY, os.path.join(HERE, "pretrain.py"), "150000", c], check=True, cwd=HERE)
    return c


def keep_in_budget(ais):
    """Every 10 minutes: how much of the budget is used. When little room is left, the logs keep only their
    newest part - never the memories (the minds stop growing by themselves when there is no room)."""
    import limits

    st = limits.status()
    if st["room_gb"] >= 2:
        return
    freed = 0
    for ai in ais:
        d = life_of(ai["name"])
        for f in ("brain.log", os.path.join("telemetry", "events.jsonl"), os.path.join("telemetry", "series.jsonl")):
            freed += limits.trim(os.path.join(d, f))
    log(f"disk budget: the project takes {st['project_gb']} of {st['budget_gb']} GB ({st['drive_free_gb']} GB free "
        f"on the drive); old log lines let go: {freed / 2 ** 20:.0f} MB")


def brain_cmd(ai, port):
    d = life_of(ai["name"])
    cmd = [PY, "-u", os.path.join(HERE, "brain_server.py"), "--port", str(port), "--load", os.path.join(d, "brain.npz"),
           "--self", os.path.join(d, "self.json"), "--limbic", os.path.join(d, "growing"), "--name", ai["name"],
           "--telemetry", os.path.join(d, "telemetry")]
    if ai.get("eyes", True):
        v = CFG_VISION
        cmd += ["--see", "--senses", ai.get("senses", "grow"), "--retina", str(v.get("picture", 256)),
                "--neurons", str(v.get("neurons", 131072)), "--zones", str(v.get("zones", 8))]
    if ai.get("voice") and os.path.exists(os.path.join(HERE, "voice", "meta.json")):
        cmd += ["--voice", os.path.join(HERE, "voice")]
    return cmd


def start_brain(ai, port):
    d = life_of(ai["name"])
    os.makedirs(d, exist_ok=True)
    stop = os.path.join(d, "STOP")
    if os.path.exists(stop):
        os.remove(stop)
    if not os.path.exists(os.path.join(d, "brain.npz")):
        shutil.copy(childhood(), os.path.join(d, "brain.npz"))
    out = open(os.path.join(d, "brain.log"), "a", encoding="utf-8")
    return subprocess.Popen(brain_cmd(ai, port), cwd=HERE, stdout=out, stderr=subprocess.STDOUT, creationflags=GROUP,
                            env=dict(os.environ, PYTHONIOENCODING="utf-8"))


def start_client(cfg, ai, i, port, names):
    import native_client

    main = i == 0
    return native_client.launch(
        ai["name"], "127.0.0.1", cfg["server"].get("port", 25565), port, ai.get("eyes", True),
        resolution=cfg.get("main_window", "1280x720") if main else cfg.get("background_window", "480x270"),
        game=native_client.game_dir(ai["name"]), peers=names,
        max_fps=60 if main else 30, render_distance=8 if main else 6, background=not main,
        step_ms=int(cfg.get("step_ms", 20)), frame=int(CFG_VISION.get("picture", 256)), zones=int(CFG_VISION.get("zones", 8)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=os.path.join(HERE, "world.json"))
    p.add_argument("--instances", type=int, default=0)
    p.add_argument("--accept-eula", action="store_true")
    p.add_argument("--no-clients", action="store_true", help="server + brains + dashboard only (join the bodies yourself)")
    p.add_argument("--dashboard-only", action="store_true")
    p.add_argument("--stop", action="store_true", help="ask a running world to save and fall asleep (from another window)")
    a = p.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    CFG_VISION.update(cfg.get("vision", {}))
    os.makedirs(WORLD, exist_ok=True)
    stop_flag = os.path.join(WORLD, "STOP")
    if a.stop:
        open(stop_flag, "w").close()
        print("asked the world to fall asleep: the brains save, then the clients and the server stop")
        return
    if os.path.exists(stop_flag):
        os.remove(stop_flag)
    dash_port = cfg.get("dashboard_port", 8765)
    procs = {}

    def start_dashboard():
        out = open(os.path.join(WORLD, "dashboard.log"), "a", encoding="utf-8")
        procs["dashboard"] = subprocess.Popen([PY, os.path.join(HERE, "dashboard.py"), "--world", WORLD, "--port", str(dash_port),
                                               "--server-port", str(cfg["server"].get("port", 25565))],
                                              cwd=HERE, stdout=out, stderr=subprocess.STDOUT, creationflags=GROUP)

    if a.dashboard_only:
        start_dashboard()
        log(f"dashboard: http://127.0.0.1:{dash_port}  (Ctrl+C to stop)")
        webbrowser.open(f"http://127.0.0.1:{dash_port}")
        try:
            procs["dashboard"].wait()
        except KeyboardInterrupt:
            procs["dashboard"].terminate()
        return

    fixed = a.instances or (cfg["instances"] if isinstance(cfg.get("instances"), int) else 0)
    n, why = how_many(cfg, fixed)
    ais = cfg["ais"][:n]
    log(f"{n} AI in this world: {', '.join(x['name'] for x in ais)}  ({why})")
    json.dump({**cfg, "ais": ais}, open(os.path.join(WORLD, "world.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    server_dir = prepare_server(cfg, a.accept_eula)
    procs["server"] = start_server(cfg, server_dir)
    speed_up(cfg)
    if not os.path.exists(os.path.join(HERE, "knowledge", "progress.json")):
        subprocess.run([PY, os.path.join(HERE, "build_progress.py"), os.path.join(server_dir, "server.jar")], cwd=HERE)
    if not os.path.exists(os.path.join(HERE, "guide", "pages.jsonl")):          # the guide, read while they live
        log("downloading the guide (the Minecraft Wiki) in the background...")
        procs["guide"] = subprocess.Popen([PY, os.path.join(HERE, "guide.py")], cwd=HERE, creationflags=GROUP,
                                          stdout=open(os.path.join(WORLD, "guide.log"), "a"), stderr=subprocess.STDOUT)
    childhood()
    ports = {ai["name"]: 5555 + i for i, ai in enumerate(ais)}
    for ai in ais:
        procs["brain:" + ai["name"]] = start_brain(ai, ports[ai["name"]])
    for ai in ais:
        if not wait_port(ports[ai["name"]], 240, procs["brain:" + ai["name"]]):
            log(f"the brain of {ai['name']} did not wake up - see {os.path.join(life_of(ai['name']), 'brain.log')}")
        else:
            log(f"{ai['name']}: brain awake on port {ports[ai['name']]}")
    start_dashboard()
    log(f"dashboard: http://127.0.0.1:{dash_port}")
    webbrowser.open(f"http://127.0.0.1:{dash_port}")
    names = [x["name"] for x in ais]
    if not a.no_clients:
        for i, ai in enumerate(ais):
            log(f"{ai['name']}: starting the game client ({'the big window' if i == 0 else 'in the background'})")
            procs["client:" + ai["name"]] = start_client(cfg, ai, i, ports[ai["name"]], names)
            time.sleep(25 if i == 0 else 15)             # one after another: loading a client is heavy
    else:
        log("no clients: start bodies yourself (python native_client.py --name <AI> --brain-port <port> --eyes)")
    log("the world lives. Ctrl+C: everyone saves and falls asleep.")

    restarts = {}
    pace, t_pace = int(cfg["server"].get("tick_rate", 20)), time.time()
    t_disk = 0.0
    try:
        while True:
            time.sleep(5)
            if cfg["server"].get("max_tick_rate") and time.time() - t_pace > 30:
                t_pace = time.time()
                pace = adapt_pace(cfg, ais, pace)
            if time.time() - t_disk > 600:                  # the project's disk budget (world.json "limits")
                t_disk = time.time()
                keep_in_budget(ais)
            if os.path.exists(stop_flag):                   # python world.py --stop
                os.remove(stop_flag)
                log("asked to fall asleep: the brains save what they learned...")
                break
            if procs.get("server") is not None and procs["server"].poll() is not None:
                log("the server stopped - starting it again")
                procs["server"] = start_server(cfg, server_dir)
                speed_up(cfg)
            for i, ai in enumerate(ais):
                k = "brain:" + ai["name"]
                if procs[k].poll() is not None:
                    log(f"{ai['name']}: the brain stopped - waking it again")
                    procs[k] = start_brain(ai, ports[ai["name"]])
                c = "client:" + ai["name"]
                if c in procs and procs[c].poll() is not None and time.time() - restarts.get(c, 0) > 30:
                    restarts[c] = time.time()
                    log(f"{ai['name']}: the game client closed - starting it again")
                    procs[c] = start_client(cfg, ai, i, ports[ai["name"]], names)
            if procs["dashboard"].poll() is not None:
                start_dashboard()
    except KeyboardInterrupt:
        log("falling asleep: the brains save what they learned...")
    finally:
        for ai in ais:                                       # a brain saves and exits when it finds STOP
            open(os.path.join(life_of(ai["name"]), "STOP"), "w").close()
        deadline = time.time() + 90
        for ai in ais:
            b = procs.get("brain:" + ai["name"])
            while b is not None and b.poll() is None and time.time() < deadline:
                time.sleep(0.5)
            if b is not None and b.poll() is None:
                b.kill()
        import native_client

        for k, pr in procs.items():
            if k.startswith("client:"):
                pr.terminate()
                native_client.close(native_client.game_dir(k.split(":", 1)[1]))   # the game window too
        srv = procs.get("server")
        if srv is not None and srv.poll() is None:
            try:
                srv.stdin.write(b"stop\n")
                srv.stdin.flush()
                srv.wait(timeout=60)
            except Exception:
                srv.kill()
        if procs.get("dashboard") is not None:
            procs["dashboard"].terminate()
        log("everyone is asleep; the lives are in", os.path.join(WORLD, "life"))


if __name__ == "__main__":
    main()
