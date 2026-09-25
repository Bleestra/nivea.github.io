"""
Telemetry: what each Synapse does, feels, sees and achieves - written to files the dashboard reads.

  live.json      the present: who, where, health, what he feels and wants, the last decisions and events,
                 the scores, what the eyes recognise in each zone of the picture (updated ~2 times a second)
  live.jpg       what he sees right now
  events.jsonl   his life: advancements, first-time items, deaths, words, what the eyes learned to recognise
  series.jsonl   a sample every 100 moments: the curves for comparing lives

Only observation: nothing here takes part in any decision.
"""
import json
import os
import time
from collections import deque

from actions import ACTIONS, ru

TIERS = ["wooden", "stone", "iron", "golden", "diamond", "netherite"]
TIER_WEIGHT = {"wooden": 1, "stone": 2, "iron": 3, "golden": 3, "diamond": 4, "netherite": 5}


def tech_level(known):
    """The highest tool or armour tier ever held (0 nothing, 1 wood ... 5 netherite)."""
    best = 0
    for k in known:
        for t, w in TIER_WEIGHT.items():
            if k.startswith(t + "_") and k.rsplit("_", 1)[-1] in ("pickaxe", "sword", "axe", "shovel", "hoe", "helmet",
                                                               "chestplate", "leggings", "boots"):
                best = max(best, w)
    return best


def _write(path, data, binary=False):
    """Replace a file at once (the dashboard never sees half of it); on Windows retry if it is being read."""
    tmp = path + ".tmp"
    with open(tmp, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})) as f:
        f.write(data)
    for _ in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.02)


class Telemetry:
    def __init__(self, directory, senses):
        self.dir = directory
        os.makedirs(directory, exist_ok=True)
        self.senses = senses
        self.decisions = deque(maxlen=200)
        self.events = deque(maxlen=200)
        self.t_live = self.t_frame = 0.0
        self.step = 0
        self.rewards = deque(maxlen=500)
        self.known_seen = set()
        self.last_thought, self.t_thought = "", 0.0
        self.pos = None
        self.fail_rate, self.fails = None, {}
        self.pace, self.times = {}, deque(maxlen=60)
        path = os.path.join(directory, "events.jsonl")
        if os.path.exists(path):                              # the dashboard shows a whole life, across restarts
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f.readlines()[-200:]:
                        self.events.append(json.loads(line))
            except Exception:
                pass

    def event(self, kind, text, **extra):
        e = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "step": self.step, "kind": kind, "text": text, **extra}
        self.events.append(e)
        with open(os.path.join(self.dir, "events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def moment(self, m, a, target, say, reward, hud, frame, seeing, child, me):
        self.step += 1
        now = time.time()
        self.times.append(now)
        for k, v in (m.get("_pace") or {}).items():               # where the time of a moment goes
            if isinstance(v, (int, float)):
                self.pace[k] = round(self.pace.get(k, v) * 0.8 + v * 0.2, 1)
        if len(self.times) > 5:
            self.pace["moments_per_s"] = round((len(self.times) - 1) / max(1e-6, self.times[-1] - self.times[0]), 2)
        self.rewards.append(float(reward))
        feel = hud.get("feeling", "") if hud else ""
        goal = hud.get("goal", "") if hud else ""
        act = m.get("act")                                     # the body felt whether my last action did anything
        if act:
            for d in reversed(self.decisions):
                if d["a"] == act.get("a") and "ok" not in d:
                    d["ok"] = bool(act.get("ok", True))
                    if not d["ok"]:
                        d["why"] = act.get("why", "")
                    break
        inner = m.get("_events", [])
        for kind, text in inner:
            self.event(kind, text)
        self.decisions.append({"t": time.strftime("%H:%M:%S"), "step": self.step, "a": a, "action": ru(a),
                               "raw": ACTIONS[a] if a < len(ACTIONS) else str(a), "target": target, "goal": goal,
                               "feeling": feel.split(" — ")[0][:60], "reward": round(float(reward), 3),
                               "hp": m.get("health"), "food": m.get("food")})
        # what happened in his life
        for adv_id, title in m.get("advancements", []):
            self.event("advancement", f"Достижение: {title}", id=adv_id)
        if m.get("died"):
            self.event("death", f"Погиб: {m['died']}")
        if say and not say.startswith("Понял: ") and not any(say == text or say.endswith(text) for _, text in inner):
            self.event("say", say)
        for what in ("traded", "read"):
            v = (m.get("fev") or {}).get(what)
            if v:
                self.event(what, ("Выменял: " if what == "traded" else "Прочитал: ") + str(v)[:120])
        if me is not None:
            for k in me.me.get("known_items", {}):
                if k not in self.known_seen:
                    if self.step > 1:
                        self.event("discovery", f"Впервые: {k}", item=k)
                    self.known_seen.add(k)
        if seeing is not None and self.step % 500 == 0:
            for name, right, count in seeing.rec.known():
                key = "eyes:" + name
                if right >= 0.8 and key not in self.known_seen:
                    self.known_seen.add(key)
                    self.event("vision", f"Научился узнавать: {name} ({right * 100:.0f}%)", item=name)
        if child is not None and now - self.t_thought > 5:
            try:
                from mind_bridge import ru_thought

                self.last_thought, self.t_thought = ru_thought(child.mind), now
            except Exception:
                pass
        fails = m.get("_fails")
        if fails:
            self.fails = fails
            tries = sum(v[0] for v in fails.values())
            self.fail_rate = round(sum(v[1] for v in fails.values()) / tries, 3) if tries else None
        if self.step % 100 == 0:
            self._sample(m, seeing, child, me)
        self._last = (m, hud, seeing, child, me)
        if now - self.t_live > 0.5:
            self.t_live = now
            self._live(m, hud, seeing, child, me)
        if frame is not None and now - self.t_frame > 0.5:
            self.t_frame = now
            import cv2

            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                _write(os.path.join(self.dir, "live.jpg"), jpg.tobytes(), binary=True)

    def scores(self, seeing, child, me):
        known = (me.me.get("known_items", {}) if me else {})
        deaths = len(me.me.get("deaths", [])) if me else 0
        age = int(child.age) if child is not None else self.step
        return {"advancements": len(me.me.get("advancements", [])) if me else 0,
                "items": len(known), "tech": tech_level(known), "deaths": deaths,
                "explored": len(me.me.get("places", [])) if me else 0,
                "concepts": len(child.mind.names) if child is not None else 0,
                "age": age, "life_avg": round(age / (deaths + 1)),
                "vision": round(seeing.rec.acc, 3) if seeing is not None else None,
                "places": child.places.count() if child is not None and hasattr(child, "places") else 0,
                "copied": child.imitation.copied if child is not None and hasattr(child, "imitation") else 0,
                "fail_rate": self.fail_rate,
                "reward_avg": round(sum(self.rewards) / max(1, len(self.rewards)), 4)}

    def _sample(self, m, seeing, child, me):
        s = {"t": time.time(), "step": self.step, **self.scores(seeing, child, me), "hp": m.get("health"), "food": m.get("food")}
        with open(os.path.join(self.dir, "series.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(s) + "\n")

    def _live(self, m, hud, seeing, child, me):
        emotions = {}
        stage = ""
        if child is not None:
            from limbic import NAMES

            L = child.limbic
            emotions = {NAMES.get(k, k): round(float(v), 2) for k, v in sorted(L.e.items(), key=lambda kv: -kv[1])[:8] if v > 0.05}
            stage = hud.get("stage", "") if hud else ""
        vision = None
        if seeing is not None and seeing.last is not None:
            vision = {**seeing.stats(),
                      "zones": [[n, d, round(c, 2), k] for n, d, c, k in seeing.last["zones"]],
                      "labels": [[str(x[0]), x[1]] for x in (seeing.last.get("labels") or [])]}
        items = m.get("items", {})
        live = {"t": time.time(), "online": True, "name": (me.me["name"] if me else "Synapse"), "senses": self.senses,
                "step": self.step, "stage": stage, "lived": hud.get("lived", "") if hud else "", "feeling": hud.get("feeling", "") if hud else "",
                "goal": hud.get("goal", "") if hud else "", "thought": self.last_thought, "emotions": emotions,
                "hp": m.get("health"), "food": m.get("food"), "pos": [*(m.get("xz") or [0, 0]), m.get("y")],
                "dim": m.get("dim"), "held": m.get("held"),
                "inventory": dict(sorted(((k, v) for k, v in items.items()), key=lambda kv: -kv[1])[:36]),
                "decisions": list(self.decisions)[-60:], "events": list(self.events)[-60:],
                "scores": self.scores(seeing, child, me), "vision": vision,
                "action_use": self._action_use(),
                "development": m.get("_development"),
                "pace": self.pace,
                "fails": [[ru(ACTIONS.index(k)) if k in ACTIONS else k, v[0], v[1], v[2]]
                          for k, v in sorted(self.fails.items(), key=lambda kv: -kv[1][1])[:10] if v[1]],
                "places_known": (child.places.known(m) if child is not None and hasattr(child, "places") else []),
                "memory": self._memory(child, m), "intent": m.get("_intent")}
        _write(os.path.join(self.dir, "live.json"), json.dumps(live, ensure_ascii=False))

    @staticmethod
    def _memory(child, m):
        """How much the mind holds: concepts, links, moments lived, skill synapses, chests (it all grows)."""
        if child is None:
            return None
        mind = child.mind
        ep = getattr(mind, "episodic", None)
        pl = getattr(child, "places", None)
        return {"concepts": len(mind.names), "links": int(sum(len(i) for i, _ in mind.cols.values())),
                "moments": ep.n if ep is not None else None, "skills_gb": round(mind.G.nbytes / 2 ** 30, 2),
                "chests": len(pl.chests) if pl is not None else 0, "stored": m.get("_stored") or {},
                "bag_free": m.get("free_slots")}

    def _action_use(self):
        c = {}
        for d in self.decisions:
            c[d["action"]] = c.get(d["action"], 0) + 1
        return dict(sorted(c.items(), key=lambda kv: -kv[1])[:12])

    def flush(self):
        """The body went away: write the very last state (not the one of half a second ago)."""
        if getattr(self, "_last", None):
            self._live(*self._last)

    def offline(self):
        path = os.path.join(self.dir, "live.json")
        try:
            live = json.load(open(path, encoding="utf-8"))
            live["online"] = False
            _write(path, json.dumps(live, ensure_ascii=False))
        except Exception:
            pass
