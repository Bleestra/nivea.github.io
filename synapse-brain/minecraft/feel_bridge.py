"""
Feelings in Minecraft: the body's report turned into what the limbic system feels, and its words.

The same brain as in LifeWorld (agent/child.py + agent/limbic.py). What differs is only the body:
  - taste: an innate palatability for each Minecraft food (the tongue, not a rule about behaviour);
  - the sky: with eyes (--eyes) its colours come from the real picture when the bot looks up;
    without eyes the bot only has a sense of time of day (weaker than seeing);
  - the tone of a player's voice is approximated from the words in chat (warm / alarmed / scolding);
  - what happened to the blocks it placed itself is reported by the body (efference copy);
  - kinds of beings: zombie, creeper, cat (and 'mycat' once tamed), a player (the caregiver), others.
"""
import os
import pickle
import re
import sys

import zlib

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
from brain_agent import _h  # noqa: E402
from child import Child  # noqa: E402
from limbic import NAMES  # noqa: E402
from mind_bridge import ru, state_from  # noqa: E402
from actions import ACTIONS  # noqa: E402

MC_TASTE = {  # innate palatability (sweet/fat/umami good; bitter/rotten/poison bad)
    "cooked_beef": 1.0, "cooked_porkchop": 1.0, "cooked_chicken": 0.9, "cooked_mutton": 0.9, "cooked_rabbit": 0.9,
    "cooked_cod": 0.9, "cooked_salmon": 1.0, "bread": 0.6, "baked_potato": 0.7, "apple": 0.5, "golden_apple": 1.2,
    "enchanted_golden_apple": 1.3, "sweet_berries": 0.6, "glow_berries": 0.6, "carrot": 0.4, "golden_carrot": 1.0,
    "beetroot": 0.3, "melon_slice": 0.7, "cookie": 1.0, "cake": 1.2, "pumpkin_pie": 1.0, "honey_bottle": 1.1,
    "mushroom_stew": 0.8, "rabbit_stew": 1.0, "beetroot_soup": 0.6, "suspicious_stew": 0.4, "dried_kelp": 0.2,
    "beef": 0.2, "porkchop": 0.2, "chicken": -0.2, "mutton": 0.2, "rabbit": 0.2, "cod": 0.3, "salmon": 0.3,
    "tropical_fish": 0.3, "potato": 0.1, "rotten_flesh": -0.6, "spider_eye": -0.8, "poisonous_potato": -0.7,
    "pufferfish": -0.9, "chorus_fruit": 0.1,
}
KINDS = ["zombie", "creeper", "cat", "mycat", "carer", "hostile", "animal", "villager", "golem", "peer"]
# sounds the ears know from birth (a hiss, a boom, a groan, a purr: the limbic system startles or calms);
# every other sound is only "heard" - what it means is learned
# kinds of pain, as the body knows them (the game says what hurt: a fall, a blow, hunger, water, fire...)
PAIN = {"hands": "hands", "fall": "fall", "fly_into_wall": "fall", "falling_block": "fall", "falling_anvil": "fall", "falling_stalactite": "fall",
        "starve": "hunger", "drown": "drown", "in_fire": "burn", "on_fire": "burn", "lava": "burn", "hot_floor": "burn",
        "campfire": "burn", "lightning_bolt": "burn", "dragon_breath": "burn", "cactus": "prick", "sweet_berry_bush": "prick",
        "stalagmite": "prick", "thorns": "prick", "explosion": "blast", "player_explosion": "blast", "in_wall": "suffocation",
        "cramming": "suffocation", "freeze": "cold", "magic": "poison", "indirect_magic": "poison", "wither": "poison",
        "out_of_world": "void", "generic": "world"}
ATTACKS = ("mob_attack", "mob_attack_no_aggro", "player_attack", "arrow", "trident", "mob_projectile", "sting", "fireball",
           "thrown", "sonic_boom", "spit")


def sealed_sides(around):
    """How many of my four sides are closed at both my feet and my head (a mob cannot reach me there)."""
    blocked = (1, 2, 5)
    return sum(1 for x in around[:4] if x // 6 in blocked and x % 6 in blocked)


def dark_unease(m):
    """Innate apprehension of the dark (0..1), as in people: the darker it is and the more exposed I am (open sky,
    open sides), the stronger. None in the Nether and the End, where darkness is not the danger."""
    dim = str(m.get("dim", "overworld"))
    if "nether" in dim or dim.endswith("end"):
        return 0.0
    light = m.get("light")
    if light is None:                                           # a body without the light sense: the time of day
        tod = m.get("time", 6000)
        light = 4 if 13000 <= tod <= 23000 and m.get("sky", 1) else 12
    dark = max(0.0, (8 - float(light)) / 8)
    exposure = (1.0 if m.get("sky", 1) else 0.6) - 0.15 * sealed_sides(m.get("around", []))
    return float(max(0.0, min(1.0, dark * exposure)))


def pain_of(entry):
    """[damage type, attacker kind, attacker] -> what hurt: the attacker's kind for a blow, else the kind of pain."""
    kind_type, who_kind = entry[0], entry[1] if len(entry) > 1 else ""
    if who_kind and (kind_type in ATTACKS or kind_type not in PAIN):
        return who_kind
    return PAIN.get(kind_type, "hit" if kind_type in ATTACKS else kind_type)


INNATE_SOUNDS = {("creeper", "primed"): "hiss", ("explode", ""): "boom", ("zombie", "ambient"): "groan",
                 ("cat", "purr"): "purr", ("cat", "purreow"): "purr"}
WARM = r"молод|умни|хорош|люблю|спасиб|класс|отлич|good|nice|love|thank|great|well done"
ALARM = r"осторожн|беги|опасн|сзади|крипер|careful|run|watch out|behind"
SCOLD = r"нельзя|плохо|не надо|стоп|прекрати|фу\b|bad|stop|don't|dont"
SKY_WORDS = {0: "ночное небо", 1: "голубое небо", 2: "облака", 3: "жёлтое небо", 4: "оранжевый закат",
             5: "красный закат", 6: "розовое небо", 7: "звёзды"}


def sky_from_time(tod, look):
    """No eyes: a sense of the time of day, turned into the same colour codes."""
    if tod < 12000:
        v = np.ones(8, np.int64)
    elif tod < 13800:
        s = (tod - 12000) / 1800
        v = np.clip(3 + (np.arange(8) / 8 * 3 + s * 2).astype(int), 3, 6)
    elif tod < 22200:
        v = np.zeros(8, np.int64)
    else:
        v = np.clip(6 - (np.arange(8) / 8 * 2 + (tod - 22200) / 1800 * 2).astype(int), 4, 6)
    return v if look else np.array([int(np.bincount(v, minlength=8).argmax())])


def sky_from_frame(frame, look):
    """Eyes: colour of 8 patches of the upper part of the picture (hue, brightness, saturation)."""
    top = frame[:20].astype(np.float32)
    out = []
    for j in range(8):
        r, g, b = top[:, j * 8:(j + 1) * 8].reshape(-1, 3).mean(0)
        mx, mn = max(r, g, b), min(r, g, b)
        if mx < 50:
            c = 0
        elif mx - mn < 25:
            c = 2 if mx > 170 else 1
        elif b >= r and b >= g:
            c = 1
        elif r > 200 and g > 170:
            c = 3
        elif r > g * 1.3 and g > 90:
            c = 4
        elif r > g * 1.3 and b < r * 0.7:
            c = 5
        elif r > g and b > g:
            c = 6
        else:
            c = 1
        out.append(c)
    v = np.array(out, np.int64)
    return v if look else np.array([int(np.bincount(v, minlength=8).argmax())])


def kinds_of(s):
    """Planks are planks, a log is a log: what the recipes and the guide call oak planks (any planks will do -
    "crafted from planks of any kind") is also what I have when I carry birch or spruce planks. A person sees
    the kind, not only the tree it came from."""
    out = dict(s)
    for k, v in s.items():
        m = KIND.match(k)
        if m and v:
            oak = f"{m.group(1)}:oak_{m.group(3)}"
            out[oak] = out.get(oak, 0) + v if m.group(1) == "have" else max(out.get(oak, 0), v)
        t = TOOL.match(k)                             # a stone pickaxe is a pickaxe: it does what a wooden one does
        if t and v:
            basic = f"{t.group(1)}:wooden_{t.group(3)}"
            out[basic] = max(out.get(basic, 0), v)
    return out


class MCChild(Child):
    def __init__(self, n_actions, seed=0):
        super().__init__(n_actions, seed=seed, taste=MC_TASTE, items=("log", "cobble", "food", "fish", "rotten_flesh"),
                         eat_action=6, wait_action=4, kinds=KINDS)
        self.attack_action = ACTIONS.index("attack")           # anger's innate urge acts through this one
        self.mind.helper_kinds = ("have:", "hold:", "wear:")    # what can make a thing go better: what I carry, hold, wear
        self.m = {}
        from imitation import Imitation
        from places import PlaceMemory

        self.places, self.imitation = PlaceMemory(), Imitation()   # where things are; what I saw people do
        from development import Development
        from guide_reader import GuideBook

        self.development = Development(GuideBook())              # the need to grow; the guide to learn how
        self.mind.min_desire = float(os.environ.get("MIN_DESIRE_MC", "0.2"))
        self.relative_value = os.environ.get("RELATIVE", "1") == "1"
        self.mind.secondary = os.environ.get("SECONDARY", "1") == "1"
        self.cortical_dopamine = os.environ.get("CORTICAL_DA", "1") == "1"
        self.mind.contingency = os.environ.get("CONTINGENCY", "1") == "1"
        self.hunger_ctx = os.environ.get("HUNGER_CTX", "1") == "1"
        base = self.mind.flat.cells

        def cells(obs):                       # the striatum also knows what I have and what is around (concepts)
            c = base(obs)
            extra = [_h(31, zlib.crc32(k.encode()), min(int(v), 3)) for k, v in self._concepts.items() if v]
            return np.concatenate([c, np.array(extra, np.int64)]) if extra else c
        self.mind.flat.cells = cells
        self._concepts = {}
        # sensations and places are means, not things to want for themselves
        self.mind.means_only = ("see:", "reach:", "walls", "saw:", "deep", "underground", "stuck", "free", "indoors", "sky",
                                "near:", "day", "in:", "can_craft:", "hear:", "broke:", "know:", "moving:", "dark",
                                "approach:", "stored:", "bag_room", "hold:", "at_table")

    def senses(self, o):
        self._concepts = self.concepts(o)
        s = super().senses(o)
        vis = self.m.get("_vis_ids")                  # what the eyes recognise where: cells the habits learn from
        if vis:
            s = (s[0], s[1], s[2], np.asarray(vis, np.int64), s[4])
        return s

    def concepts(self, o):
        s = state_from(self.m)                        # everything it holds, sky, stuck, day, fed, healthy
        for k in self.kinds:
            s["near:" + k] = int(any(kind == k and d <= 2 for kind, _, d in o["near"]))
        if len(o["sky"]) == 8:
            s["sky:%d" % int(np.bincount(o["sky"], minlength=8).argmax())] = 1
        for k in (3, 5, 7):
            s["walls>=%d" % k] = int(o["walls"] >= k)
        s["indoors"] = int(not self.m.get("sky", 1) and self.m.get("y", 64) >= 55)   # a roof over my head, not a cave
        s["deep"] = int(self.m.get("y", 64) < 16)                                      # far below the surface
        s["see:diamond"] = int(bool(self.m.get("diamond_seen")))
        s["in:" + str(self.m.get("dim", "overworld")).replace("minecraft:", "")] = 1  # which world I am in
        for k in self.m.get("craftable", []):                                          # the recipe book shows it
            s["can_craft:" + k] = 1
        for name, d, *_ in self.m.get("seen", []):                                    # what my eyes see now
            s["see:" + name] = 1
            if d <= 4:
                s["reach:" + name] = 1                                                 # ... and can touch
        for what, *_ in self.m.get("hear", []):                                        # what my ears hear now
            s["hear:" + str(what)] = 1
        for block, _ in (self.m.get("fev") or {}).get("broke", []):                    # my hands just broke it
            s["broke:" + str(block)] = 1
        for entry in self.m.get("pain", []):                                           # it hurts: what hurt me
            s["pain:" + pain_of(entry)] = 1
        for name in self.m.get("_known_places", []):                                   # I remember where there is X
            s["know:" + name] = 1
        for name, n in (self.m.get("_stored") or {}).items():                          # I have X put away in a chest
            s["stored:" + name] = n
        if self.m.get("held"):
            s["hold:" + str(self.m["held"])] = 1                                       # what is in my hand
        for kind, _, _, cause, *_ in (self.m.get("fev") or {}).get("deaths", []):
            if cause == "self":
                s["killed:" + str(kind)] = 1                                           # it fell by my hand
        if "free_slots" in self.m:
            s["bag_room"] = int(self.m["free_slots"] > 0)                              # there is room in my bag
        if self.m.get("table_near") or (self.m.get("items") or {}).get("crafting_table"):
            s["at_table"] = 1                                                          # a crafting table at hand
        light = self.m.get("light")
        if light is not None and light <= 7:
            s["dark"] = 1                                                              # it is dark around me
        if sealed_sides(self.m.get("around", [])) == 4 and not self.m.get("sky", 1):
            s["sheltered"] = 1                                                         # walls on every side, a roof
        night = 13000 <= self.m.get("time", 6000) <= 23000
        if night and self.m.get("_unease", 1.0) < 0.05 and "nether" not in str(self.m.get("dim", "")):
            s["safe_night"] = 1                                                        # night, and I am not afraid
        motion = self.m.get("_motion") or {}                                           # the eyes see it move
        for name in motion.get("moving", []):
            s["moving:" + name] = 1
        for name in motion.get("approach", []):
            s["approach:" + name] = 1
        if (self.m.get("fev") or {}).get("trades"):
            s["saw:trades"] = 1
        tr = (self.m.get("fev") or {}).get("traded")
        if tr:
            s["traded"] = s.get("traded", 0) + 1
        return kinds_of(s)


class Body:
    """Keeps what the bridge needs to know between two moments (health before, fatigue, ...)."""

    def __init__(self):
        self.hp, self.fish, self.fatigue, self.t, self.nausea, self.prev_items = 20, 0, 0, 0, 0, {}
        self.was_asleep = False

    def to_o(self, m, act, frame=None):
        self.t += 1
        items = m.get("items", {})
        fev = m.get("fev", {}) or {}
        tod = m.get("time", 6000)
        night = 13000 <= tod <= 23000
        look = act == 13 or m.get("pitch", 0) < 0            # looking up
        sky = sky_from_frame(frame, look) if frame is not None else sky_from_time(tod, look)
        hp = float(m.get("health", 20) or 20)
        near = [tuple(x) for x in m.get("near", [])]
        hurt = [tuple(x) for x in fev.get("hurt", [])]
        if hp < self.hp:
            pains = m.get("pain", [])
            if pains:                                      # the game says what hurt (the Fabric body)
                cause = pain_of(pains[0])
            else:                                          # otherwise: guessed from who is near
                cause = min(((k, d) for k, _, d in near if k in ("zombie", "creeper", "hostile")), key=lambda x: x[1], default=("world", 0))[0]
            hurt.append(("self", 0, int(round(self.hp - hp)), cause))
        self.hp = hp
        if m.get("sleeping") or m.get("died"):             # slept, or a new body after respawn
            self.fatigue = 0
        self.fatigue += 1
        ate = fev.get("ate")
        if ate == "rotten_flesh":
            self.nausea = 30
        self.nausea = max(0, self.nausea - 1)
        fish = sum(v for k, v in items.items() if k in ("cod", "salmon", "tropical_fish", "cooked_cod", "cooked_salmon"))
        got = [k for k, v in items.items() if v > self.prev_items.get(k, 0)]
        if fev.get("trades"):
            got.append("trades")                                   # something never seen before: a trading window
        self.prev_items = dict(items)
        tone = 0
        for _, text in m.get("heard", []):
            t = text.lower()
            tone = 3 if re.search(SCOLD, t) else 2 if re.search(ALARM, t) else 1 if re.search(WARM, t) else tone
        sounds = set()
        for what, _, dist, *which in m.get("hear", []):   # real ears (the Fabric body): the game's own sounds
            s = INNATE_SOUNDS.get((what, which[0] if which else "")) or INNATE_SOUNDS.get((what, ""))
            if s and dist <= 16:
                sounds.add(s)
        if not m.get("_human"):                            # without real ears: guessed from who is near
            if fev.get("boom"):
                sounds.add("boom")
            if any(k == "creeper" and d <= 3 for k, _, d in near):
                sounds.add("hiss")
            if any(k == "zombie" and d <= 5 for k, _, d in near):
                sounds.add("groan")
            if any(k == "mycat" and d <= 2 for k, _, d in near) and np.random.random() < 0.15:
                sounds.add("purr")
        around = m.get("around", [])
        walls = sum(2 for x in around[:4] if x // 6 in (1, 2, 5) or x % 6 in (1, 2, 5))
        food = sum(v for k, v in items.items() if k in MC_TASTE and MC_TASTE[k] > 0)
        o = {"view": np.array(m["obs"], np.int64), "sky": sky, "walls": walls, "hp": int(hp), "hunger": int(m.get("food", 20) or 20),
             "fatigue": self.fatigue, "nausea": int(self.nausea > 0), "t": self.t, "night": night,
             "pos": tuple(m.get("xz", (0, 0))), "dir": int(m.get("heading", 0)),
             "inv": {"log": sum(v for k, v in items.items() if k.endswith("_log")),
                     "cobble": items.get("cobblestone", 0), "food": food, "fish": fish,
                     "rotten_flesh": items.get("rotten_flesh", 0)},
             "near": near, "carer_holds": "gem" if (m.get("carer_holds") or "").endswith(("diamond", "emerald", "_ingot")) else
             ("fish" if (m.get("carer_holds") or "") in ("cod", "salmon") else None),
             "lost_built": [tuple(x) for x in fev.get("lost", [])],
             "ev": {"deaths": [tuple(x) for x in fev.get("deaths", [])], "hurt": hurt, "destroyed": [], "ate": ate,
                    "caught": fish > self.fish, "tamed": fev.get("tamed"), "tone": tone, "gift": bool(fev.get("gift")),
                    "carer_did": fev.get("carerDid"), "explosion": (0, 0) if fev.get("boom") else None, "sounds": sounds,
                    "died": bool(m.get("died")), "slept": bool(m.get("sleeping")) and not self.was_asleep, "placed": None, "got": got,
                    "cat_with_carer": False}}
        self.fish = fish
        self.was_asleep = bool(m.get("sleeping"))
        return o


def save(child, path):
    os.makedirs(path, exist_ok=True)
    child.mind.save(os.path.join(path, "mind.npz"))
    if getattr(child, "places", None) is not None:
        child.places.save(os.path.join(path, "places.json"))
    if getattr(child, "imitation", None) is not None:
        import json

        with open(os.path.join(path, "imitation.json"), "w", encoding="utf-8") as f:
            json.dump(child.imitation.state(), f, ensure_ascii=False)
    if getattr(child, "development", None) is not None:
        import json

        with open(os.path.join(path, "development.json"), "w", encoding="utf-8") as f:
            json.dump(child.development.state(), f, ensure_ascii=False)
    with open(os.path.join(path, "limbic.pkl"), "wb") as f:
        pickle.dump(child.limbic, f)
    with open(os.path.join(path, "age.txt"), "w") as f:
        f.write(f"{child.age} {child.r_avg} {child.v_avg}")


def load(child, path):
    if not os.path.exists(os.path.join(path, "limbic.pkl")):
        return False
    child.mind.load(os.path.join(path, "mind.npz"))
    if getattr(child, "places", None) is not None:
        child.places.load(os.path.join(path, "places.json"))
    if getattr(child, "imitation", None) is not None and os.path.exists(os.path.join(path, "imitation.json")):
        import json

        child.imitation.load(json.load(open(os.path.join(path, "imitation.json"), encoding="utf-8")))
    if getattr(child, "development", None) is not None and os.path.exists(os.path.join(path, "development.json")):
        import json

        child.development.load(json.load(open(os.path.join(path, "development.json"), encoding="utf-8")))
    with open(os.path.join(path, "limbic.pkl"), "rb") as f:
        child.limbic = pickle.load(f)
    with open(os.path.join(path, "age.txt")) as f:
        parts = f.read().split()
    child.age = int(parts[0])
    if len(parts) == 3:
        child.r_avg, child.v_avg = float(parts[1]), float(parts[2])
    return True


def talk(child, text):
    """Questions about feelings and loves, answered from the limbic system and the mind."""
    t = text.lower()
    L, m = child.limbic, child.mind
    if re.search(r"как (ты )?себя чувству|что (ты )?чувству|как (у тебя )?дела|how do you feel|how are you", t):
        s = L.say()
        return s + "." if s else "Спокойно. Ничего особенного не чувствую."
    if re.search(r"что (ты )?(любишь|нравится)|кого (ты )?любишь|what do you (love|like)", t):
        n = len(m.names)
        val = np.where(m.nc[:n].sum(1) > 0, m.Rc[:n].max(1), m.R[:n])
        liked = [i for i in np.argsort(-val)[:4] if val[i] > 0.2]
        words = []
        for i in liked:
            name = m.names[i]
            words.append(SKY_WORDS.get(int(name[4:]), name) if name.startswith("sky:") else ru(name))
        beings = sorted(L.attach_being.items(), key=lambda kv: -kv[1])[:2]
        who = [("мой кот" if L.kind_of.get(b) == "mycat" else "ты" if L.kind_of.get(b) == "carer" else L.kind_of.get(b, "кто-то"))
               for b, a in beings if a > 0.3]
        out = "Мне нравится: " + (", ".join(words) if words else "пока сам не знаю")
        return out + (". Люблю: " + ", ".join(who) if who else "") + "."
    if re.search(r"чего (ты )?боишься|what are you afraid", t):
        bad = sorted(L.blame.items(), key=lambda kv: -kv[1])[:2]
        return "Боюсь и злюсь на: " + ", ".join(k for k, v in bad if v > 0.3) if any(v > 0.3 for _, v in bad) else "Пока ничего не боюсь."
    return None


def feeling_name(k):
    return NAMES.get(k, k)


MOTOR = {35: "approach", 36: "mine_target", 37: "craft_target", 38: "goto_place", 39: "explore"}
MOTOR.update({ACTIONS.index(k): k for k in ("drop_junk", "store", "take", "attack", "craft_new")})   # which / whom: the brain
KIND = re.compile(r"^(have|see|reach|hold):(?!oak_)(?!stripped_)(\w+?)_(planks|log)$")
TOOL = re.compile(r"^(have|hold):(stone|iron|golden|diamond|netherite)_(sword|pickaxe|axe|shovel|hoe)$")   # a better one of a kind


_RECIPES = []


def recipes():
    """The recipe book I have read (knowledge/sim_rules.json): item -> [{need: {item: n}, ...}]."""
    if not _RECIPES:
        import json

        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge", "sim_rules.json")
        _RECIPES.append(json.load(open(p, encoding="utf-8")).get("recipes", {}) if os.path.exists(p) else {})
    return _RECIPES[0]


def item_kind(name):
    """birch_planks -> oak_planks, stone_sword -> wooden_sword: the kind my knowledge names it by."""
    m = KIND.match("have:" + name)
    if m:
        return f"oak_{m.group(3)}"
    t = TOOL.match("have:" + name)
    return f"wooden_{t.group(3)}" if t else name


def spends(item, need):
    """Making this would use up something my plans need (any planks, when my plan needs planks)."""
    return any({item_kind(k) for k in r["need"]} & need for r in recipes().get(item, []))


def plan_needs(child):
    """Everything my plans need: the whole chain to what I want now, and to the next step of my path."""
    mind = child.mind
    heads = [x for x in (mind.target, mind.goal) if x is not None]
    dev = getattr(child, "development", None)
    if dev is not None and dev.aimed in getattr(dev, "path", {}):
        heads += [mind.idx[c] for alts in dev.path[dev.aimed]["wants"] for c in alts if c in mind.idx]
    active, out = mind.val > 0, set()
    for h in heads:
        out.add(h)
        for e, p in mind.reason(active, h)[1]:
            out.update((e, p))
    for i in list(out):                                   # ... and what I already have for those steps (it will be used)
        out.update(int(p) for p in mind.pre(i))
    return {mind.names[i][5:] for i in out if mind.names[i].startswith("have:")}


def worth_of(child, item):
    """What having this thing is worth to me (learned: its value and what it leads to) - and what it is good for:
    a sword is worth what fighting goes better with it, a pickaxe what mining does (one does not throw tools away)."""
    mind = child.mind
    worth = 0.0
    i = mind.idx.get("have:" + item)
    if i is not None:
        v = getattr(child, "_v", None)
        worth = float(v[i]) if v is not None and i < len(v) else float(max(mind.R[i], 0.0))
    tools = {mind.idx.get(f"{p}:{x}") for x in (item, item_kind(item)) for p in ("have", "hold")} - {None}
    v = getattr(child, "_v", None)

    def goal_worth(g):                                      # the goal with what it leads to (cobblestone -> a pickaxe)
        return float(v[g]) if v is not None and g < len(v) else max(float(mind.R[g]), 0.0)
    for g, pri in mind.helps_prior.items():                 # what I read it helps with
        if tools & set(pri):
            worth = max(worth, 0.5 * goal_worth(g))
    for g, (n, s_, per) in mind.helps.items():              # what I found it helps with
        for p in tools & set(per):
            if per[p][0] >= 5 and (per[p][1] + 1) / (per[p][0] + 2) - (s_ - per[p][1] + 1) / (max(n - per[p][0], 0) + 2) >= 0.2:
                worth = max(worth, 0.5 * goal_worth(g))
    return worth


def attention(child, a, m):
    """What a motor program is aimed at - chosen by the brain: the thing the current plan needs,
    else what I have never seen (novelty draws the eyes), else what I value most; home = the
    place I am most attached to. What to throw away, put away or take - by what things are worth to me."""
    kind = MOTOR.get(a)
    if kind is None or kind == "explore":
        return None
    mind, L = child.mind, child.limbic
    if kind == "craft_new":                                        # curiosity: something never made - but not
        new = [k for k in m.get("craftable", []) if "have:" + k not in mind.idx or mind.nev[mind.idx["have:" + k]] == 0]
        if not new:                                                # out of what my plans need (planks for buttons
            return None                                            # when I need a table and a pickaxe)
        need = plan_needs(child)
        spare = [k for k in new if not spends(k, need)]
        return spare[int(np.random.randint(len(spare)))] if spare else "#none"
    if kind in ("drop_junk", "store", "take"):
        places = getattr(child, "places", None)
        carried = {k: n for k, n in (m.get("items") or {}).items() if not k.startswith("worn:") and n > 0}
        need = plan_needs(child)
        if kind == "drop_junk":                                    # what I value least, the most of it first
            return min(carried, key=lambda k: (worth_of(child, k), -carried[k])) if carried else None
        if kind == "store":                                        # what the plan does not need now, the bulkiest
            spare = [k for k in carried if k not in need] or list(carried)
            return max(spare, key=lambda k: (carried[k], -worth_of(child, k))) if spare else None
        chest = places.nearest_chest(m) if places is not None else None     # take: what the plan needs, else
        inside = chest["items"] if chest else {}                          # what is worth most to me in there
        wanted = [k for k in inside if k in need]
        if wanted:
            return wanted[0]
        return max(inside, key=lambda k: worth_of(child, k)) if inside else None
    if kind == "attack":
        angry = [(k, i, d) for k, i, d in (m.get("near") or []) if L.grudge(k) > 0.1]
        if angry and L.e.get("anger", 0.0) > 0.05:                  # angry: at that very one I hold it against
            return max(angry, key=lambda x: (L.grudge(x[0]), -x[2]))[1]
    if kind == "goto_place":
        places = getattr(child, "places", None)
        if places is not None and mind.goal is not None:           # a remembered place of what my plan needs
            for i in [mind.goal] + list(mind.pre(mind.goal)):
                name = mind.names[i]
                if name == "at_table":                                  # a table I remember: go to it
                    spot = places.nearest("crafting_table", m)
                    if spot:
                        return spot
                if name.startswith(("have:", "stored:")) and name.split(":", 1)[1] not in (m.get("items") or {}):
                    spot = places.where_stored(name.split(":", 1)[1], m)     # I put it away: the chest
                    if spot:
                        return spot
                if name.startswith(("see:", "reach:", "have:", "know:")):
                    spot = places.nearest(name.split(":", 1)[1], m)
                    if spot:
                        return spot
        if not L.attach_place:
            return None
        (x, z), _ = max(L.attach_place.items(), key=lambda kv: kv[1])
        return [int(x), int(z)]
    seen = [x[0] for x in m.get("seen", [])]
    if kind == "mine_target":                              # one digs blocks, not creatures
        seen = [x[0] for x in m.get("seen", []) if len(x) < 3 or x[2] == "block"]
    if kind == "attack":                                   # ... and fights creatures, not blocks - and not people
        seen = [x[0] for x in m.get("seen", []) if len(x) >= 3 and x[2] == "mob" and x[0] != "player"]
    g = mind.goal
    if kind == "craft_target":
        craftable = m.get("craftable", [])
        if g is not None and mind.names[g].startswith("have:"):
            if mind.names[g][5:] in craftable or not craftable:
                return mind.names[g][5:]
            same = [k for k in craftable if item_kind(k) == mind.names[g][5:]]      # oak planks wanted: birch will do
            if same:
                return same[0]
            for i in mind.pre(g):                         # a step towards it that I can make now
                if mind.names[i].startswith("have:") and mind.names[i][5:] in craftable:
                    return mind.names[i][5:]
        if not craftable:
            return None
        new = [k for k in craftable if "have:" + k not in mind.idx or mind.nev[mind.idx["have:" + k]] == 0]
        need = plan_needs(child)
        new = [k for k in new if not spends(k, need)]     # (not out of what my plans need)
        if new:                                           # something I have never made: curiosity
            return new[int(np.random.randint(len(new)))]
        return max(craftable, key=lambda k: mind.R[mind.idx["have:" + k]] if "have:" + k in mind.idx else 0.0)
    if g is not None:
        nodes = [g] + list(mind.pre(g))
        for (e, act), rec in mind.ao.items():
            if e == g and rec[0] >= 2:
                nodes += list(mind._ao_need(rec))
        for i in nodes:
            name = mind.names[i]
            if name.startswith("see:") and name[4:] in seen:
                return name[4:]
        if mind.names[g].startswith("have:") and mind.names[g][5:] in seen:
            return mind.names[g][5:]
        wanted = [mind.names[i][4:] for i in nodes if mind.names[i].startswith("see:")]
        if wanted and kind in ("mine_target", "approach"):      # my plan needs that one: not whatever is in sight
            return wanted[0]                                     # (out of sight: the body says so, I go and look)
    # no plan: what do I expect to get from each thing I see? (learned: this action on that thing gave me ...)
    worth = {}
    for (e, act), rec in mind.ao.items():
        if act != a or rec[0] < 1 or not mind.names[e].startswith("have:"):
            continue
        need = [mind.names[i] for i in mind._ao_need(rec)] if rec[0] >= 2 else []
        for x in seen:
            if "see:" + x in need or "reach:" + x in need:
                p = rec[0] / (rec[2] + 1.0)
                worth[x] = max(worth.get(x, 0.0), p * (max(mind.R[e], 0.0) + 0.3 / np.sqrt(1 + mind.nev[e])))
    im = getattr(child, "imitation", None)
    copy = im.attention(seen, child.age) if im is not None else None
    if copy is not None and np.random.random() < 0.5:              # what I saw someone use draws my eyes
        return copy
    tried = getattr(child, "tried_on", {})
    child.tried_on = tried
    fresh = [x for x in seen if tried.get((a, x), 0) < 3]          # never really tried this on it: curiosity
    if fresh and (not worth or np.random.random() < 0.3):
        x = fresh[int(np.random.randint(len(fresh)))]
    elif worth:
        x = max(worth, key=worth.get)
    elif seen:
        x = seen[int(np.random.randint(len(seen)))]
    else:
        return None
    tried[(a, x)] = tried.get((a, x), 0) + 1
    return x
