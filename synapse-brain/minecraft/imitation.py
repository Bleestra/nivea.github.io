"""
Mirror neurons: learning by watching a person (or another Synapse).

The body reports what it saw someone do nearby - broke a block (with what in hand), placed a block, hit a
being, ate something. From that, as in a child:
  - social value: what people use and eat is interesting to have (the tool in their hand, the block they
    placed, the food they ate) - a small expected value, not an order;
  - a belief: "breaking X goes with holding T" (what I saw) - weak, experience confirms or overturns it;
  - the joy of imitation (innate in infants): doing the same thing myself soon after I saw it is pleasant,
    once for each thing I saw.
Only the caregiver ("carer") and other Synapses ("peer") are watched; what to copy, and when, the mind
decides. Nothing here says "build a house" - if someone builds one in front of him, he may try.
"""

MEMORY = 6000        # moments an observed deed stays fresh enough to imitate
SOCIAL_VALUE = 0.4   # how interesting a thing becomes after seeing someone use it
JOY = 0.4            # the pleasure of doing what I saw done


class Imitation:
    def __init__(self):
        self.seen = []              # [age, who, name, act, what, tool, imitated]
        self.valued = set()
        self.salient = {}           # thing -> age last seen used by someone (draws attention)
        self.copied = 0

    def moment(self, m, child, age):
        """Returns (extra reward, words for the diary) for this moment."""
        mind = child.mind
        notes, reward = [], 0.0
        for kind, name, act, what, tool in m.get("watched", []):
            if kind not in ("carer", "peer"):
                continue
            self.seen.append([age, kind, name, act, what, tool, False])
            self.salient[what] = age
            if tool:
                self.salient[tool] = age
            values = {}
            for thing in (tool, what if act in ("placed", "ate") else None):
                if thing and thing not in self.valued:
                    self.valued.add(thing)
                    values["have:" + thing] = SOCIAL_VALUE
            claims = []
            if act == "broke" and tool:
                claims.append(("broke:" + what, ["have:" + tool, "see:" + what]))
            if claims or values:
                mind.tell(claims, values, source="видел у " + name)
            verb = {"broke": "сломал", "placed": "поставил", "attacked": "ударил", "ate": "съел"}.get(act, act)
            notes.append(f"видел: {name} {verb} {what}" + (f" ({tool} в руке)" if tool else ""))
        self.seen = [s for s in self.seen if age - s[0] <= MEMORY]
        mine = self._my_deeds(m)
        for s in self.seen:
            if s[6]:
                continue
            if (s[3], s[4]) in mine or (s[5] and s[5] == m.get("held") and (s[3], s[4]) in mine):
                s[6] = True
                reward += JOY
                self.copied += 1
                notes.append(f"повторил за {s[2]}: {s[3]} {s[4]}")
        return reward, notes

    @staticmethod
    def _my_deeds(m):
        """What I did this moment, in the same words: broke X, placed X, attacked X, ate X."""
        fev = m.get("fev") or {}
        deeds = set()
        for block, _ in fev.get("broke", []):
            deeds.add(("broke", block))
        if fev.get("ate"):
            deeds.add(("ate", fev["ate"]))
        for kind, _, _, by in fev.get("hurt", []):
            if by == "self":
                deeds.add(("attacked", kind))
        act = m.get("act") or {}
        if act.get("ok") and act.get("action") in ("place_block", "use", "pillar_up", "place_chest"):
            for k, v in (m.get("_placed_items") or {}).items():
                deeds.add(("placed", k))
        return deeds

    def attention(self, seen_names, age):
        """Of the things in sight, the one someone used most recently (watching draws the eyes), or None."""
        fresh = [(age - self.salient[n], n) for n in seen_names if n in self.salient and age - self.salient[n] <= MEMORY]
        return min(fresh)[1] if fresh else None

    def state(self):
        return {"seen": self.seen[-50:], "valued": sorted(self.valued), "copied": self.copied}

    def load(self, st):
        self.seen, self.valued, self.copied = st.get("seen", []), set(st.get("valued", [])), st.get("copied", 0)
