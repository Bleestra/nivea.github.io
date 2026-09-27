"""
A new generation: the lives of the AIs so far go to world/archive (nothing is deleted - they can be brought back),
and the same names are born again with nothing learned but their eyes (seeing is perception, grown by itself; it
is kept if asked). Their bodies in the game go too: inventory, advancements, stats, where they were. The next
start of the world (python world.py) then finds a fresh place for them and their protected childhood
(generation.py). Run it with the world stopped (python world.py --stop).

    python new_generation.py                 # Synapse1..3, the eyes kept
    python new_generation.py --no-eyes       # the eyes from nothing too
    python new_generation.py --names Synapse2,Synapse3 --keep-generation
                                             # only these two born again, into the world's generation as it is
                                             # (its days, its peace and its monsters go on)
"""
import argparse
import json
import os
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.join(HERE, "world")
EYES = ("brain_eyes_gpu.npz", "brain_cortex_gpu.npz", "brain_recognition.json", "brain_recognition.npz")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--names", default="Synapse1,Synapse2,Synapse3")
    p.add_argument("--no-eyes", action="store_true")
    p.add_argument("--keep-generation", action="store_true", help="the world's generation goes on (only these are born again)")
    a = p.parse_args()
    names = a.names.split(",")
    archive = os.path.join(WORLD, "archive", "gen-" + time.strftime("%Y%m%d-%H%M"))
    os.makedirs(os.path.join(archive, "life"))
    users = {u["name"]: u["uuid"] for u in json.load(open(os.path.join(WORLD, "server", "usercache.json"), encoding="utf-8"))}
    for name in names:
        life = os.path.join(WORLD, "life", name)
        if os.path.exists(life):
            shutil.move(life, os.path.join(archive, "life", name))
            os.makedirs(life)
            if not a.no_eyes:
                for f in EYES:
                    src = os.path.join(archive, "life", name, f)
                    if os.path.exists(src):
                        shutil.copy(src, life)
            print(f"{name}: the life so far -> {os.path.join(archive, 'life', name)}"
                  f"{'' if a.no_eyes else '; the eyes kept'}")
        uuid = users.get(name)
        if uuid:                                             # the body in the game: bag, advancements, stats, place
            for sub, ext in (("playerdata", ".dat"), ("playerdata", ".dat_old"), ("advancements", ".json"), ("stats", ".json")):
                f = os.path.join(WORLD, "server", "world", sub, uuid + ext)
                if os.path.exists(f):
                    os.makedirs(os.path.join(archive, "server", sub), exist_ok=True)
                    shutil.move(f, os.path.join(archive, "server", sub, uuid + ext))
            print(f"{name}: the body in the game -> archive (born again at the world's spawn, with nothing)")
    gen = os.path.join(WORLD, "generation.json")
    if os.path.exists(gen) and not a.keep_generation:
        shutil.move(gen, os.path.join(archive, "generation.json"))
    print("done: the next python world.py starts the new generation")


if __name__ == "__main__":
    main()
