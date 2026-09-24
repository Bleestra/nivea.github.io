"""
Reading: text -> beliefs in the mind (language areas -> prefrontal/hippocampal chain synapses).

A child who reads "to get a diamond you need an iron pickaxe" does not KNOW it yet - it believes it.
Here reading writes weak beliefs into the same chain synapses experience uses: a told precondition
starts as if it had been seen a few times, and every real experience then confirms or overrides it.
Words saying something is precious ("самый ценный", "лучший") set an expected value for it.

Honest limit: this 'language area' is a small dictionary and two sentence patterns
("чтобы X, нужно Y", "X лежит глубоко"), not real language understanding.
"""
import re

LEXICON = [  # (pattern, concept) - longest phrases first
    (r"алмазн\w*\s+кирк", "have:diamond_pick"), (r"железн\w*\s+кирк", "have:iron_pick"),
    (r"каменн\w*\s+кирк", "have:stone_pick"), (r"деревянн\w*\s+кирк", "have:wood_pick"),
    (r"алмаз(?!н)\w*", "have:diamond"), (r"палк\w*", "have:stick"), (r"верстак\w*", "have:table"),
    (r"печ[ьи]\w*", "have:furnace"), (r"глубок\w*|недр\w*|сердц\w* гор\w*", "deep"), (r"булыжник\w*", "have:cobble"),
]
PRECIOUS = r"ценн|лучш|прочн|драгоцен"
# the same words, for the concept names of the Minecraft body
MC_NAMES = {"have:diamond_pick": "have:diamond_pickaxe", "have:iron_pick": "have:iron_pickaxe",
            "have:stone_pick": "have:stone_pickaxe", "have:wood_pick": "have:wooden_pickaxe", "have:table": "have:crafting_table",
            "have:cobble": "have:cobblestone", "deep": "deep"}


def mentions(text):
    found, t = [], text.lower()
    for pat, concept in LEXICON:
        for m in re.finditer(pat, t):
            if not any(a <= m.start() < b for a, b, _ in found):
                found.append((m.start(), m.end(), concept))
    return [c for _, _, c in sorted(found)]


def read(text, names=None):
    """Returns (claims [(target, [preconditions])], values {concept: expected value}).
    names: optional renaming of concepts for another body (e.g. MC_NAMES)."""
    claims, values = _read(text)
    if names:
        rn = lambda c: names.get(c, c)
        claims = [(rn(t), [rn(p) for p in ps]) for t, ps in claims]
        values = {rn(c): v for c, v in values.items()}
    return claims, values


def _read(text):
    claims, values = [], {}
    for sent in re.split(r"[.!?\n]+", text):
        s = sent.lower().strip()
        if not s:
            continue
        if "чтобы" in s and re.search(r"нуж|требу|надо", s):
            head, _, tail = re.split(r"(нуж\w*|требу\w*|надо)", s, maxsplit=1)
            target, pres = mentions(head), mentions(tail)
            if target and pres:
                claims.append((target[-1], [p for p in pres if p != target[-1]]))
        elif re.search(r"лежат|лежит|находят|встречаются", s):
            ms = mentions(s)
            if len(ms) >= 2:                                   # "алмазы лежат глубоко": where they are
                claims.append((ms[0], ms[1:]))
        if re.search(PRECIOUS, s):
            for c in mentions(s):
                if c.startswith("have:"):                          # things are precious, places are not
                    values[c] = 1.0
    return claims, values
