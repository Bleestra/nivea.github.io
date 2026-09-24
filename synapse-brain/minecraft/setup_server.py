"""
Download and configure an official Minecraft Java server for SynapseBrain (offline mode, so the bot
can join; spawn protection off, so it may dig near spawn).

    python3 setup_server.py --accept-eula [--version 1.20.4] [--dir server]

Running the server means accepting Mojang's EULA (https://aka.ms/MinecraftEULA) - pass --accept-eula
only if you do. Then start it with:  java -Xmx3G -jar server/server.jar nogui
"""
import argparse
import json
import os
import urllib.request

p = argparse.ArgumentParser()
p.add_argument("--version", default="1.20.4")
p.add_argument("--dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "server"))
p.add_argument("--accept-eula", action="store_true")
p.add_argument("--difficulty", default="easy", help="peaceful / easy / normal / hard")
a = p.parse_args()
if not a.accept_eula:
    raise SystemExit("Read https://aka.ms/MinecraftEULA and re-run with --accept-eula if you accept it.")
os.makedirs(a.dir, exist_ok=True)
get = lambda u: json.load(urllib.request.urlopen(u))
man = get("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
ver = get(next(v["url"] for v in man["versions"] if v["id"] == a.version))
jar = os.path.join(a.dir, "server.jar")
if not os.path.exists(jar):
    print("downloading server", a.version)
    urllib.request.urlretrieve(ver["downloads"]["server"]["url"], jar)
open(os.path.join(a.dir, "eula.txt"), "w").write("eula=true\n")
open(os.path.join(a.dir, "server.properties"), "w").write(
    f"online-mode=false\nspawn-protection=0\ndifficulty={a.difficulty}\ngamemode=survival\nmotd=SynapseBrain\n")
print(f"ready: cd {a.dir} && java -Xmx3G -jar server.jar nogui   (then: op SynapseBrain in the server console)")
