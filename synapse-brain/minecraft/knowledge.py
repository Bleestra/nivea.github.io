"""
What an AI may get ready-made, not from its own life - each a channel that can be shut (world.json "knowledge",
for everyone or for one AI). With a channel shut, nothing of it reaches the mind: an experiment "learned it by
itself" is only honest when the channels that could have told it are shut, and each run writes down which were.

  guide      the Minecraft Wiki (guide_reader): read when a step fails, when afraid in the dark, for the next step
  recipes    the game's reference (knowledge/sim_rules.json): recipes, which tool a block needs, what crafting spends
  path       the advancement tree as the next step to want, the joy of a better tool tier, of a new world
  imitation  watching people: what they use draws the eyes, doing what I saw is a joy
  speech     what people say becomes beliefs and values (the replies are still given)
  books      what I read in game books becomes beliefs
  childhood  the habits grown in MiniCraft before birth (a newborn starts with them)
  recipe_book the game's own recipe book (every player has it): opened, it shows what the unlocked recipes need

The innate stays whatever is shut: the body, the senses, pain, hunger, fear of the dark, curiosity - and the
hands still feel hard blocks (a sensation, not knowledge).
"""
import json
import os
import platform
import subprocess
import sys
import time

CHANNELS = ("guide", "recipes", "path", "imitation", "speech", "books", "childhood", "recipe_book")
HERE = os.path.dirname(os.path.abspath(__file__))


def merged(cfg, ai=None):
    """The channels for one AI: everything open, then world.json 'knowledge', then the AI's own."""
    k = {c: True for c in CHANNELS}
    k.update({c: bool(v) for c, v in (cfg.get("knowledge") or {}).items() if c in CHANNELS})
    k.update({c: bool(v) for c, v in ((ai or {}).get("knowledge") or {}).items() if c in CHANNELS})
    return k


def channels():
    """In a brain: the channels it was started with (SYNAPSE_KNOWLEDGE, set by world.py; all open without it)."""
    k = {c: True for c in CHANNELS}
    try:
        k.update({c: bool(v) for c, v in json.loads(os.environ.get("SYNAPSE_KNOWLEDGE", "{}")).items() if c in CHANNELS})
    except ValueError:
        pass
    return k


def is_open(channel):
    return channels().get(channel, True)


def _commit():
    try:
        root = os.path.dirname(HERE)
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=root, capture_output=True, text=True,
                               timeout=20).stdout.strip()
        return {"commit": rev or None, "uncommitted_changes": bool(dirty)}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None}


def manifest(life_dir, **what):
    """Write down how this run of a life was started: the code, the channels of ready knowledge, the switches,
    the world, the machine. runs/<time>.json next to the life; returns its path."""
    import numpy as np

    env = {k: v for k, v in os.environ.items() if k in ("CONTINGENCY", "RELATIVE", "SECONDARY", "CORTICAL_DA",
                                                         "HUNGER_CTX", "MIN_DESIRE_MC", "EPISODIC", "FORCE_FILE",
                                                         "SYNAPSE_DEVICE")}
    try:
        world = json.loads(os.environ.get("SYNAPSE_WORLD", "{}"))
    except ValueError:
        world = {}
    ram = None
    try:
        import psutil

        ram = round(psutil.virtual_memory().total / 2 ** 30, 1)
    except ImportError:
        pass
    doc = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), **_commit(), "knowledge": channels(), "switches": env,
           "world": world, **what,
           "machine": {"python": sys.version.split()[0], "numpy": np.__version__, "os": platform.platform(),
                       "cpus": os.cpu_count(), "ram_gb": ram}}
    d = os.path.join(life_dir, "runs")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, time.strftime("%Y%m%d-%H%M%S") + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return path
