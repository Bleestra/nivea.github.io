"""
Can the brain learn the whole of Minecraft by itself, if its body has motor programs?

The same brain as in Minecraft (minecraft/brain_core.py: habits + mind + limbic system + personality)
lives in MineSim (Minecraft's rules, abstract space) and acts only through the bot's motor programs.
Milestones on the way to the Ender Dragon are counted: when each is reached for the first time, and
in what share of lives.

    python3 minesim_bench.py [steps=1000000] [seed=0] [life_dir]
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "minecraft"))
from minesim import ACTIONS, MineSim  # noqa: E402

import feel_bridge  # noqa: E402
from brain_core import Grown  # noqa: E402
from personality import Self  # noqa: E402

LADDER = ["oak_log", "crafting_table", "wooden_pickaxe", "cobblestone", "stone_pickaxe", "raw_iron", "iron_ingot",
          "iron_pickaxe", "diamond", "diamond_pickaxe", "obsidian", "flint_and_steel", "nether", "fortress",
          "blaze_rod", "ender_pearl", "ender_eye", "stronghold", "end", "dragon"]


def reached(sim, got):
    inv = set(sim.inv) | set(w for w in sim.worn)
    for k in LADDER[:12] + ["blaze_rod", "ender_pearl", "ender_eye"]:
        if k in inv:
            got.add(k)
    dim, x, z, depth = sim.where
    if dim == "the_nether":
        got.add("nether")
        if sim.scene()["kind"] == "fortress":
            got.add("fortress")
    if sim.scene()["kind"] == "stronghold":
        got.add("stronghold")
    if dim == "the_end":
        got.add("end")
    if sim.dragon_dead:
        got.add("dragon")


def run(steps=1_000_000, seed=0, life_dir=None, log_every=50_000):
    life_dir = life_dir or tempfile.mkdtemp(prefix="minesim_")
    os.makedirs(life_dir, exist_ok=True)
    sim = MineSim(seed)
    child = feel_bridge.MCChild(len(ACTIONS), seed=seed)
    feel_bridge.load(child, os.path.join(life_dir, "growing"))
    me = Self(os.path.join(life_dir, "self.json"))
    core = Grown(child, me, log=lambda *a: None)
    first, lives, got, t0 = {}, [], set(), time.time()
    m = sim.message()
    for n in range(1, steps + 1):
        a, tgt, say, o = core.decide(m)
        m = sim.step(a, tgt)
        reached(sim, got)
        for k in got:
            first.setdefault(k, n)
        if m["died"] or sim.dragon_dead:
            lives.append(got)
            got = set()
            if sim.dragon_dead:
                print(f"*** THE ENDER DRAGON IS DEAD at step {n} ***", flush=True)
                break
        if n % log_every == 0:
            recent = lives[-50:] or [got]
            print(f"{n} steps ({n / (time.time() - t0):.0f}/s), {len(lives)} lives, stage {child.limbic.stage()}, "
                  f"{len(child.mind.names)} concepts; last 50 lives reached: " +
                  " ".join(f"{k}:{sum(k in L for L in recent) * 100 // len(recent)}" for k in LADDER
                           if any(k in L for L in recent)), flush=True)
            print("   first time: " + ", ".join(f"{k}@{first[k]}" for k in LADDER if k in first), flush=True)
            feel_bridge.save(child, os.path.join(life_dir, "growing"))
            me.save()
    return first, lives, child


if __name__ == "__main__":
    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    life = sys.argv[3] if len(sys.argv) > 3 else None
    run(steps, seed, life)
