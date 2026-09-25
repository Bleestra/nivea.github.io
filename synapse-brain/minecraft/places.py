"""
The memory of places (hippocampal place and object cells): where I have seen each kind of thing.

Everything the eyes report with a position is remembered - "stone, there", "a crafting table, there",
"water, there" - a few places per kind, the latest and most often seen first. A place is forgotten when I
stand next to it and the thing is not there any more (mined, eaten, walked away). From it the mind gets the
sense "I know where there is X" (concept know:X), and the motor program "go to a place" can be aimed at a
remembered X that the plan needs. Nothing here says which places matter: the mind learns that.

Chests are remembered with what is in them, as I saw it the last time I opened each: from that the mind gets
"I have X put away" (concept stored:X), and "go to a place" can be aimed at the chest that holds what the
plan needs.
"""
import json
import math
import os

PER_KIND = 6          # places kept for each kind of thing
KNOW_RADIUS = 96      # "I know where there is X" - within this distance (blocks)
KNOW_MAX = 12         # how many kinds of remembered things the mind is told about at a time
FLEETING = {"item", "experience_orb", "arrow", "snowball", "egg", "fishing_bobber", "ender_pearl", "falling_block"}


class PlaceMemory:
    def __init__(self):
        self.places = {}          # name -> [[x, y, z, dim, last_seen_age, times]]
        self.chests = {}          # "x,y,z,dim" -> {"at": [x, y, z], "dim": dim, "items": {name: count}, "age": age}

    # ---------------------------------------------------------------- my chests
    def chest(self, info, m, age):
        """I opened a chest: remember where it is and everything that is in it now."""
        at, dim = [int(v) for v in info["at"]], str(m.get("dim", "overworld"))
        self.chests["%d,%d,%d,%s" % (*at, dim)] = {"at": at, "dim": dim, "items": dict(info.get("items") or {}),
                                                   "age": age}

    def chest_gone(self, m):
        """There is no chest where I remember one (broken, burnt): forget it and what was in it."""
        here, dim = m.get("pos"), str(m.get("dim", "overworld"))
        if here:
            for k, c in list(self.chests.items()):
                if c["dim"] == dim and self._dist(c["at"], here) <= 4:
                    del self.chests[k]

    def stored(self):
        """Everything I have put away: {item: count} over all my chests."""
        out = {}
        for c in self.chests.values():
            for k, n in c["items"].items():
                out[k] = out.get(k, 0) + n
        return out

    def where_stored(self, item, m):
        """The nearest chest in my world that holds this item, or None."""
        here, dim = m.get("pos"), str(m.get("dim", "overworld"))
        cs = [c for c in self.chests.values() if c["dim"] == dim and c["items"].get(item)]
        if not cs or not here:
            return None
        return list(min(cs, key=lambda c: self._dist(c["at"], here))["at"])

    def nearest_chest(self, m):
        here, dim = m.get("pos"), str(m.get("dim", "overworld"))
        cs = [c for c in self.chests.values() if c["dim"] == dim]
        return min(cs, key=lambda c: self._dist(c["at"], here)) if cs and here else None

    def update(self, m, age):
        """Remember what I see now; forget what is no longer where I remember it."""
        dim = str(m.get("dim", "overworld"))
        here = m.get("pos") or [*(m.get("xz") or [0, 0])[:1], m.get("y", 64), *(m.get("xz") or [0, 0])[1:]]
        seen_now = set()
        for entry in m.get("seen", []):
            if len(entry) < 6:
                continue
            name, x, y, z = entry[0], int(entry[3]), int(entry[4]), int(entry[5])
            seen_now.add(name)
            if name in FLEETING:                              # a thing lying or flying has no place
                continue
            spots = self.places.setdefault(name, [])
            for s in spots:
                if s[3] == dim and abs(s[0] - x) + abs(s[1] - y) + abs(s[2] - z) <= 4:
                    s[:3] = [x, y, z]
                    s[4], s[5] = age, s[5] + 1
                    break
            else:
                spots.append([x, y, z, dim, age, 1])
                spots.sort(key=lambda s: (-s[4], -s[5]))
                del spots[PER_KIND:]
        if here and len(here) >= 3:                           # standing where I remember something that is not here
            for name, spots in list(self.places.items()):
                if name in seen_now:
                    continue
                spots[:] = [s for s in spots if not (s[3] == dim and self._dist(s, here) < 3.0)]
                if not spots:
                    del self.places[name]

    @staticmethod
    def _dist(s, here):
        return math.sqrt((s[0] - here[0]) ** 2 + (s[1] - here[1]) ** 2 + (s[2] - here[2]) ** 2)

    def nearest(self, name, m):
        """The closest remembered place of this kind of thing in my world, or None."""
        dim = str(m.get("dim", "overworld"))
        here = m.get("pos")
        spots = [s for s in self.places.get(name, []) if s[3] == dim]
        if not spots or not here:
            return None
        s = min(spots, key=lambda s: self._dist(s, here))
        return [s[0], s[1], s[2]] if self._dist(s, here) <= KNOW_RADIUS * 2 else None

    def known(self, m):
        """Kinds of things I remember a place of, not in sight now, nearest first."""
        here, dim = m.get("pos"), str(m.get("dim", "overworld"))
        if not here:
            return []
        visible = {e[0] for e in m.get("seen", [])}
        rows = []
        for name, spots in self.places.items():
            if name in visible:
                continue
            d = min((self._dist(s, here) for s in spots if s[3] == dim), default=None)
            if d is not None and d <= KNOW_RADIUS:
                rows.append((d, name))
        return [n for _, n in sorted(rows)[:KNOW_MAX]]

    def count(self):
        return sum(len(v) for v in self.places.values())

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"places": self.places, "chests": self.chests}, f)

    def load(self, path):
        if os.path.exists(path):
            d = json.load(open(path, encoding="utf-8"))
            if "places" in d and isinstance(d.get("chests"), dict):
                self.places, self.chests = d["places"], d["chests"]
            else:                                             # before chests were remembered
                self.places = d
