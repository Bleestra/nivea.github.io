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
KINDS = ["zombie", "creeper", "cat", "mycat", "carer", "hostile", "animal", "villager", "golem"]
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


class MCChild(Child):
    def __init__(self, n_actions, seed=0):
        super().__init__(n_actions, seed=seed, taste=MC_TASTE, items=("log", "cobble", "food", "fish", "rotten_flesh"),
                         eat_action=6, wait_action=4, kinds=KINDS)
        self.m = {}
        self.mind.min_desire = float(os.environ.get("MIN_DESIRE_MC", "0.2"))
        base = self.mind.flat.cells

        def cells(obs):                       # the striatum also knows what I have and what is around (concepts)
            c = base(obs)
            extra = [_h(31, zlib.crc32(k.encode()), min(int(v), 3)) for k, v in self._concepts.items() if v]
            return np.concatenate([c, np.array(extra, np.int64)]) if extra else c
        self.mind.flat.cells = cells
        self._concepts = {}
        # sensations and places are means, not things to want for themselves
        self.mind.means_only = ("see:", "reach:", "walls", "saw:", "deep", "underground", "stuck", "free", "indoors", "sky",
                                "near:", "day", "in:", "can_craft:")

    def senses(self, o):
        self._concepts = self.concepts(o)
        return super().senses(o)

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
        for name, d in self.m.get("seen", []):                                        # what my eyes see now
            s["see:" + name] = 1
            if d <= 4:
                s["reach:" + name] = 1                                                 # ... and can touch
        if (self.m.get("fev") or {}).get("trades"):
            s["saw:trades"] = 1
        tr = (self.m.get("fev") or {}).get("traded")
        if tr:
            s["traded"] = s.get("traded", 0) + 1
        return s


class Body:
    """Keeps what the bridge needs to know between two moments (health before, fatigue, ...)."""

    def __init__(self):
        self.hp, self.fish, self.fatigue, self.t, self.nausea, self.prev_items = 20, 0, 0, 0, 0, {}

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
            cause = min(((k, d) for k, _, d in near if k in ("zombie", "creeper", "hostile")), key=lambda x: x[1], default=("world", 0))[0]
            hurt.append(("self", 0, int(round(self.hp - hp)), cause))
        self.hp = hp
        if act == 24 and night:
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
                    "died": bool(m.get("died")), "slept": act == 24 and night, "placed": None, "got": got,
                    "cat_with_carer": False}}
        self.fish = fish
        return o


def save(child, path):
    os.makedirs(path, exist_ok=True)
    child.mind.save(os.path.join(path, "mind.npz"))
    with open(os.path.join(path, "limbic.pkl"), "wb") as f:
        pickle.dump(child.limbic, f)
    with open(os.path.join(path, "age.txt"), "w") as f:
        f.write(str(child.age))


def load(child, path):
    if not os.path.exists(os.path.join(path, "limbic.pkl")):
        return False
    child.mind.load(os.path.join(path, "mind.npz"))
    with open(os.path.join(path, "limbic.pkl"), "rb") as f:
        child.limbic = pickle.load(f)
    with open(os.path.join(path, "age.txt")) as f:
        child.age = int(f.read())
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


def attention(child, a, m):
    """What a motor program is aimed at - chosen by the brain: the thing the current plan needs,
    else what I have never seen (novelty draws the eyes), else what I value most; home = the
    place I am most attached to."""
    kind = MOTOR.get(a)
    if kind is None or kind == "explore":
        return None
    mind, L = child.mind, child.limbic
    if kind == "goto_place":
        if not L.attach_place:
            return None
        (x, z), _ = max(L.attach_place.items(), key=lambda kv: kv[1])
        return [int(x), int(z)]
    seen = [name for name, _ in m.get("seen", [])]
    g = mind.goal
    if kind == "craft_target":
        craftable = m.get("craftable", [])
        if g is not None and mind.names[g].startswith("have:"):
            if mind.names[g][5:] in craftable or not craftable:
                return mind.names[g][5:]
            for i in mind.pre(g):                         # a step towards it that I can make now
                if mind.names[i].startswith("have:") and mind.names[i][5:] in craftable:
                    return mind.names[i][5:]
        if not craftable:
            return None
        new = [k for k in craftable if "have:" + k not in mind.idx or mind.nev[mind.idx["have:" + k]] == 0]
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
