"""
Reading the guide (guide/pages.jsonl, the Minecraft Wiki) into what the mind can use.

Every sentence that names things of the game is read for five kinds of knowledge, in the mind's own concepts:
  made of      "Torches are crafted from sticks and coal"          have:torch <- have:stick + have:coal
  mined with   "Iron ore can be mined with a stone pickaxe"        have:raw_iron <- have:stone_pickaxe + see:iron_ore
  needs        "A nether portal requires obsidian"                 have:X <- have:obsidian
  found in     "Diamond ore is found deep underground"             see:diamond_ore <- deep
  drops        "Cows drop leather and beef"                        have:leather <- see:cow
  danger       "Creepers explode when near the player"             pain:creeper <- near:creeper
Honest limit: sentence patterns over a dictionary of the game's names, not understanding of English. What it
gets is a weak belief (mind.tell), confirmed or overturned by experience - as anything read.

The book is consulted like a person consults a guide: about one thing, when it is needed (GuideBook.about).
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(HERE, "guide", "pages.jsonl")
INDEX = os.path.join(HERE, "guide", "knowledge.json")
PLACES = [(r"\bnether\b", "in:the_nether"), (r"\bthe end\b|\bend dimension\b", "in:the_end"),
          (r"\bdeep\b|\bdeepslate\b|\by ?[=<]?\s*-\d+|\bbelow y|\blow(er)? levels?\b", "deep"),
          (r"\bunderground\b|\bcaves?\b|\bmines?haft", "underground"),
          (r"\bsurface\b|\bforests?\b|\bplains\b|\btaiga\b|\bjungle", "sky"),
          (r"\bocean|\brivers?\b|\bwater\b|\blakes?\b", "see:water"), (r"\bvillages?\b", "see:villager")]
HOSTILE_KIND = {"zombie": "zombie", "husk": "zombie", "drowned": "zombie", "creeper": "creeper"}
NOT_THINGS = {"air", "cave_air", "void_air", "light", "barrier", "structure_void", "structure_block", "jigsaw",
              "command_block", "chain_command_block", "repeating_command_block", "debug_stick", "knowledge_book",
              "test_block", "test_instance_block", "marker", "moving_piston", "piston_head", "fire", "water", "lava",
              "end", "area_effect_cloud", "interaction", "text_display", "item_display", "block_display", "item",
              "player", "painting", "item_frame", "arrow", "egg"}


class Lexicon:
    """The game's names in English (and plurals), longest first: "iron pickaxe" before "iron"."""

    def __init__(self, rules):
        names = {}
        for kind in ("blocks", "recipes", "entities"):
            for n in rules.get(kind, {}):
                if n not in NOT_THINGS:
                    names[n.replace("_", " ")] = n
        extra = {"wood": "oak_log", "logs": "oak_log", "log": "oak_log", "planks": "oak_planks", "sticks": "stick",
                 "pickaxe": "wooden_pickaxe", "iron": "raw_iron", "diamonds": "diamond", "coal": "coal",
                 "cobble": "cobblestone", "bed": "white_bed", "wool": "white_wool", "boat": "oak_boat",
                 "sword": "wooden_sword", "axe": "wooden_axe"}
        names.update({k: v for k, v in extra.items() if k not in names})
        self.entities = set(rules.get("entities", {}))
        self.item_of = names
        # one alternation, longest names first: the leftmost, then longest name wins (one pass per sentence)
        alt = "|".join(re.escape(p) for p in sorted(names, key=len, reverse=True))
        self.rx = re.compile(r"\b(" + alt + r")(?:e?s)?\b")

    def mentions(self, text):
        return [(m.start(), self.item_of[m.group(1)]) for m in self.rx.finditer(text.lower())]

    def spans(self, text):
        return [(m.start(), m.end(), self.item_of[m.group(1)]) for m in self.rx.finditer(text.lower())]


WEAPON = re.compile(r"_(sword|axe)$")
FIGHT = re.compile(r"\b(kill\w*|fight\w*|defend\w*|defen[cs]e|combat|protect\w*|fend\w* off|attack\w*|strike|slay\w*)\b")
FOES = [(r"\b(zombies?|husks?|drowned)\b", ("zombie",)), (r"\bcreepers?\b", ("creeper",)),
        (r"\b(skeletons?|spiders?|endermen|enderman|witch\w*|pillagers?|slimes?)\b", ("hostile",)),
        (r"\b(mobs?|monsters?|hostile)\b", ("hostile", "zombie"))]        # "monsters": zombies are monsters too
EDITION = re.compile(r"\b(bedrock|java|pocket|education|legacy console|console)\s+edition")   # a version, not a block
CLAUSE = re.compile(r"[;:!?()]|,\s+(?:and|but|which|so|while|because|although|if|when|as|or)\b"
                    r"|\s(?:which|who|because|although|if|when|while|so that)\b")
NOT_SUBJECT = re.compile(r"\b(you|we|they|i|one|players?|it|he|she|not|n't|never|no|without|don't|doesn't)\b|[,;:]")


def clause_end(low, start):
    """Where the clause that starts here ends: what follows belongs to another thought."""
    m = CLAUSE.search(low, start)
    return m.start() if m else len(low)


def subject_of(low, spans, verb_start, relative=False):
    """The thing that is the subject of the verb: named right before it ("torches require ..."), not a person
    ("you need ...") and not denied ("... does not need ..."). "..., which is needed" refers back to it."""
    before = [s for s in spans if s[1] <= verb_start]
    if not before:
        return None
    s = before[-1]
    between = low[s[1]:verb_start]
    if relative:
        between = re.sub(r"^\s*,?\s*(which|that)\b", "", between)
    if len(between) > 30 or NOT_SUBJECT.search(between):
        return None
    return s[2]


def shelter_claims(low, ms):
    """What the guide says about getting through the night: a shelter (walls and a roof) and light keep mobs away."""
    out = []
    if re.search(r"\b(shelters?|houses?|base|hut|walls?|bunker)\b", low) and \
            re.search(r"\b(night|mobs?|monsters?|hostile|safe|survive|spawn\w*)\b", low):
        out.append(("safe_night", ["sheltered"]))                    # "build a shelter before the night"
        mats = [n for _, n in ms if re.search(r"dirt|cobblestone|planks|log|stone|wood|brick|glass", n)]
        if mats:
            out.append(("sheltered", ["have:" + x for x in mats[:2]]))
    if re.search(r"\btorch", low) and re.search(r"\b(spawn\w*|mobs?|monsters?|safe|dark\w*)\b", low):
        out.append(("safe_night", ["have:torch"]))                   # "light the area: mobs cannot spawn"
    return out


def read_sentence(s, lex, rules):
    """-> [(target, [preconditions])] in the mind's concepts."""
    low = EDITION.sub("edition", s.lower())
    ms = lex.mentions(low)
    shelter = shelter_claims(low, ms)                          # these sentences seldom name a thing of the game
    if not ms:
        return shelter
    spans = lex.spans(low)
    names = [m for _, m in ms]
    first = names[0]
    out = list(shelter)

    def after(k):                                              # the things named after the verb, in its clause
        end = clause_end(low, k.end())
        return [n for p, n in ms if k.end() < p < end]
    m = re.search(r"\b(crafted|made|created|smelted|cooked)\s+(from|with|using|out of|by combining)\b", low)
    if m:
        heads = [n for p, n in ms if p < m.start()]
        tails = after(m)
        if heads and tails:
            out.append(("have:" + heads[-1], ["have:" + t for t in tails if t != heads[-1]][:4]))
    m = re.search(r"\b(mined|obtained|broken|collected|harvested)\b[^.]*?\b(with|using|requires?)\b", low)
    if m and first in rules.get("blocks", {}):
        tools = [n for p, n in ms if p > m.start() and re.search(r"_(pickaxe|axe|shovel|hoe|sword)$|^shears$", n)]
        drops = rules["blocks"][first].get("drops") or [first]
        if tools:
            out.append(("have:" + drops[0], ["have:" + tools[0], "see:" + first]))
    m = re.search(r"\b(requires?|needs?)\b", low)                               # "X requires Y": X <- Y
    r = re.search(r"\b(?:is|are)\s+(?:\w+\s+)?(?:needed|necessary|required)\s+(?:to|for|in order to)\b", low)
    k = m if m and (not r or m.start() < r.start()) else r                      # "Y is needed to get X": X <- Y
    if k and not out:
        head = subject_of(low, spans, k.start(), relative=k is r)
        tails = after(k)
        if head and tails:
            if k is r:
                out.append(("have:" + tails[0], ["have:" + head]))
            else:
                out.append(("have:" + head, ["have:" + t for t in tails if t != head][:3]))
    if re.search(r"\b(is|are|can be)\s+(\w+\s+)?(found|generated|generates|located|spawns?|occurs?)\b", low) \
            and first in rules.get("blocks", {}) or re.search(r"\b(spawns?|found)\b", low) and first in lex.entities:
        places = [c for rx, c in PLACES if re.search(rx, low)]
        if places:
            out.append(("see:" + first, places[:2]))
    # "cows drop leather": drop as what a creature does - not "a drop down", not "for a cat to drop a gift"
    m = re.search(r"(?<!to )(?<!a )(?<!the )\b(drops?|dropped)\b(?!\s+(?:down|off|into|onto|to|from|out)\b)", low)
    who = [sp[2] for sp in spans if m and sp[1] <= m.start()]
    if m and who and who[-1] in lex.entities:
        for n in after(m):
            if n not in lex.entities:
                out.append(("have:" + n, ["see:" + who[-1]]))
    # "have a weapon (a sword or an axe) to kill monsters": a monster falls to the one who holds a weapon
    weapons = [n for _, n in ms if WEAPON.search(n)]
    if weapons and FIGHT.search(low):
        foes = list(dict.fromkeys(k for rx, ks in FOES if re.search(rx, low) for k in ks))
        w = next((x for x in weapons if x.endswith("_sword")), weapons[0])
        for k in foes:
            out.append(("killed:" + k, ["hold:" + w]))
        if foes:
            out.append(("hold:" + w, ["have:" + w]))                     # to hold it, I must have it
    if first in lex.entities and re.search(r"\b(explodes?|explosion|attacks?|hostile|damages?|deals?\s+\d|hurts?)\b", low):
        kind = HOSTILE_KIND.get(first, "hostile")
        out.append(("pain:" + kind, ["near:" + kind]))
    return [(t, [p for p in ps if p != t]) for t, ps in out if ps]


def build():
    """Read the whole guide once into an index: concept -> what the guide says about getting it."""
    rules = json.load(open(os.path.join(HERE, "knowledge", "sim_rules.json"), encoding="utf-8"))
    lex = Lexicon(rules)
    index = {}
    for line in open(PAGES, encoding="utf-8"):
        page = json.loads(line)
        own = page["title"].lower()
        for sent in re.split(r"(?<=[.!?])\s+|\n+", page["text"]):
            if len(sent) < 15 or len(sent) > 400 or sent.startswith("=="):
                continue
            for target, pres in read_sentence(sent, lex, rules):
                key = json.dumps([target, sorted(pres)])
                row = index.setdefault(target, {}).setdefault(key, {"pres": pres, "n": 0, "said": sent.strip(), "page": page["title"]})
                row["n"] += 1
                if target.split(":")[-1].replace("_", " ") in own:           # what an item's own article says wins
                    row["n"] += 3
                    row["said"], row["page"] = sent.strip(), page["title"]
    compact = {t: sorted(rows.values(), key=lambda r: -r["n"])[:4] for t, rows in index.items()}
    json.dump(compact, open(INDEX, "w", encoding="utf-8"), ensure_ascii=False)
    return compact


class GuideBook:
    def __init__(self):
        self.index, self.stamp, self.building = {}, 0.0, False
        self.refresh()

    def refresh(self):
        """Take the latest reading of the guide; if the guide grew (the download may still be going), read it
        again in the background - the brain goes on living meanwhile."""
        if os.path.exists(INDEX) and os.path.getmtime(INDEX) > self.stamp:
            try:
                self.index, self.stamp = json.load(open(INDEX, encoding="utf-8")), os.path.getmtime(INDEX)
            except Exception:
                pass
        if not os.path.exists(PAGES) or self.building:
            return
        if not os.path.exists(INDEX) or os.path.getmtime(PAGES) > os.path.getmtime(INDEX) + 300:
            import threading

            def work():
                try:
                    build()
                finally:
                    self.building = False
            self.building = True
            threading.Thread(target=work, daemon=True).start()

    def about(self, concept, most=2):
        """What the guide says about getting this: [(claim, the sentence, the page)]."""
        rows = self.index.get(concept, [])
        best = rows[0]["n"] if rows else 0              # a passing remark does not outweigh the thing's own article
        return [((concept, r["pres"]), r["said"], r["page"]) for r in rows[:most] if r["n"] >= max(1, best / 2)]
