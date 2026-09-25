"""
Understanding what the caregiver says: the names of things, explanations and requests.

A small language area, honest about its size. It knows the name of every item and block of the game (in
Russian and English, with Russian endings: "кирка / кирку / кирки"), and three kinds of sentences:

  explanation  "чтобы получить булыжник, нужна кирка" / "булыжник делают из камня" / "to make X you need Y"
               -> a belief in the mind (weak, experience confirms it), as from a book
  request      "сделай кирку" / "добудь дерево" / "принеси рыбу" / "make a pickaxe" / "get wood"
               -> the thing becomes wanted (an expected value): a child wants what a parent asks for;
                  whether and when to do it the mind still decides
  naming       any sentence that mentions a thing -> it is noticed (a little interest)

The tone of the words (warm, alarmed, scolding) is felt separately (feel_bridge), as before.
"""
import json
import os
import re

from personality import RU_NAMES
from recall import BLOCKS_RU

HERE = os.path.dirname(os.path.abspath(__file__))
REQUEST = r"\b(сделай|скрафти|смастери|добудь|добыть|принеси|найди|построй|собери|возьми|выкопай|сруби|make|craft|get|bring|find|build|collect|mine)\w*"
EXPLAIN = r"(чтобы|to make|to get)"
NEED = r"(нуж\w*|надо|требу\w*|need\w*|require\w*)"
FROM = r"\b(дела\w+|получа\w+|добыва\w+|копа\w+|made|crafted|mined|comes?)\s+(из|from|with|of)\b"
EXTRA = {"камень": "stone", "камня": "stone", "камнем": "stone", "угля": "coal", "углём": "coal", "дерева": "oak_log", "железа": "iron_ingot", "дерево": "oak_log", "древесину": "oak_log", "бревно": "oak_log", "доски": "oak_planks",
         "кирку": "wooden_pickaxe", "кирка": "wooden_pickaxe", "меч": "wooden_sword", "еду": "bread", "рыбу": "cod",
         "уголь": "coal", "железо": "iron_ingot", "алмаз": "diamond", "факел": "torch", "кровать": "white_bed",
         "wood": "oak_log", "pickaxe": "wooden_pickaxe", "sword": "wooden_sword", "food": "bread", "fish": "cod"}


def _stem(word):
    w = word.lower()
    return w[:-2] if len(w) > 5 else w[:-1] if len(w) > 3 else w


def _pattern(phrase):
    return r"\b" + r"\s+".join(re.escape(_stem(w)) + r"\w*" for w in phrase.split()) + r"\b"


class Lexicon:
    def __init__(self):
        names = {}
        rules = os.path.join(HERE, "knowledge", "sim_rules.json")
        items = set()
        if os.path.exists(rules):
            r = json.load(open(rules, encoding="utf-8"))
            items = set(r.get("blocks", {})) | set(r.get("recipes", {}))
        for item in items:
            names[item.replace("_", " ")] = item                        # english: "wooden pickaxe"
        for d in (RU_NAMES, BLOCKS_RU):
            for item, ru in d.items():
                names[ru] = item
        names.update(EXTRA)
        # longest phrases first, so "деревянную кирку" wins over "кирку"
        self.entries = sorted(((len(p), re.compile(_pattern(p)), item) for p, item in names.items() if p.strip()),
                              key=lambda e: -e[0])

    def mentions(self, text):
        t, found = text.lower(), []
        for _, rx, item in self.entries:
            for mt in rx.finditer(t):
                if not any(a <= mt.start() < b for a, b, _ in found):
                    found.append((mt.start(), mt.end(), item))
        return [item for _, _, item in sorted(found)]


class Understanding:
    def __init__(self):
        self.lex = Lexicon()

    def hear(self, text):
        """-> (claims [(concept, [preconditions])], values {concept: value}, what I understood in words)."""
        claims, values, said = [], {}, []
        for sent in re.split(r"[.!?\n;]+", text):
            s = sent.lower().strip()
            if not s:
                continue
            things = self.lex.mentions(s)
            if not things:
                continue
            if re.search(EXPLAIN, s) and re.search(NEED, s):
                head, _, tail = re.split(NEED, s, maxsplit=1)
                target, pres = self.lex.mentions(head), self.lex.mentions(tail)
                if target and pres:
                    claims.append(("have:" + target[-1], ["have:" + p for p in pres if p != target[-1]]))
                    said.append(f"чтобы получить {target[-1]}, нужно {', '.join(pres)}")
                    continue
            m = re.search(FROM, s)
            if m:
                target, source = self.lex.mentions(s[:m.start()]), self.lex.mentions(s[m.end():])
                if target and source:
                    claims.append(("have:" + target[-1], ["have:" + x for x in source if x != target[-1]]))
                    said.append(f"{target[-1]} получают из {', '.join(source)}")
                    continue
            if re.search(REQUEST, s):
                values["have:" + things[0]] = 0.8
                said.append(f"меня просят: {things[0]}")
                continue
            for t in things:                                           # just named: noticed
                values.setdefault("have:" + t, 0.2)
        return claims, values, said
