"""
What the Minecraft body reports, turned into concept neurons for the Mind, and the Mind's own words.

The concepts are only the body's plain facts (what I hold, what I wear, do I see the sky, am I
stuck, is it night, am I hungry). Which of them matter for what - "logs come from the surface",
"to get out of a hole, build under yourself" - the Mind learns in its chain and skill synapses.
"""
import re

from personality import RU_NAMES

RU_EXTRA = {"sky": "видеть небо", "free": "свободно двигаться", "stuck": "застрять", "day": "день",
            "fed": "быть сытым", "healthy": "быть здоровым", "underground": "быть под землёй"}


def state_from(m):
    s = {}
    for k, v in m.get("items", {}).items():
        s[("wear:" + k[5:]) if k.startswith("worn:") else ("have:" + k)] = v
    stuck = int(m.get("stuck", 0))
    s["sky"] = int(m.get("sky", 0))
    s["stuck"], s["free"] = stuck, 1 - stuck
    feat = m.get("feat", [])
    s["day"] = 1 - (feat[7] if len(feat) > 7 else 0)
    s["fed"] = int(m.get("food", 20) >= 18)
    s["healthy"] = int(m.get("health", 20) >= 15)
    s["underground"] = int(not s["sky"] and m.get("y", 64) < 55)
    return s


def ru(concept):
    kind, _, what = concept.partition(":")
    if not what:
        return RU_EXTRA.get(kind, kind)
    name = RU_NAMES.get(what, what.replace("_", " "))
    return {"have": f"иметь {name}", "wear": f"носить {name}"}.get(kind, concept)


def ru_thought(mind):
    if mind.goal is None:
        return "Сейчас просто осматриваюсь и пробую новое."
    t = mind.target if mind.target is not None else mind.goal
    chain, parts = mind.reason(mind.val > 0, t)[1], []
    for e, p in chain[:5]:
        parts.append(f"чтобы {ru(mind.names[e])}, нужно {ru(mind.names[p])}")
    head = f"Хочу {ru(mind.names[t])}."
    return " ".join([head] + [p.capitalize() + "." for p in parts] + [f"Сейчас: {ru(mind.names[mind.goal])}."])


def _find(mind, text):
    """Which concept is the question about? Match Russian or English item names."""
    t = text.lower()
    best = None
    for i, n in enumerate(mind.names):
        kind, _, what = n.partition(":")
        if kind != "have":
            continue
        for word in (what, what.replace("_", " "), RU_NAMES.get(what, "")):
            w = word.lower()
            if w and (w in t or (len(w) > 5 and w[:-2] in t)):
                if best is None or len(w) > best[1]:
                    best = (i, len(w))
    return best[0] if best else None


def talk(mind, text):
    """Answer from the Mind's own synapses, or None (then the voice answers)."""
    t = text.lower()
    if re.search(r"о ч[её]м (ты )?дума|что (ты )?делаешь|что задумал|твоя цель", t):
        return ru_thought(mind)
    if re.search(r"что (ты )?умеешь|что (ты )?знаешь о себе|расскажи о себе|кто ты", t):
        tried = [i for i in range(len(mind.names)) if mind.tries[i] >= 2]
        if not tried:
            return "Я ещё почти ничего не пробовал делать сам — всё впереди."
        comp = mind.comp
        good = sorted(tried, key=lambda i: -comp[i])[:3]
        bad = [i for i in sorted(tried, key=lambda i: comp[i])[:2] if i not in good]
        out = "Я Синапс. Лучше всего у меня получается: " + ", ".join(f"{ru(mind.names[i])} ({comp[i] * 100:.0f}%)" for i in good)
        if bad:
            out += ". Хуже всего: " + ", ".join(f"{ru(mind.names[i])} ({comp[i] * 100:.0f}%)" for i in bad)
        return out + f". Я заметил {len(mind.names)} вещей о мире и о себе."
    if re.search(r"как (мне )?(получить|сделать|добыть|скрафтить|достать)|откуда (бер|взять)|что нужно для", t):
        e = _find(mind, t)
        if e is None:
            return None
        lines = mind.why(e)
        if not lines:
            return f"Про «{ru(mind.names[e])}» я пока не понял, что для этого нужно — видел это слишком мало раз."
        out = []
        for line in lines[:5]:
            left, right = line.split(" ← ")
            out.append(f"{ru(left)} ← " + " + ".join(ru(x) for x in right.split(" + ")))
        return "По моему опыту: " + "; ".join(out)
    return None
