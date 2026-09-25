"""
Play in the Synapses' world yourself: a plain game client (no Synapse body mod - your hands are your own),
joining the running world, and operator rights (commands) once you are in.

    python play.py                     # as Bleestra
    python play.py --name Someone --no-op

To a Synapse you are a person (its caregiver): it watches what you do and copies it, and it answers you in chat.
The world runs faster than 20 ticks/s for the brains (world.json tick_rate); a plain client keeps its own pace,
so things may look hurried - `/tick rate 20` (you are an operator) slows the world while you play.
"""
import argparse
import os
import subprocess
import threading
import time

import native_client as nc

HERE = os.path.dirname(os.path.abspath(__file__))


def launch(name, host="127.0.0.1", port=25565, resolution="1280x720"):
    exe = nc.launcher()
    if not os.path.exists(os.path.join(nc.MAIN, "versions")):
        nc.prepare()                                      # Minecraft + Fabric, shared with the Synapses
    game = nc.game_dir("player-" + name)
    os.makedirs(os.path.join(game, "mods"), exist_ok=True)    # no mods: a person's own game
    opts = os.path.join(game, "options.txt")
    if not os.path.exists(opts):
        with open(opts, "w", encoding="utf-8") as f:
            f.write("lang:ru_ru\n")
    args = [exe, "--main-dir", nc.MAIN, "start", "--mc-dir", game, "--username", name,
            "--resolution", resolution, "--join-server", host, "--join-server-port", str(port), nc.VERSION]
    log = open(os.path.join(game, "launcher.log"), "a", encoding="utf-8")
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    return subprocess.Popen(args, cwd=HERE, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)


def op_when_joined(name, minutes=5):
    """Give operator rights as soon as the player is on the server (the server must know the player first)."""
    from rcon import Rcon

    pw = open(os.path.join(HERE, "world", "server", "rcon.txt")).read().strip()
    end = time.time() + minutes * 60
    while time.time() < end:
        try:
            rc = Rcon(pw)
            online = rc("list")
            if name.lower() in online.lower():
                print(rc(f"op {name}"), flush=True)
                rc.close()
                return True
            rc.close()
        except OSError:
            pass
        time.sleep(3)
    print(f"{name} did not join within {minutes} min: give the rights later with 'op {name}' (rcon)", flush=True)
    return False


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="Bleestra")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=25565)
    p.add_argument("--no-op", action="store_true")
    a = p.parse_args()
    launch(a.name, a.host, a.port)
    print(f"the game is starting for {a.name} (a minute or so)...", flush=True)
    if not a.no_op:
        op_when_joined(a.name)
