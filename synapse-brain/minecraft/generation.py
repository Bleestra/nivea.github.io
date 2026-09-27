"""
A generation of AIs: born together, in a place of the world no one has touched, with a protected childhood.

  the place  the world's spawn moves to dry land in a forest near world.json "generation" "spawn_near" (fresh
             trees, no pits and chests of those before);
  childhood  the first "safe_days" game days no monsters come (the game rule doMobSpawning, and those that are
             there are taken away). Hunger, water, falls and the innate fear of the dark stay: food has to be found,
             and whether they hide from the dark with nothing in it is their own doing. Then the monsters come.

The generation is written down in world/generation.json (when it was born, which day of the world, where).
"""
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.join(HERE, "world")
PATH = os.path.join(WORLD, "generation.json")
HOSTILE = ("zombie", "husk", "drowned", "zombie_villager", "skeleton", "stray", "bogged", "creeper", "spider",
           "cave_spider", "witch", "slime", "phantom", "enderman", "silverfish", "pillager", "vindicator", "evoker",
           "ravager", "vex", "breeze", "guardian", "elder_guardian")


def _rcon():
    from rcon import Rcon

    pw = open(os.path.join(WORLD, "server", "rcon.txt")).read().strip()
    for _ in range(30):
        try:
            return Rcon(pw)
        except OSError:
            time.sleep(2)
    raise OSError("no RCON")


def _ticks(rc):
    """The world's own clock (game ticks since it began): /time set does not turn it back, as it does the day."""
    m = re.findall(r"(\d+)", rc("time query gametime"))
    return int(m[-1]) if m else 0


def _dry_spot(rc, x, z, log):
    """Dry ground in a forest near x z: a probe is dropped onto the surface (the game finds it) and checked."""
    m = re.findall(r"\[(-?\d+), [^,]+, (-?\d+)\]", rc(f"execute positioned {x} 64 {z} run locate biome minecraft:forest"))
    if m:
        x, z = int(m[0][0]), int(m[0][1])
    rc(f"forceload add {x - 48} {z - 48} {x + 48} {z + 48}")
    time.sleep(3)
    spot = None
    for attempt in range(12):
        rc("kill @e[tag=gen_probe]")
        rc(f'summon armor_stand {x} 200 {z} {{Tags:["gen_probe"],Invisible:1b,Marker:1b}}')
        rc(f"spreadplayers {x} {z} 0 {12 + 6 * attempt} false @e[tag=gen_probe,limit=1]")
        p = re.findall(r"(-?\d+\.?\d*)d", rc("data get entity @e[tag=gen_probe,limit=1] Pos"))
        if len(p) < 3:
            continue
        sx, sy, sz = (int(float(v) // 1) for v in p[:3])
        wet = any("passed" in rc(f"execute if block {sx} {sy + dy} {sz} minecraft:water") for dy in (-1, 0, 1))
        if not wet and sy >= 62:
            spot = (sx, sy, sz)
            break
    rc("kill @e[tag=gen_probe]")
    rc(f"forceload remove {x - 48} {z - 48} {x + 48} {z + 48}")
    if spot is None:
        log(f"generation: no dry forest ground near {x} {z}")
    return spot


def load():
    return json.load(open(PATH, encoding="utf-8")) if os.path.exists(PATH) else None


def begin(cfg, log):
    """At the world's start: a new generation, if none is written down yet - the place and the day it was born."""
    gen = load()
    if gen is not None:
        return gen
    g = cfg.get("generation", {})
    rc = _rcon()
    try:
        x, z = g.get("spawn_near", [-3000, -3000])
        spot = _dry_spot(rc, x, z, log)
        if spot is not None:
            log("generation: the world's spawn:", rc("setworldspawn {} {} {}".format(*spot)))
            rc("gamerule spawnRadius 4")
        gen = {"born": time.strftime("%Y-%m-%d %H:%M"), "born_tick": _ticks(rc), "safe_days": int(g.get("safe_days", 0)),
               "spawn": list(spot) if spot else None, "monsters": g.get("safe_days", 0) <= 0}
        rc("time set day")
        json.dump(gen, open(PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log(f"generation born at tick {gen['born_tick']} of the world at {gen['spawn']}; "
            f"{gen['safe_days']} days without monsters")
    finally:
        rc.close()
    tick(log)
    return gen


def tick(log):
    """Every minute: still the childhood (no monsters), or the day they come."""
    gen = load()
    if gen is None:
        return
    try:
        rc = _rcon()
    except OSError:
        return
    try:
        day = (_ticks(rc) - gen["born_tick"]) // 24000       # the days of their life
        safe = day < gen.get("safe_days", 0)
        if safe:
            rc("gamerule doMobSpawning false")
            for kind in HOSTILE:                             # (from before, or from spawners)
                rc(f"kill @e[type=minecraft:{kind}]")
        elif not gen.get("monsters"):
            log("generation:", rc("gamerule doMobSpawning true"),
                f"- day {day} of their life: the childhood is over, the monsters come")
            gen["monsters"] = True
            gen["monsters_day"] = day
            json.dump(gen, open(PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    finally:
        rc.close()
