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
MOB_FRESH = 1500     # how long (moments) a creature's place is worth going to
UNREACH_FRESH = 600  # how long (moments) a place I got stuck on the way to is not set out for again
FLEETING = {"item", "experience_orb", "arrow", "snowball", "egg", "fishing_bobber", "ender_pearl", "falling_block"}


class PlaceMemory:
    def __init__(self):
        self.places = {}          # name -> [[x, y, z, dim, last_seen_age, times]]
        self.chests = {}          # "x,y,z,dim" -> {"at": [x, y, z], "dim": dim, "items": {name: count}, "age": age}
        self.homes = []           # where I was closed in and safe at night: [x, y, z, dim, times, last age]
        self.unreachable = []     # where I set out to and got stuck on the way: [x, z, dim, age]
        self.now = 0

    # ---------------------------------------------------------------- where I could not get
    def could_not_reach(self, at, m, age):
        """I set out for it and got stuck on the way (a cliff, water, a wall): not there again for a while."""
        if not at or len(at) < 2:
            return
        x, z = (at[0], at[2]) if len(at) >= 3 else (at[0], at[1])
        self.unreachable.append([int(x), int(z), str(m.get("dim", "overworld")), age])
        del self.unreachable[:-24]

    def _blocked(self, s, dim):
        return any(u[2] == dim and self.now - u[3] < UNREACH_FRESH and abs(u[0] - s[0]) + abs(u[1] - s[2]) <= 3
                   for u in self.unreachable)

    # ---------------------------------------------------------------- home
    def remember_home(self, m, age):
        """Safe here at night, closed in: a home (the place I come back to). The one I was safe at most is my home."""
        here, dim = m.get("pos"), str(m.get("dim", "overworld"))
        if not here:
            return
        for h in self.homes:
            if h[3] == dim and self._dist(h, here) <= 6:
                h[4], h[5] = h[4] + 1, age
                break
        else:
            self.homes.append([int(here[0]), int(here[1]), int(here[2]), dim, 1, age])
        self.homes.sort(key=lambda h: -h[4])
        del self.homes[3:]

    def hurt_here(self, what, m, age):
        """It hurt here (a fall, fire, water, something that struck me): a place to keep away from."""
        here, dim = m.get("pos"), str(m.get("dim", "overworld"))
        if not here:
            return
        spots = self.places.setdefault("danger:" + what, [])
        spots.append([int(here[0]), int(here[1]), int(here[2]), dim, age, 1])
        del spots[:-PER_KIND]

    def danger_near(self, at, m, radius=4):
        """Did it hurt near this spot before? (the kinds of pain)"""
        dim = str(m.get("dim", "overworld"))
        return [k[7:] for k, spots in self.places.items() if k.startswith("danger:")
                for s in spots if s[3] == dim and self._dist(s, at) <= radius]

    def home(self, m):
        """My home in this world, if I have one not too far away: [x, y, z], or None."""
        here, dim = m.get("pos"), str(m.get("dim", "overworld"))
        hs = [h for h in self.homes if h[3] == dim and (not here or self._dist(h, here) <= 256) and
              not self._blocked(h, dim)]
        return [hs[0][0], hs[0][1], hs[0][2]] if hs else None

    def at_home(self, m):
        h, here = self.home(m), m.get("pos")
        return bool(h and here and math.sqrt(sum((a - b) ** 2 for a, b in zip(h, here))) <= 3)

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
        cs = [c for c in self.chests.values() if c["dim"] == dim and c["items"].get(item) and not self._blocked(c["at"], dim)]
        if not cs or not here:
            return None
        return list(min(cs, key=lambda c: self._dist(c["at"], here))["at"])

    def nearest_chest(self, m):
        here, dim = m.get("pos"), str(m.get("dim", "overworld"))
        cs = [c for c in self.chests.values() if c["dim"] == dim]
        return min(cs, key=lambda c: self._dist(c["at"], here)) if cs and here else None

    def update(self, m, age):
        """Remember what I see now; forget what is no longer where I remember it."""
        dim, self.now = str(m.get("dim", "overworld")), age
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
            alive = len(entry) > 2 and entry[2] == "mob"          # a creature walks away: its place grows old
            for s in spots:
                if s[3] == dim and abs(s[0] - x) + abs(s[1] - y) + abs(s[2] - z) <= 4:
                    s[:3] = [x, y, z]
                    s[4], s[5] = age, s[5] + 1
                    break
            else:
                spots.append([x, y, z, dim, age, 1, alive])
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

    def nearest(self, name, m, age=None):
        """The closest remembered place of this kind of thing in my world, or None - a creature only if seen there
        not long ago (it walks away; a zombie seen days ago is no place to look for food)."""
        dim = str(m.get("dim", "overworld"))
        here = m.get("pos")
        spots = [s for s in self.places.get(name, []) if s[3] == dim and not self._blocked(s, dim) and
                 not (age is not None and len(s) > 6 and s[6] and age - s[4] > MOB_FRESH)]
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
            if name in visible or name.startswith("danger:"):
                continue
            d = min((self._dist(s, here) for s in spots if s[3] == dim), default=None)
            if d is not None and d <= KNOW_RADIUS:
                rows.append((d, name))
        return [n for _, n in sorted(rows)[:KNOW_MAX]]

    def count(self):
        return sum(len(v) for v in self.places.values())

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"places": self.places, "chests": self.chests, "homes": self.homes}, f)

    def load(self, path):
        if os.path.exists(path):
            d = json.load(open(path, encoding="utf-8"))
            if "places" in d and isinstance(d.get("chests"), dict):
                self.places, self.chests = d["places"], d["chests"]
                self.homes = d.get("homes", [])
            else:                                             # before chests were remembered
                self.places = d
