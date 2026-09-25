"""
One moment of the grown brain: the body's report in, a motor command out.

Shared by the Minecraft server (brain_server.py) and the simulated world (../agent/minesim.py),
so that what the brain learns in one is the same brain, in the same code, in the other.
"""
import time

import feel_bridge
from mind_bridge import talk as mind_talk

VEXATION = 0.03       # an action that did nothing: a small vexation (the cerebellum's error, wasted effort)
HAND_PAIN = 0.3       # breaking stone, ore... with bare hands (or the wrong tool) hurts the hands; it adds up
DARK_UNEASE = 0.03    # innate: in the dark and exposed (night under the sky, a black cave) - apprehension
EFFORT = 0.0004       # effort: every tick of work costs a little strength (stone by hand, 150 ticks: 0.06;
                      # with a pickaxe, 23 ticks: 0.009) - so tools become worth what they save, by themselves
PLACING = ("place_block", "use", "pillar_up", "place_chest", "place_frame")
PAIN_RU = {"fall": "упал", "hunger": "голод", "drown": "захлебнулся", "burn": "обжёгся", "prick": "укололся",
           "blast": "взрыв", "suffocation": "задыхаюсь", "cold": "замерзаю", "poison": "отрава", "void": "пустота",
           "world": "больно", "hit": "ударили", "hands": "руки"}


class Grown:
    def __init__(self, child, me=None, voice=None, log=print):
        self.child, self.me, self.voice, self.log = child, me, voice, log
        self.body = feel_bridge.Body()
        self.a_prev, self.front_prev, self.inv_prev, self.last_felt = None, 0, {}, 0.0
        self.clock = time.time
        from recall import Recall
        from understanding import Understanding

        self.recall = Recall()                                  # remembering the reference book when surprised
        self.understanding = Understanding()                    # the names of things, explanations, requests
        self.fails = {}                                         # action -> [tries, failed, last reason]
        self.sore = 0.0                                         # how sore my hands are (fades with time)
        self.looked_up = {}                                     # what I looked up after a failure -> when
        self.ticks_before = None
        self.items_before = {}
        self.plan_at_act = None                                 # the goal I had when I did the last action
        self.intent_seen = -1                                   # the last change of my intention already told
        mind, dev = child.mind, child.development
        if dev.guide is not None:                              # what I read before: what helps, and what was read
            for concept in dev.read:
                claims = [c for c, _, _ in dev.guide.about(concept)]
                mind.mark_told(claims)
                mind.tell_helps(claims)
        for block, info in self.recall.blocks.items():         # the reference book: the right tool makes mining work
            tools, drops = info.get("tools") or [], info.get("drops") or []
            if tools and drops:
                mind.tell_helps([("have:" + drops[0], ["have:" + tools[0]])], new=False)

    def new_body(self):
        """Reconnected: the senses start again (the brain and memory stay)."""
        self.body = feel_bridge.Body()
        self.a_prev, self.front_prev, self.inv_prev = None, 0, {}

    def decide(self, m, frame=None, force=None):
        child, me = self.child, self.me
        say, reward = None, float(m.get("reward", 0.0))
        events = m.setdefault("_events", [])                  # for the dashboard: what happened inside
        if me:                                                # the reward comes from inside
            reward, say = me.feel(m)
        # --- did my last action do anything? (efference copy from the body)
        act = m.get("act")
        if act:
            f = self.fails.setdefault(act.get("action", "?"), [0, 0, ""])
            f[0] += 1
            if not act.get("ok", True):
                f[1] += 1
                f[2] = act.get("why", "")
                reward -= VEXATION
            reward -= EFFORT * float(act.get("ticks", 0))     # how long my hands and legs worked
            need = act.get("need")                            # it did not work: what was missing? look it up
            if not act.get("ok", True) and need and child.age - self.looked_up.get(need, -10 ** 9) > 2000:
                self.looked_up[need] = child.age
                what = need.split(":", 1)[1].replace("_", " ")
                events.append(("guide", f"Не получилось ({act.get('why', '')}) — нужно {what}. Ищу в гайде, как это получить"))
                if need.startswith("have:") and self.plan_at_act is not None:   # a step of my plan failed for
                    child.mind.tell([], {need: 0.5}, source="неудача")      # want of it: now I want it (a random
                if need.startswith("have:"):                                 # try that failed only teaches)
                    exact = self.recall.about_item(need[5:], child)          # and the game's reference: the recipe
                    if exact:
                        events.append(("recall", exact))
                for kind, text in child.development.study(need, child, depth=2):
                    events.append((kind, text))
                    if me:
                        me.note(text, None)
        # --- my age in game time (it goes on while I dig: moments are decisions, the body lives on)
        ct = m.get("client_ticks")
        if ct is not None and me is not None:
            if self.ticks_before is not None and ct >= self.ticks_before:
                me.me["lived_ticks"] = me.me.get("lived_ticks", 0) + (ct - self.ticks_before)
            self.ticks_before = ct
        # --- sore hands: hard things broken with bare hands (or the wrong tool) hurt
        self.sore *= 0.995
        for block, gained in (m.get("fev") or {}).get("broke", []):
            tools = (self.recall.blocks.get(block) or {}).get("tools") or []
            if tools and m.get("held", "") not in tools:
                self.sore += 1.0
                if self.sore > 2.0:                               # the third one in a row: it really hurts
                    reward -= HAND_PAIN * min(3.0, self.sore - 2.0)
                    m.setdefault("pain", []).append(["hands", "", ""])
                    events.append(("pain", f"Руки болят: ломаю {block} голыми руками"))
        m["_fails"] = self.fails
        # --- pain, with its real cause; and hunger that gnaws harder as the food runs out
        hp_lost = max(0.0, self.body.hp - float(m.get("health", self.body.hp) or 0))
        for entry in m.get("pain", []):
            if entry[0] == "hands":                           # (already said: "my hands hurt")
                continue
            what = feel_bridge.pain_of(entry)
            events.append(("pain", f"Больно: {PAIN_RU.get(what, what)}" + (f" (−{hp_lost:.0f} HP)" if hp_lost else "")))
            beat = "killed:" + what                               # someone hurts me: how do I beat him? (the guide)
            if what in child.kinds and child.age - self.looked_up.get(beat, -10 ** 9) > 2000:
                self.looked_up[beat] = child.age
                read = child.development.study(beat, child, depth=3)
                if read:
                    events.append(("guide", f"Меня бьёт {PAIN_RU.get(what, what)}. Ищу в гайде, как отбиться"))
                for kind, text in read:
                    events.append((kind, text))
        food = int(m.get("food", 20) or 0)
        reward -= 0.01 * max(0, 6 - food)                     # hunger pangs (0 when fed, strong when starving)
        unease = feel_bridge.dark_unease(m)                   # the dark, when I am exposed to it (not in the Nether/End)
        reward -= DARK_UNEASE * unease
        was = getattr(self, "unease", 0.0)
        if was > 0.3 and unease < 0.05:                       # safe again: relief
            reward += 0.3
            events.append(("safe", "Укрылся — в темноте больше не страшно" if m.get("light", 15) <= 7 else "Стало светло — не страшно"))
        self.unease = unease
        m["_unease"] = unease
        # --- what the caregiver says: names, explanations, requests
        for user, text in m.get("heard", []):
            claims, values, understood = self.understanding.hear(text)
            if claims or values:
                child.mind.tell(claims, values, source=user)
            if understood:
                events.append(("understood", f"{user}: «{text[:80]}» → понял: {'; '.join(understood)}"))
                if me:
                    me.note(f"понял {user}: " + "; ".join(understood), None)
                if not say:
                    say = "Понял: " + "; ".join(understood)
        # --- watching people; the joy of doing what I saw
        items = m.get("items", {})
        if act and act.get("ok") and act.get("action") in PLACING:
            m["_placed_items"] = {k: v - items.get(k, 0) for k, v in self.items_before.items() if items.get(k, 0) < v}
        self.items_before = dict(items)
        r_im, seen_notes = child.imitation.moment(m, child, child.age)
        reward += r_im
        for note in seen_notes:
            events.append(("imitation" if note.startswith("повторил") else "watched", note[0].upper() + note[1:]))
            if me:
                me.note(note, None)
        # --- the need to develop: joy of growing, unease of standing still, the next step, reading the guide
        r_dev, dev_events = child.development.moment(m, child, me, child.age)
        reward += r_dev
        for kind, text in dev_events:
            events.append((kind, text))
            if me:
                me.note(("развитие: " if kind == "develop" else "") + text, None)
        m["_development"] = {"next": child.development.step_title, "tier": child.development.best_tier,
                             "idle": child.age - child.development.last_growth}
        # --- the memory of places, and of my chests (where each is, what is in it)
        child.places.update(m, child.age)
        chest = (m.get("fev") or {}).get("chest")
        if chest:
            from recall import ru

            child.places.chest(chest, m, child.age)
            inside = ", ".join(f"{ru(k)} {n}" for k, n in sorted((chest.get("items") or {}).items(), key=lambda kv: -kv[1]))
            events.append(("chest", "В сундуке теперь: " + (inside or "пусто")))
        if act and act.get("action") in ("store", "take") and act.get("why") == "рядом нет сундука":
            child.places.chest_gone(m)                         # it is not where I remember it
        m["_known_places"] = child.places.known(m)
        m["_stored"] = child.places.stored()
        for user, text in m.get("heard", []):                 # someone spoke to us
            if not say:
                say = feel_bridge.talk(child, text)
            if not say:
                say = mind_talk(child.mind, text)
            if self.voice and not say:
                say = self.voice.reply(text, me)
            if me:
                me.note(f"{user} сказал: «{text}»" + (f"; я ответил: «{say}»" if say else ""), None)
        realised = self.recall.moment(m, child)                 # "I broke stone, nothing... stone needs a pickaxe"
        if realised:
            say = say or realised
            events.append(("recall", realised))
            if me:
                me.note("вспомнил: " + realised, None)
            self.log("[recall] " + realised)
        o = self.body.to_o(m, self.a_prev, frame)
        child.m = m
        child.mind.novelty = getattr(me, "novelty_now", 0.0) if me else 0.0   # (the mind keeps it apart)
        child.mind.last_ok = (m.get("act") or {}).get("ok")          # did my last action do anything
        fev = m.get("fev") or {}                              # it came to me from outside: given, or found lying
        child.mind.external = bool(fev.get("gift") or fev.get("found"))
        a = child.step(o, self.a_prev, self.front_prev, self.inv_prev, extra_reward=reward)
        if force is not None:
            a = force                                         # the experimenter's hand, felt as its own movement
        self.a_prev, self.front_prev, self.inv_prev = a, int(o["view"][7]), dict(o["inv"])
        fev = m.get("fev") or {}
        if fev.get("read"):                                   # reading: text -> beliefs in the mind
            from reading import read as parse_text, MC_NAMES
            claims, values = parse_text(fev["read"], MC_NAMES)
            child.mind.tell(claims, values)
            self.log(f"[read] {fev['read'][:80]}... -> {claims} {values}")
            if me:
                me.note(f"прочитал книгу: «{fev['read'][:120]}»; поверил: " + "; ".join(
                    f"{t} ← {' + '.join(p)}" for t, p in claims), None)
        L = child.limbic
        if max(L.e.values()) > 0.6 and self.clock() - self.last_felt > 90:
            self.last_felt = self.clock()
            felt = L.say()
            if me:
                me.note("чувствую: " + felt, None)
            say = say or felt
        mind = child.mind                                     # my intention: what became of it, in words
        for step, text in [x for x in mind.intent_log if x[0] > self.intent_seen]:
            events.append(("intent", text))
            self.intent_seen = step
        m["_intent"] = {"what": mind.names[mind.intent] if mind.intent is not None else None,
                       "for": mind.steps - mind.intent_t, "fails": mind.intent_fails,
                       "saved": mind.names[mind.intent_saved] if mind.intent_saved is not None else None}
        self.plan_at_act = child.mind.goal if getattr(child.mind, "chose", "plan") == "plan" else None
        return a, feel_bridge.attention(child, a, m), say, o
