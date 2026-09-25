"""
Start Synapse: mind (brain_server.py) + body, optionally with voice and eyes.

    python3 run_synapse.py --host localhost --port 25565 [--voice] [--eyes] [--name Synapse]
    python3 run_synapse.py --body mod [--eyes]      # the body is the real game client (../fabric-mod)

Bodies: "bot" - the Mineflayer bot (bot.js, Minecraft 1.20.4, no window); "mod" - the real Minecraft
1.21.4 client with the Synapse Body mod: a game window you can watch, eyes from the game's own renderer
(with a GPU they feed the large visual cortex), every player action. The server must match the version.

First run: grows the brain in MiniCraft ("childhood", about a minute) and, with --voice, trains the
voice (about 10 minutes, downloads the Minecraft Wiki from Hugging Face). Everything the bot learns
is kept in minecraft/life/ (synapses, self.json, diary) and carries over between runs.
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
p = argparse.ArgumentParser()
p.add_argument("--host", default="localhost")
p.add_argument("--port", default="25565")
p.add_argument("--body", default="bot", choices=["bot", "mod"],
               help="bot: Mineflayer (bot.js); mod: the real game client with the Synapse Body mod")
p.add_argument("--version", default=None, help="game version (default 1.20.4 for bot, 1.21.4 for mod)")
p.add_argument("--name", default=None, help="player name (default SynapseBrain for bot, Synapse for mod)")
p.add_argument("--voice", action="store_true", help="answer in chat (trains the voice on first use)")
p.add_argument("--eyes", action="store_true", help="see the game through a first-person 3D view")
p.add_argument("--blind", action="store_true", help="with --eyes: act from vision only (the senses only teach)")
p.add_argument("--no-feelings", action="store_true", help="the mind without the limbic system (previous version)")
p.add_argument("--brain-port", default="5555")
a = p.parse_args()
a.version = a.version or ("1.21.4" if a.body == "mod" else "1.20.4")
a.name = a.name or ("Synapse" if a.body == "mod" else "SynapseBrain")
if a.body == "mod" and a.version != "1.21.4":
    raise SystemExit("the Synapse Body mod is built for Minecraft 1.21.4")

life = os.path.join(HERE, "life")
os.makedirs(life, exist_ok=True)
brain = os.path.join(life, "brain.npz")
py = sys.executable
if not os.path.exists(brain):
    print("childhood in MiniCraft...", flush=True)
    subprocess.run([py, os.path.join(HERE, "pretrain.py"), "150000", brain], check=True)
if a.voice and not os.path.exists(os.path.join(HERE, "voice", "meta.json")):
    print("growing the voice (reads the Minecraft Wiki, ~10 min)...", flush=True)
    subprocess.run([py, os.path.join(HERE, "train_voice.py")], check=True)
if a.body == "bot" and not os.path.exists(os.path.join(HERE, "node_modules")):
    subprocess.run("npm install", shell=True, cwd=HERE, check=True)

mind = [py, os.path.join(HERE, "brain_server.py"), "--port", a.brain_port, "--load", brain,
        "--self", os.path.join(life, "self.json")]
mind += ["--mind", os.path.join(life, "mind.npz")] if a.no_feelings else ["--limbic", os.path.join(life, "growing")]
body = ["node", os.path.join(HERE, "bot.js"), "--host", a.host, "--port", a.port, "--version", a.version,
        "--name", a.name, "--brain", a.brain_port]
if a.voice:
    mind += ["--voice", os.path.join(HERE, "voice")]
if a.eyes and a.body == "mod":                # the mod sends the game's own picture with every moment
    mind += ["--see"] + (["--blind"] if a.blind else [])
elif a.eyes:
    mind += ["--eyes", "http://localhost:3007", "--see"] + (["--blind"] if a.blind else [])
    body += ["--viewer", "3007"]


def start_body():
    if a.body == "mod":
        import native_client

        return native_client.launch(a.name, a.host, int(a.port), int(a.brain_port), a.eyes)
    return subprocess.Popen(body, cwd=HERE)


m = subprocess.Popen(mind, cwd=HERE)
import socket  # noqa: E402

for _ in range(300):  # the mind needs a moment to wake up (loading the voice takes longest)
    try:
        socket.create_connection(("127.0.0.1", int(a.brain_port)), timeout=1).close()
        break
    except OSError:
        if m.poll() is not None:
            raise SystemExit("the brain server stopped - see the messages above")
        time.sleep(1)
print("Synapse is alive. Ctrl+C to let it sleep (its memory is saved). Progress: life/progress.csv", flush=True)
try:
    while True:                     # live on: if the body falls off the server, it comes back
        b = start_body()
        b.wait()
        if m.poll() is not None:
            print("the mind stopped - restarting it", flush=True)
            m = subprocess.Popen(mind, cwd=HERE)
            time.sleep(40)
        print("the body disconnected - reconnecting in 10 s", flush=True)
        time.sleep(10)
except KeyboardInterrupt:
    pass
finally:
    b.terminate()
    m.terminate()
    m.wait(timeout=60)
