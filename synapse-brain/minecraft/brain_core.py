"""
One moment of the grown brain: the body's report in, a motor command out.

Shared by the Minecraft server (brain_server.py) and the simulated world (../agent/minesim.py),
so that what the brain learns in one is the same brain, in the same code, in the other.
"""
import time

import feel_bridge
from actions import ACTIONS
from mind_bridge import talk as mind_talk

VEXATION = 0.03       # an action that did nothing: a small vexation (the cerebellum's error, wasted effort)
HAND_PAIN = 0.3       # breaking stone, ore... with bare hands (or the wrong tool) hurts the hands; it adds up
DARK_UNEASE = 0.03    # innate: in the dark and exposed (night under the sky, a black cave) - apprehension
EFFORT = 0.0004       # effort: every tick of work costs a little strength (stone by hand, 150 ticks: 0.06;
                      # with a pickaxe, 23 ticks: 0.009) - so tools become worth what they save, by themselves
PLACING = ("place_block", "use", "pillar_up", "place_chest", "place_frame", "place_up")
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
        self.kills = []                                         # creatures that fell by my hand, a moment ago
        self.moment_id = 0                                      # each answer to the body is numbered; the body says
                                                                # which one its report of an action is about
        self.contract = {"moments": 0, "reported": 0, "stale": 0, "interrupted": 0, "timeout": 0, "changed": 0}
        mind, dev = child.mind, child.development
        from knowledge import channels

        self.knowledge = K = channels()                        # what may come ready-made (world.json "knowledge")
        if dev.guide is not None:                              # what I read before: what helps, and what was read
            for concept in dev.read:
                claims = [c for c, _, _ in dev.guide.about(concept)]
                mind.mark_told(claims)
                mind.tell_helps(claims)
        for block, info in (self.recall.blocks.items() if K["recipes"] else ()):   # the reference book: the right
            tools, drops = info.get("tools") or [], info.get("drops") or []             # tool makes mining work
            if tools and drops:
                mind.tell_helps([("have:" + drops[0], ["have:" + tools[0]])], new=False)

    def new_body(self):
        """Reconnected: the senses start again (the brain and memory stay)."""
        self.body = feel_bridge.Body()
        self.a_prev, self.front_prev, self.inv_prev = None, 0, {}
        self.child.mind.acted(-1)                               # what I chose last never reached a body

    def did(self, act):
        """What my body really did last, from its report (efference copy): None when it does not say (then:
        what I chose), -1 when the report is about another moment than my last answer, or the body was cut off
        (death, pause) - then nothing is learned about doing it."""
        c = self.contract                                       # (counted: how often body and mind disagree)
        c["moments"] += 1
        if not act or "a" not in act:
            return None
        c["reported"] += 1
        c["timeout"] += bool(act.get("timeout"))
        if "id" in act and int(act["id"]) != self.moment_id:
            c["stale"] += 1
            return -1
        if act.get("interrupted"):
            c["interrupted"] += 1
            return -1
        return int(act["a"])

    @staticmethod
    def _count(child, item):
        kind = getattr(child, "kind_of", None) or (lambda k: k)
        return sum(v for k, v in ((child.m or {}).get("items") or {}).items() if k == item or kind(k) == item)

    def _state_of(self, child, effect):
        """What the expected effect is now: how many I have of it, or whether it is true."""
        if effect.startswith("have:"):
            return self._count(child, effect.split("×")[0][5:])
        im = child.imagination
        return bool(im.holds(effect, im.state()))

    def _expectation(self, child, a, events):
        """A step of my plan comes with what I expect of it ("I strike the log - a log in my bag"). The next
        moment I see whether it came: that is how far such a step can be trusted (imagining the next way with
        it), and a step that worked is progress - I go on with the plan instead of giving it up as too slow."""
        from recall import ru

        mind, exp = child.mind, getattr(self, "expect", None)
        if exp is not None:
            now = self._state_of(child, exp["effect"])
            ok = now > exp["before"] if exp["effect"].startswith("have:") else bool(now)
            if not ok and exp["kind"] == "attack" and isinstance(exp["target"], str) and                     (getattr(child, "_concepts", {}) or {}).get("see:" + exp["target"]):
                exp = None                                    # a blow landed, it still stands: the fight goes on
        if exp is not None:
            child.imagination.learned(exp["kind"], exp["target"], exp["effect"], ok)
            what = ru(exp["effect"].split("×")[0].partition(":")[2] or exp["effect"])
            step = ru(exp["kind"]) + (" " + ru(exp["target"]) if isinstance(exp["target"], str) else "")
            if ok:
                if mind.goal is not None:
                    mind.goal_t = mind.steps                  # (the plan goes on: patience renewed)
                events.append(("step", f"✓ {step} — ждал {what}, получил"))
            else:
                r = child.imagination.rel.get(child.imagination.key(exp["kind"], exp["target"], exp["effect"]), [0, 0])
                events.append(("step", f"✗ {step} — ждал {what}, не вышло ({int(r[0] - r[1])} из {int(r[0])})"))
            self.expect = None
        st = child.plan_steps.get(mind.goal) if getattr(mind, "how", None) == "plan" and mind.goal is not None else None
        if st is not None and a < len(ACTIONS) and ACTIONS[a] == st["kind"]:
            self.expect = dict(st, before=self._state_of(child, st["effect"]))

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
                tgt = getattr(self, "last_target", None)
                if act.get("action") == "goto_place" and isinstance(tgt, list) and not act.get("interrupted"):
                    child.places.could_not_reach(tgt, m, child.age)   # stuck on the way there: not again for a while
            reward -= EFFORT * float(act.get("ticks", 0))     # how long my hands and legs worked
            need = act.get("need")                            # it did not work: what was missing? look it up
            if not self.knowledge["recipes"]:                 # (the body naming what was missing - "nothing to eat:
                need = None                                   # bread" - is the game's rules told: shut with them)
            if not act.get("ok", True) and need and child.age - self.looked_up.get(need, -10 ** 9) > 2000:
                self.looked_up[need] = child.age
                what = need.split(":", 1)[1].replace("_", " ")
                events.append(("guide", f"Не получилось ({act.get('why', '')}) — нужно {what}" +
                               (". Ищу в гайде, как это получить" if child.development.guide is not None else "")))
                if need.startswith("have:") and self.plan_at_act is not None:   # a step of my plan failed for
                    child.mind.tell([], {need: 0.5}, source="неудача")      # want of it: now I want it (a random
                if need.startswith("have:") and self.knowledge["recipes"]:   # try that failed only teaches)
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
            child.yields.learn(block, gained, feel_bridge.tool_of(m.get("held")))   # what it gave me, with what
            tools = (self.recall.blocks.get(block) or {}).get("tools") or []
            if tools and m.get("held", "") not in tools:
                self.sore += 1.0
                if self.sore > 2.0:                               # the third one in a row: it really hurts
                    reward -= HAND_PAIN * min(3.0, self.sore - 2.0)
                    m.setdefault("pain", []).append(["hands", "", ""])
                    events.append(("pain", f"Руки болят: ломаю {block} голыми руками"))
        now_items = m.get("items") or {}
        for kind, _, _, cause, *_ in (m.get("fev") or {}).get("deaths", []):
            if cause == "self":                               # it fell by my hand: what does it leave me?
                self.kills.append(["mob:" + str(kind), dict(now_items), 0])
        for k in self.kills:                                  # (what came into my bag in the moments after)
            k[2] += 1
        for k in [k for k in self.kills if k[2] >= 4]:
            child.yields.learn(k[0], [i for i, n in now_items.items() if n > k[1].get(i, 0)])
        self.kills = [k for k in self.kills if k[2] < 4]
        m["_fails"] = self.fails
        # --- pain, with its real cause; and hunger that gnaws harder as the food runs out
        hp_lost = max(0.0, self.body.hp - float(m.get("health", self.body.hp) or 0))
        for entry in m.get("pain", []):
            if entry[0] == "hands":                           # (already said: "my hands hurt")
                continue
            what = feel_bridge.pain_of(entry)
            events.append(("pain", f"Больно: {PAIN_RU.get(what, what)}" + (f" (−{hp_lost:.0f} HP)" if hp_lost else "")))
            if what not in ("hunger", "hands"):               # it hurt here: a place to keep away from
                child.places.hurt_here(what, m, child.age)
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
        if was > 0.3 and unease < 0.05 and child.age - getattr(self, "relieved_at", -10 ** 9) > 400:   # safe again:
            self.relieved_at = child.age                      # relief (once - not each time I peek out and back)
            reward += 0.3
            events.append(("safe", "Укрылся — в темноте больше не страшно" if m.get("light", 15) <= 7 else "Стало светло — не страшно"))
        self.unease = unease
        m["_unease"] = unease
        m["_exposure"] = feel_bridge.exposure(m)
        tod = m.get("time", 6000)
        if 12000 <= tod <= 23500 and m["_exposure"] <= 0.05 and child.age - getattr(self, "homed_at", -10 ** 9) > 400:
            self.homed_at = child.age                         # closed in and safe at night: this is a home
            child.places.remember_home(m, child.age)
            events.append(("home", "Здесь я в безопасности ночью — это мой дом"))
        # --- what the caregiver says: names, explanations, requests
        for user, text in (m.get("heard", []) if self.knowledge["speech"] else ()):
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
        r_im, seen_notes = child.imitation.moment(m, child, child.age) if child.imitation is not None else (0.0, [])
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
        realised = self.recall.moment(m, child) if self.knowledge["recipes"] else None   # "I broke stone,
                                                                # nothing... stone needs a pickaxe"
        if realised:
            say = say or realised
            events.append(("recall", realised))
            if me:
                me.note("вспомнил: " + realised, None)
            self.log("[recall] " + realised)
        child.schemas.outcome(m)                              # what came of the last aimed action (learned)
        o = self.body.to_o(m, self.a_prev, frame)
        child.m = m
        child.mind.novelty = getattr(me, "novelty_now", 0.0) if me else 0.0   # (the mind keeps it apart)
        did = self.did(act)
        child.mind.last_ok = None if did == -1 else (act or {}).get("ok")    # did my last action do anything
        fev = m.get("fev") or {}                              # it came to me from outside: given, or found lying
        child.mind.external = bool(fev.get("gift") or fev.get("found"))
        a = child.step(o, self.a_prev, self.front_prev, self.inv_prev, extra_reward=reward, did=did)
        m["_did"], m["_chose"], m["_how"] = did, a, getattr(child.mind, "how", None)
        w = getattr(child.mind, "why_a", None)                # what drew the plan to it most (above the average)
        m["_why"] = sorted(((round(v, 3), k) for k, v in w.items() if v > 0), reverse=True)[:3] if w else None
        blocked = getattr(child.mind, "blocked", None)          # what the mind meant, if it was refused (a veto)
        m["_meant"] = blocked if blocked is not None and blocked != a else None
        child.mind.blocked = None
        if force is not None and force != a:
            a = force                                         # the experimenter's hand, felt as its own movement:
            m["_intervention"] = True                         # learned as what was done, and marked in the record
        n_body = m.get("n_actions")
        if n_body is not None and a >= int(n_body):           # this body cannot do it (bot.js has 41 actions)
            a = child.wait_action
        m["_contract"] = self.contract
        if a != m["_chose"]:
            self.contract["changed"] += 1
            child.mind.acted(a)
            if child.prev is not None:
                child.prev = (child.prev[0], a)
        self.moment_id += 1
        self._expectation(child, a, events)                   # what my last step brought; what I expect of this one
        self.a_prev, self.front_prev, self.inv_prev = a, int(o["view"][7]), dict(o["inv"])
        fev = m.get("fev") or {}
        if fev.get("ate"):                                    # it went into my mouth, and it was food
            child.edible.add(str(fev["ate"]))
        if fev.get("recipes") and self.knowledge["recipe_book"]:   # the recipe book: what makes what
            claims = []
            for result, need, table, *_ in fev["recipes"]:
                pres = ["have:" + k for k in need] + (["at_table"] if table else [])
                claims.append(("have:" + result, pres))
                child.recipes_read[result] = [need, bool(table)]   # (with how many of each: for imagining)
            child.mind.tell(claims, {}, source="книга рецептов")
            from recall import ru

            for result, need, table, *_ in fev["recipes"][:4]:
                events.append(("read", f"В книге рецептов: {ru(result)} ← " + " + ".join(
                    f"{ru(k)} ×{n}" for k, n in need.items()) + (" (на верстаке)" if table else "")))
        if fev.get("read") and self.knowledge["books"]:       # reading: text -> beliefs in the mind
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
        if getattr(child, "imagined", None) and child.imagined != getattr(self, "imagined_said", None):
            self.imagined_said = child.imagined                # a way played in my head, in words
            events.append(("imagine", "Представил путь: " + child.imagined))
        mind = child.mind                                     # my intention: what became of it, in words
        for step, text in [x for x in mind.intent_log if x[0] > self.intent_seen]:
            events.append(("intent", text))
            self.intent_seen = step
        m["_intent"] = {"what": mind.names[mind.intent] if mind.intent is not None else None,
                       "for": mind.steps - mind.intent_t, "fails": mind.intent_fails,
                       "saved": mind.names[mind.intent_saved] if mind.intent_saved is not None else None}
        ps = getattr(child, "plan_steps", {})                  # (for the record: the step imagined for what I decided,
        m["_plan"] = {k: ps[g]["kind"] + (":" + ps[g]["target"] if isinstance(ps[g]["target"], str) else "")
                      for k, g in (("intent", mind.intent), ("goal", mind.goal)) if g is not None and g in ps}   # and for the step)
        self.plan_at_act = child.mind.goal if getattr(child.mind, "chose", "plan") == "plan" else None
        tgt = feel_bridge.attention(child, a, m)
        child._executed = (ACTIONS[a] if a < len(ACTIONS) else "wait", tgt)   # (the core learns from what was done)
        child.schemas.aim(ACTIONS[a] if a < len(ACTIONS) else "", tgt if isinstance(tgt, str) else None, m)
        return a, tgt, say, o
