"""
MineSim: Minecraft's own rules in an abstract world, played through the real bot's motor programs.

Why: in Minecraft the body now has motor programs (approach what I see, mine it, craft what I want,
go home, explore...), so the brain has to learn WHAT to do, not how to walk. The real game runs at
a few decisions per second; to see whether the brain can learn the whole game - up to the Ender
Dragon - it needs millions of moments. Here they take hours.

The rules come from the game's data (knowledge/sim_rules.json, exported by export_sim_data.js):
every recipe, what each block drops and which tool it needs, food values, what mobs drop. The
world is abstract: a scene is what the bot can see from where it stands (blocks and creatures by
name); moving (explore / dig down / portals) brings a new scene. The simulator sends the brain
EXACTLY the messages the real body sends (same fields, same concept names) and accepts the same
40 motor commands with the same attention targets - it is the same brain, in the same code
(minecraft/brain_core.py), that plays Minecraft. Nothing here tells the brain what to do.

Simplifications (honest list): no 3D space inside a scene; mobs fight by chance per step; smelting
is instant; a portal frame is one motor program ('place_frame', 10 obsidian); the dragon fight is
abstract (crystals on pillars heal it; pillar up or shoot them; hit the dragon when it perches).
"""
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = json.load(open(os.path.join(HERE, "..", "minecraft", "knowledge", "sim_rules.json")))
_WOODS = ("spruce_", "birch_", "jungle_", "acacia_", "dark_oak_", "mangrove_", "cherry_", "bamboo_", "crimson_", "warped_")
RULES["recipes"] = {k: v for k, v in RULES["recipes"].items() if not k.startswith(_WOODS)}   # this world grows only oaks
ADV = json.load(open(os.path.join(HERE, "..", "minecraft", "knowledge", "advancements.json")))
ACTIONS = ['forward', 'turn_left', 'turn_right', 'dig_front', 'wait', 'craft_new', 'eat', 'back', 'strafe_left',
           'strafe_right', 'jump', 'toggle_sprint', 'toggle_sneak', 'look_up', 'look_down', 'attack', 'use_item',
           'dig_down', 'equip_armor', 'equip_weapon', 'equip_tool', 'place_block', 'craft_gear', 'smelt', 'sleep',
           'drop_junk', 'pillar_up', 'dig_up', 'fish', 'interact', 'store', 'take', 'place_chest', 'trade', 'read',
           'approach', 'mine_target', 'craft_target', 'goto_place', 'explore', 'place_frame']
A = {n: i for i, n in enumerate(ACTIONS)}
# exhaustion per moment (~1 s) of each kind of effort (Minecraft: walking .01/m, sprint-jump .2, mining .005/block,
# attacking .1; 4.0 exhaustion = 1 food point); a whole chunk crossed = ~16 m
EXHAUST = {"explore": 0.2, "goto_place": 0.2, "forward": 0.04, "back": 0.04, "strafe_left": 0.04, "strafe_right": 0.04,
           "approach": 0.06, "jump": 0.05, "attack": 0.1, "mine_target": 0.03, "dig_front": 0.03, "dig_down": 0.1,
           "dig_up": 0.1, "pillar_up": 0.1, "toggle_sprint": 0.05}
SHELTER = 8                                       # placed blocks that make walls and a roof around one
STEP_OUT = {"forward", "back", "strafe_left", "strafe_right", "jump", "approach", "explore", "attack", "dig_down",
            "dig_up", "pillar_up", "fish", "trade", "interact"}
DAY = 1200                                        # moments per Minecraft day (~1 s each)
NIGHT = (700, 1200)

# ---------------------------------------------------------------- what a place looks like
# (name, probability to be there, (min, max) how many)
BIOMES = {
    "plains": [("grass_block", 1, (8, 20)), ("dirt", 1, (3, 8)), ("oak_log", .45, (2, 6)), ("oak_leaves", .45, (3, 8)),
               ("stone", .3, (2, 6)), ("gravel", .2, (1, 4)), ("sand", .2, (2, 6)), ("water", .35, (2, 8)),
               ("sugar_cane", .15, (1, 3)), ("cow", .4, (1, 3)), ("pig", .3, (1, 3)), ("sheep", .3, (1, 3)),
               ("chicken", .3, (1, 3)), ("obsidian", .03, (4, 7))],          # the rare ruined portal
    "forest": [("grass_block", 1, (5, 12)), ("dirt", 1, (2, 6)), ("oak_log", .95, (4, 10)), ("oak_leaves", .95, (6, 14)),
               ("stone", .2, (1, 4)), ("cow", .25, (1, 2)), ("pig", .2, (1, 2)), ("chicken", .25, (1, 2)),
               ("apple", 0, (0, 0))],
    "hills": [("stone", 1, (8, 20)), ("coal_ore", .6, (1, 4)), ("iron_ore", .3, (1, 3)), ("gravel", .3, (1, 4)),
              ("grass_block", .7, (2, 8)), ("dirt", .7, (2, 5)), ("oak_log", .3, (1, 3)), ("sheep", .3, (1, 3)),
              ("emerald_ore", .03, (1, 1))],
    "desert": [("sand", 1, (10, 20)), ("sandstone", .8, (3, 8)), ("cactus", .5, (1, 3)), ("dead_bush", .4, (1, 2))],
    "cave": [("stone", 1, (10, 20)), ("coal_ore", .6, (1, 5)), ("iron_ore", .55, (1, 4)), ("copper_ore", .4, (1, 4)),
             ("gravel", .3, (1, 4)), ("dirt", .2, (1, 3)), ("water", .2, (1, 3)), ("lava", .2, (1, 3)),
             ("gold_ore", .1, (1, 2)), ("andesite", .3, (2, 5))],
    "deep": [("deepslate", 1, (10, 20)), ("deepslate_iron_ore", .45, (1, 3)), ("deepslate_redstone_ore", .4, (1, 4)),
             ("deepslate_diamond_ore", .14, (1, 3)), ("deepslate_gold_ore", .2, (1, 2)), ("deepslate_lapis_ore", .2, (1, 3)),
             ("lava", .5, (1, 4)), ("obsidian", .15, (1, 5)), ("water", .2, (1, 3)), ("tuff", .3, (2, 5))],
    "nether_wastes": [("netherrack", 1, (10, 20)), ("nether_quartz_ore", .5, (1, 4)), ("nether_gold_ore", .3, (1, 3)),
                      ("lava", .6, (1, 5)), ("gravel", .2, (1, 3)), ("soul_sand", .3, (2, 5)), ("glowstone", .2, (1, 3))],
    "fortress": [("nether_bricks", 1, (8, 16)), ("netherrack", 1, (3, 8)), ("nether_wart", .4, (1, 3)), ("lava", .3, (1, 2))],
    "stronghold": [("stone_bricks", 1, (8, 16)), ("mossy_stone_bricks", .6, (2, 6)), ("cracked_stone_bricks", .5, (1, 4)),
                   ("iron_bars", .4, (1, 3))],
    "end": [("end_stone", 1, (10, 20)), ("obsidian", 1, (8, 12))],
}
MOBS = {  # where they live: (biome group, day/night/always, probability)
    "surface_night": [("zombie", .5), ("skeleton", .45), ("creeper", .35), ("spider", .35), ("enderman", .05)],
    "dark": [("zombie", .35), ("skeleton", .35), ("creeper", .25), ("spider", .3)],
    "nether_wastes": [("zombified_piglin", .6), ("ghast", .3), ("piglin", .3), ("magma_cube", .2), ("enderman", .12)],
    "fortress": [("blaze", .9), ("wither_skeleton", .5), ("zombified_piglin", .3)],
    "stronghold": [("silverfish", .5)],
    "end": [("enderman", .95)],
}
HEALTH = {"zombie": 20, "skeleton": 20, "creeper": 20, "spider": 16, "enderman": 40, "cow": 10, "pig": 10, "sheep": 8,
          "chicken": 4, "zombified_piglin": 20, "ghast": 10, "piglin": 16, "magma_cube": 16, "blaze": 20,
          "wither_skeleton": 20, "silverfish": 8, "ender_dragon": 200, "end_crystal": 1}
HOSTILE = {  # chance per moment to hurt me when within reach, damage; 'far' = can hurt from afar
    "zombie": (.15, 3, False), "skeleton": (.1, 3, True), "creeper": (.06, 14, False), "spider": (.15, 2, False),
    "enderman": (.3, 7, False), "zombified_piglin": (.3, 8, False), "ghast": (.06, 6, True), "piglin": (.2, 5, False),
    "magma_cube": (.2, 4, False), "blaze": (.15, 5, True), "wither_skeleton": (.3, 8, False), "silverfish": (.2, 1, False),
    "ender_dragon": (.05, 8, True)}
NEUTRAL = {"enderman", "zombified_piglin"}       # only when provoked
KIND = {"zombie": "zombie", "creeper": "creeper", "cow": "animal", "pig": "animal", "sheep": "animal",
        "chicken": "animal"}
WEAPON = {"wooden_sword": 4, "stone_sword": 5, "iron_sword": 6, "diamond_sword": 7, "wooden_axe": 7, "stone_axe": 9,
          "iron_axe": 9, "diamond_axe": 9}
ARMOR = {"leather": .04, "chainmail": .06, "iron": .08, "golden": .05, "diamond": .12}
TIERS = ["wooden", "stone", "iron", "diamond", "netherite"]
SMELT = {"raw_iron": "iron_ingot", "raw_gold": "gold_ingot", "raw_copper": "copper_ingot", "beef": "cooked_beef",
         "porkchop": "cooked_porkchop", "chicken": "cooked_chicken", "mutton": "cooked_mutton", "cod": "cooked_cod",
         "salmon": "cooked_salmon", "potato": "baked_potato", "sand": "glass", "cobblestone": "stone",
         "oak_log": "charcoal", "iron_ore": "iron_ingot"}
FUEL = ["coal", "charcoal", "oak_log", "oak_planks", "blaze_rod", "stick"]
EXTRA_DROPS = {"oak_leaves": [("oak_sapling", .05), ("apple", .005), ("stick", .02)], "sheep": [("white_wool", 1.0)],
               "gravel": [("flint", RULES["flint_from_gravel"])]}
FULL_BLOCKS = ("cobblestone", "dirt", "cobbled_deepslate", "netherrack", "oak_planks", "stone", "sand", "andesite",
               "end_stone", "deepslate", "oak_log", "sandstone", "tuff", "granite", "diorite")


def tier_of(name):
    for i, t in enumerate(TIERS):
        if name.startswith(t + "_"):
            return i + 1
    return 0


class MineSim:
    def __init__(self, seed=0):
        self.rng = np.random.default_rng(seed)
        self.t = 0                                        # morning
        self.last_act, self.exhaustion = "wait", 0.0
        self.scenes = {}                                  # (dim, x, z, depth) -> scene (a persistent world)
        self.spawn = ("overworld", 0, 0, 0)
        self.stronghold = (int(self.rng.integers(6, 12)) * (1 if self.rng.random() < .5 else -1),
                           int(self.rng.integers(6, 12)) * (1 if self.rng.random() < .5 else -1))
        self.dragon_dead = False
        self.won_at = None
        self.ever = set()
        self.nether_entry = None
        self.new_life()

    # ---------------------------------------------------------------- places
    def _gen(self, key):
        dim, x, z, depth = key
        r = self.rng
        if dim == "overworld":
            if (x, z) == self.stronghold and depth >= 1:
                kind = "stronghold"
            else:
                kind = ["plains", "forest", "hills", "desert"][int(r.choice(4, p=[.4, .3, .2, .1]))] if depth == 0 \
                    else "cave" if depth == 1 else "deep"
        elif dim == "the_nether":
            kind = "fortress" if (key != self.nether_entry and r.random() < .12) else "nether_wastes"
        else:
            kind = "end"
        things = {}
        for name, p, (a, b) in BIOMES[kind]:
            if r.random() < p and b > 0:
                things[name] = int(r.integers(a, b + 1))
        sc = {"kind": kind, "things": things, "mobs": [], "reach": set(), "frame": 0, "portal": None,
              "eyes": 0, "placed": {}}
        if kind == "stronghold":
            sc["things"]["end_portal_frame"] = 12
            sc["eyes"] = int(r.binomial(12, .1))
        if kind == "end":
            sc["things"]["end_crystal"] = 10
            self._spawn(sc, "ender_dragon")
        for mk in ("dark",) if kind in ("cave", "deep") else (kind,) if kind in MOBS else ():
            for name, p in MOBS[mk]:
                if r.random() < p:
                    self._spawn(sc, name)
        if kind in ("plains", "forest", "hills"):
            for name in ("cow", "pig", "sheep", "chicken"):
                n = things.pop(name, 0)
                for _ in range(n):
                    self._spawn(sc, name)
        return sc

    def _spawn(self, sc, name):
        sc["mobs"].append({"name": name, "hp": HEALTH.get(name, 10), "id": int(self.rng.integers(1 << 30)),
                           "near": False, "angry": name not in NEUTRAL})

    def scene(self, key=None):
        key = key or self.where
        if key not in self.scenes:
            self.scenes[key] = self._gen(key)
        return self.scenes[key]

    def new_life(self):
        if getattr(self, "where", None) is not None and self.where in getattr(self, "scenes", {}):
            self._leave()
        self.where = self.spawn
        self.scene()["inside"] = False
        self.t += (DAY - self.t % DAY) if self.night() else 0        # you wake up in the morning (as after a bed)
        self.inv, self.worn = {}, set()
        self.hp, self.food, self.held = 20.0, 20, None
        self.exhaustion = 0.0
        self.height = 0                                   # pillared up (for the end crystals)
        self.nether_entry = None
        self.eye_hint = 0
        self.fev = self._fev()
        self.adv_new, self.adv = [], getattr(self, "adv", set())
        self.died = ""

    def _fev(self):
        return {"deaths": [], "hurt": [], "lost": [], "boom": False, "gift": False, "tamed": None, "carerDid": None,
                "ate": None, "trades": [], "traded": None, "read": None}

    def night(self):
        return NIGHT[0] <= self.t % DAY < NIGHT[1]

    def surface(self):
        return self.where[0] == "overworld" and self.where[3] == 0

    # ---------------------------------------------------------------- the body's abilities
    def give(self, item, n=1):
        self.inv[item] = self.inv.get(item, 0) + n

    def take(self, item, n=1):
        self.inv[item] = self.inv.get(item, 0) - n
        if self.inv[item] <= 0:
            del self.inv[item]

    def pick_tier(self):
        return max([tier_of(k) for k in self.inv if k.endswith("_pickaxe")] + [0])

    def can_mine(self, block):
        info = RULES["blocks"].get(block)
        if info is None or not info["diggable"] or block in ("water", "lava", "end_portal_frame", "bedrock"):
            return False
        tools = info["tools"]
        return not tools or any(t in self.inv for t in tools)

    def mine(self, block, sc):
        if block not in sc["things"] or not self.can_mine(block):
            return False
        sc["things"][block] -= 1
        if sc["placed"].get(block, 0) > sc["things"][block]:
            sc["placed"][block] = sc["things"][block]
            if sum(sc["placed"].values()) < SHELTER:
                sc["inside"] = False
        if sc["things"][block] <= 0:
            del sc["things"][block]
            sc["reach"].discard(block)
        info = RULES["blocks"][block]
        drops = info["drops"][:1] or [block]
        if block in EXTRA_DROPS:
            drops = [] if block == "oak_leaves" else drops
            for d, p in EXTRA_DROPS[block]:
                if self.rng.random() < p:
                    drops = [d] if block == "gravel" else drops + [d]
        for d in drops:
            self.give(d)
        if "lava" in sc["things"] and self.rng.random() < .01:          # dug into lava
            self.hurt(12, "lava")
        return True

    def recipe_ok(self, item):
        rs = RULES["recipes"].get(item)
        if not rs:
            return None
        sc = self.scene()
        for r in rs:
            if r["table"] and "crafting_table" not in sc["things"] and "crafting_table" not in self.inv:
                continue
            if all(self.inv.get(k, 0) >= n for k, n in r["need"].items()):
                return r
        return None

    def craft(self, item):
        r = self.recipe_ok(item)
        if r is None:
            return False
        sc = self.scene()
        if r["table"] and "crafting_table" not in sc["things"]:          # put the table down first (like the bot)
            self.take("crafting_table")
            sc["things"]["crafting_table"] = 1
            sc["reach"].add("crafting_table")
        for k, n in r["need"].items():
            self.take(k, n)
        self.give(item, r["makes"])
        return True

    def hurt(self, dmg, cause):
        armor = sum(ARMOR.get(w.split("_")[0], 0) for w in self.worn)
        dmg = dmg * (1 - min(.8, armor))
        self.hp -= dmg
        self.fev["hurt"].append(["self", 0, int(round(dmg)), cause])
        if self.hp <= 0 and not self.died:
            self.died = {"lava": "tried to swim in lava", "fall": "fell from a high place", "hunger": "starved to death",
                         "ender_dragon": "was slain by Ender Dragon"}.get(cause, f"was slain by {cause}")

    def attack(self, sc, name=None):
        near = [m for m in sc["mobs"] if m["near"] and (name is None or m["name"] == name)]
        if not near:
            near = [m for m in sc["mobs"] if name is not None and m["name"] == name]
            if not near:
                return
            near[0]["near"] = True
        mob = near[0]
        if mob["name"] == "ender_dragon" and self.rng.random() > .25:
            return                                          # it is flying, out of reach
        dmg = max([1] + [WEAPON.get(k, 1) for k in self.inv if k in WEAPON and self.held == "weapon"])
        mob["hp"] -= dmg
        mob["angry"] = mob["hit"] = True
        self.fev["hurt"].append([KIND.get(mob["name"], "hostile"), mob["id"] % 100000, int(dmg), "self"])
        if mob["name"] == "zombified_piglin":
            for m in sc["mobs"]:
                if m["name"] == "zombified_piglin":
                    m["angry"] = True
        if mob["hp"] <= 0:
            sc["mobs"].remove(mob)
            self.fev["deaths"].append([KIND.get(mob["name"], "hostile"), mob["id"] % 100000, False, "self", True])
            for item, p in RULES["mobs"].get(mob["name"], []) + EXTRA_DROPS.get(mob["name"], []):
                if self.rng.random() < p:
                    self.give(item)
            self.advance("adventure/kill_a_mob")
            if mob["name"] == "ender_dragon":
                self.dragon_dead = True
                self.advance("end/kill_dragon")

    def advance(self, adv_id):
        if adv_id not in self.adv and adv_id in ADV:
            self.adv.add(adv_id)
            self.adv_new.append([adv_id, ADV[adv_id]["title"]])

    def _enter(self, sc):
        sc["inside"] = True
        for m in sc["mobs"]:
            m["near"] = False

    def _leave(self):
        old = self.scene()
        old["inside"] = False
        old["mobs"] = [m for m in old["mobs"] if m["name"] not in HOSTILE or m["name"] == "ender_dragon"
                       or old["kind"] in ("fortress", "stronghold")]   # hostile mobs despawn far from a player

    def travel(self, key):
        self._leave()
        self.where = key
        sc = self.scene()
        sc["inside"] = False
        sc["reach"] = set()
        for m in sc["mobs"]:
            m["near"] = False
        return sc

    # ---------------------------------------------------------------- one moment
    def step(self, a, target=None):
        self.fev, self.adv_new = self._fev(), []
        self.sleeping = False
        name = ACTIONS[a]
        self.last_act = name
        sc = self.scene()
        r = self.rng
        dim, x, z, depth = self.where
        self.t += 1
        if name in STEP_OUT:                                     # walking out of my shelter
            sc["inside"] = False
        if name in ("forward", "back", "strafe_left", "strafe_right", "turn_left", "turn_right", "jump"):
            opts = list(sc["things"]) + [m["name"] for m in sc["mobs"]]
            if opts and r.random() < .3:                     # a few steps: something else comes within reach
                o = opts[int(r.integers(len(opts)))]
                sc["reach"].add(o)
                for m in sc["mobs"]:
                    if m["name"] == o:
                        m["near"] = True
                        break
        elif name == "approach" and target:
            if target in ("nether_portal", "end_portal") and target in sc["things"]:
                if target == "nether_portal":
                    if dim == "overworld":
                        self.portal_home = ("overworld", x, z, depth)
                        self.nether_entry = ("the_nether", x // 8, z // 8, 0)
                        nsc = self.travel(self.nether_entry)
                        nsc["things"]["nether_portal"] = 1
                        self.advance("story/enter_the_nether")
                    else:
                        self.travel(getattr(self, "portal_home", self.spawn))
                else:
                    self.travel(("the_end", 0, 0, 0))
                    self.advance("story/enter_the_end")
            elif target in sc["things"]:
                sc["reach"].add(target)
            else:
                for m in sc["mobs"]:
                    if m["name"] == target:
                        m["near"] = True
                        break
        elif name in ("mine_target", "dig_front"):
            block = target if name == "mine_target" else None
            if block is None:
                cands = [b for b in sc["reach"] if b in sc["things"]] or list(sc["things"])
                block = cands[int(r.integers(len(cands)))] if cands else None
            if block is not None and self.mine(block, sc):
                self.held = "tool"
                if block in ("stone", "cobblestone", "deepslate"):
                    self.advance("story/mine_stone")
                if "diamond" in block:
                    self.advance("story/mine_diamond")
                if block == "obsidian":
                    self.advance("story/form_obsidian")
        elif name == "craft_target" and target:
            if self.craft(str(target)):
                self._craft_adv(str(target))
        elif name in ("craft_new", "craft_gear"):
            cands = [k for k in RULES["recipes"] if self.recipe_ok(k)]
            if name == "craft_new":
                cands = [k for k in cands if k not in self.ever][:3]
            else:
                cands = sorted([k for k in cands if k.endswith(("_pickaxe", "_sword", "_axe", "_helmet", "_chestplate",
                                                                  "_leggings", "_boots"))], key=lambda k: -tier_of(k))[:1]
            for k in cands:
                if self.craft(k):
                    self._craft_adv(k)
                    break
        elif name == "smelt":
            if "furnace" in sc["things"] or "furnace" in self.inv:
                if "furnace" not in sc["things"]:
                    self.take("furnace")
                    sc["things"]["furnace"] = 1
                fuel = next((f for f in FUEL if f in self.inv), None)
                raw = next((k for k in self.inv if k in SMELT and k != fuel), None)
                if fuel and raw:
                    n = min(self.inv[raw], 8)
                    self.take(raw, n)
                    self.take(fuel)
                    self.give(SMELT[raw], n)
                    if SMELT[raw] == "iron_ingot":
                        self.advance("story/smelt_iron")
        elif name == "eat":
            foods = [k for k in self.inv if k in RULES["foods"]]
            if foods and self.food < 20:
                f = foods[int(r.integers(len(foods)))]
                self.take(f)
                self.food = min(20, self.food + RULES["foods"][f]["points"])
                self.fev["ate"] = f
                if f in ("rotten_flesh", "chicken", "spider_eye", "poisonous_potato") and r.random() < .5:
                    self.food = max(0, self.food - 3)
        elif name == "attack":
            self.attack(sc, target if target else None)
        elif name == "equip_weapon":
            self.held = "weapon"
        elif name == "equip_armor":
            for piece in ("helmet", "chestplate", "leggings", "boots"):
                best = max((k for k in self.inv if k.endswith("_" + piece)), key=lambda k: ARMOR.get(k.split("_")[0], 0),
                           default=None)
                if best:
                    for w in [w for w in self.worn if w.endswith("_" + piece)]:
                        self.worn.discard(w)
                    self.worn.add(best)
                    self.take(best)
                    self.advance("story/obtain_armor")
        elif name == "dig_down" and dim == "overworld" and depth < 2 and self.pick_tier() >= 1:
            if r.random() < .03:
                self.hurt(4, "fall")
            self.travel((dim, x, z, depth + 1))
        elif name in ("dig_up", "pillar_up"):
            if dim == "the_end" and name == "pillar_up" and any(k in self.inv for k in FULL_BLOCKS):
                self.take(next(k for k in FULL_BLOCKS if k in self.inv))
                self.height += 1
            elif dim == "overworld" and depth > 0 and (name == "dig_up" and self.pick_tier() >= 1 or
                                                       name == "pillar_up" and any(k in self.inv for k in FULL_BLOCKS)):
                if name == "pillar_up":
                    self.take(next(k for k in FULL_BLOCKS if k in self.inv))
                self.travel((dim, x, z, depth - 1))
        elif name == "explore":
            if dim == "overworld" and depth == 0:
                dx, dz = int(r.integers(-1, 2)), int(r.integers(-1, 2))
                if self.eye_hint > 0:                              # following the eye of ender
                    dx, dz = int(np.sign(self.stronghold[0] - x)), int(np.sign(self.stronghold[1] - z))
                    self.eye_hint -= 1
                self.travel((dim, x + dx, z + dz, 0))
            elif dim == "overworld":
                self.travel((dim, x + int(r.integers(-1, 2)), z + int(r.integers(-1, 2)), depth))
            elif dim == "the_nether":
                nk = (dim, x + int(r.integers(-1, 2)), z + int(r.integers(-1, 2)), 0)
                nsc = self.travel(nk)
                if nsc["kind"] == "fortress":
                    self.advance("nether/find_fortress")
            if self.where[:3] == ("overworld",) + self.stronghold and depth >= 1:
                self.advance("story/follow_ender_eye")
            if "lava" in self.scene()["things"] and r.random() < .01:
                self.hurt(12, "lava")                              # a lava pool here, one misstep (pathfinding avoids most)
        elif name == "goto_place" and target and dim == "overworld":
            nsc = self.travel(("overworld", int(target[0]) // 16, int(target[1]) // 16, 0))
            if sum(nsc["placed"].values()) >= SHELTER:
                self._enter(nsc)                                 # home: in through the door
        elif name == "place_block":
            blk = next((k for k in FULL_BLOCKS if k in self.inv), None)
            if blk:
                self.take(blk)
                sc["things"][blk] = sc["things"].get(blk, 0) + 1
                sc["placed"][blk] = sc["placed"].get(blk, 0) + 1
                if dim == "overworld" and depth == 0 and sum(sc["placed"].values()) >= SHELTER:
                    self._enter(sc)                              # walls and a roof around me
        elif name == "place_frame" and self.inv.get("obsidian", 0) >= 10 and dim == "overworld":
            self.take("obsidian", 10)
            sc["things"]["nether_portal_frame"] = 1
        elif name == "place_chest" and "chest" in self.inv:
            self.take("chest")
            sc["things"]["chest"] = 1
        elif name == "use_item":
            if "flint_and_steel" in self.inv and "nether_portal_frame" in sc["things"]:
                del sc["things"]["nether_portal_frame"]
                sc["things"]["nether_portal"] = 1
            elif "ender_eye" in self.inv and sc["kind"] == "stronghold" and sc["eyes"] < 12:
                self.take("ender_eye")
                sc["eyes"] += 1
                if sc["eyes"] >= 12:
                    sc["things"]["end_portal"] = 1
            elif "ender_eye" in self.inv and dim == "overworld" and depth == 0:
                if r.random() < .2:
                    self.take("ender_eye")                         # the eye shattered
                self.eye_hint = 3                                  # I saw where it flew
            elif "bow" in self.inv and "arrow" in self.inv and "end_crystal" in sc["things"]:
                self.take("arrow")
                if r.random() < .5:
                    self._crystal(sc)
        elif name == "sleep" and self.night() and any(k.endswith("_bed") for k in self.inv) and dim == "overworld":
            self.t += DAY - self.t % DAY
            self.sleeping = True
            sc["mobs"] = [m for m in sc["mobs"] if m["name"] not in ("zombie", "skeleton", "spider", "creeper")]
        elif name == "fish" and "fishing_rod" in self.inv and "water" in sc["things"] and r.random() < .2:
            self.give("cod")
        if dim == "the_end" and self.height >= 3 and name == "attack" and "end_crystal" in sc["things"]:
            self._crystal(sc)
        self._world(sc)
        return self.message()

    def _crystal(self, sc):
        sc["things"]["end_crystal"] -= 1
        self.fev["boom"] = True
        self.hurt(4, "end_crystal")
        if sc["things"]["end_crystal"] <= 0:
            del sc["things"]["end_crystal"]

    def _craft_adv(self, item):
        if item == "stone_pickaxe":
            self.advance("story/upgrade_tools")
        if item == "iron_pickaxe":
            self.advance("story/iron_tools")
        if item == "ender_eye":
            pass

    def _world(self, sc):
        r = self.rng
        dim, x, z, depth = self.where
        # the body: hunger and healing
        self.exhaustion = getattr(self, "exhaustion", 0.0) + EXHAUST.get(self.last_act, 0.005)
        if self.exhaustion >= 4.0:                                     # Minecraft's exhaustion: effort costs food
            self.exhaustion -= 4.0
            self.food = max(0, self.food - 1)
        if self.food == 0 and self.t % 20 == 0 and self.hp > 1:
            self.hurt(1, "hunger")                                     # Normal difficulty: hunger leaves half a heart
        if self.food >= 18 and self.t % 20 == 0 and self.hp < 20:
            self.hp = min(20.0, self.hp + 1)
            self.exhaustion += 6.0                                     # healing is paid for with food
        # creatures
        dark = depth > 0 or dim != "overworld" or self.night()
        if dim == "overworld" and depth == 0 and self.night() and r.random() < .01 and len(sc["mobs"]) < 6:
            names, ps = zip(*MOBS["surface_night"])
            name = names[int(r.choice(len(names), p=np.array(ps) / sum(ps)))]
            self._spawn(sc, name)
        if dim == "overworld" and depth > 0 and r.random() < .008 and len(sc["mobs"]) < 6:
            self._spawn(sc, MOBS["dark"][int(r.integers(4))][0])
        if dim == "overworld" and depth == 0 and not self.night():
            sc["mobs"] = [m for m in sc["mobs"] if m["name"] not in ("zombie", "skeleton") or depth > 0]
            for m in sc["mobs"]:
                if m["name"] == "spider" and not m.get("hit"):
                    m["angry"] = False                       # spiders are calm in daylight unless provoked
        for m in list(sc["mobs"]):
            h = HOSTILE.get(m["name"])
            if h is None or not m["angry"]:
                continue
            if sc.get("inside"):
                m["near"] = False                            # walls between us
                continue
            if not m["near"] and r.random() < (.06 if dark else .02):
                m["near"] = True                             # it comes to me
            if (m["near"] or h[2]) and r.random() < h[0]:
                if m["name"] == "ender_dragon":
                    crystals = sc["things"].get("end_crystal", 0)
                    m["hp"] = min(HEALTH["ender_dragon"], m["hp"] + crystals * .5)
                self.hurt(h[1], m["name"])
                if m["name"] == "creeper":
                    sc["mobs"].remove(m)
                    self.fev["boom"] = True
        # dimension-specific dangers
        if dim == "the_nether" and r.random() < .003:
            self.hurt(10, "lava")
        if self.hp <= 0:
            self.fev["deaths"] = self.fev["deaths"]
            died = self.died or "died"
            self.new_life()
            self.died = died
            self.hp = 20.0

    # ---------------------------------------------------------------- the body's report (like bot.js)
    def message(self):
        sc = self.scene()
        dim, x, z, depth = self.where
        items = dict(self.inv)
        for w in self.worn:
            items["worn:" + w] = 1
        self.ever = getattr(self, "ever", set()) | set(self.inv)
        seen = []
        for k in sc["things"]:
            seen.append([k, 2 if k in sc["reach"] else 8, "block"])
        for m in sc["mobs"]:
            seen.append([m["name"], 2 if m["near"] else 8, "mob"])
        near = [[KIND.get(m["name"], "hostile" if m["name"] in HOSTILE else "animal"), m["id"] % 100000, 2 if m["near"] else 6]
                for m in sc["mobs"]]
        cls = {"oak_log": 1, "lava": 3, "water": 4}
        front = next((cls.get(b, 2 if "ore" in b or b in ("stone", "deepslate") else 5) for b in sc["reach"]), 0)
        grid = [0] * 25
        grid[7] = front
        tod = int((self.t % DAY) / DAY * 24000)
        y = {0: 64, 1: 30, 2: -30}.get(depth, 64) if dim == "overworld" else 64
        hostile = [m for m in sc["mobs"] if m["name"] in HOSTILE]
        feat = [5 if hostile else 0, 5 if any(m["name"] in ("cow", "pig", "sheep", "chicken") for m in sc["mobs"]) else 0,
                min(4, int(self.hp) // 5), min(4, self.food // 5), len(self.worn),
                2 if self.held == "weapon" else 1 if self.held == "tool" else 0, self.pick_tier(), int(self.night()),
                0, 0, 1, 0, min(15, len(self.adv))]
        died = self.died
        self.died = ""
        msg = {"obs": grid, "inv": items.get("oak_log", 0), "goal": 0, "reward": 0.0, "done": bool(died),
               "items": items, "chunk": [x, z], "food": self.food, "health": max(0.0, self.hp),
               "can_craft_new": False, "feat": feat, "died": died, "heard": [], "advancements": self.adv_new,
               "sky": int(dim == "overworld" and depth == 0 and not sc.get("inside")),
               "around": [7] * 6 if sc.get("inside") else [0] * 6, "stuck": 0, "y": y,
               "near": near, "fev": self.fev, "time": tod, "heading": 0, "pitch": 0, "xz": [x * 16, z * 16],
               "held": self.held or "", "diamond_seen": 5 if any("diamond_ore" in k for k in sc["things"]) else 0,
               "seen": seen, "dim": dim, "sleeping": getattr(self, "sleeping", False),
               "craftable": [k for k in RULES["recipes"] if self.recipe_ok(k)][:40]}   # what the recipe book shows
        return msg
