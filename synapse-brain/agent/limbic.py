"""
Limbic system: feelings that grow out of a body, a memory and a life - not out of scripts.

GENOME (the only innate part, the same things a newborn has):
  interoception   hunger, pain (loss of health), tiredness, nausea                (hypothalamus, insula)
  taste           palatability of each food; pleasure scales with hunger          (alliesthesia)
  startle         a loud sudden sound raises arousal                              (brainstem)
  prosody         a warm voice soothes, a scolding voice hurts, an alarmed one arouses (infants
                  react to tone long before words); a purring cat is a soothing sound
  curiosity       the pleasure of LEARNING: progress of the brain's own predictions (not surprise
                  itself - noise is not interesting); the same rule for the sky, which is where
                  sunsets can become beautiful - or not
  attachment      whoever/whatever is present when I feel good becomes dear (Hebbian bonding);
                  what I built with my own hands is dear in proportion to the effort
  empathy         the distress of a being dear to me is felt as my own, in proportion to how dear
  retaliation     when I am angry, harming the one I blame is satisfying (known from neuroscience
                  of aggression); WHO is to blame is learned, and whether to hit is up to the striatum
  action tendencies of the dimensions: sadness lowers vigour and makes the mind replay the loss,
                  fear avoids (amygdala), boredom and interest explore, loneliness seeks company.

LEARNED (from experience): the value of everything (dopamine TD), predicted harm and predicted
joy, who causes losses (blame), what is mine and how dear it is (cognitive map + attachment),
what the caregiver approves of (standards), my own competence, episodic memories with their
feelings, and every preference - houses, sunsets, fish at sunset - or none of them.

EMOTIONS are not programs. Each moment the appraisal system computes a few dimensions (valence,
arousal, novelty, expectation of harm and of joy, who caused it, can I cope, how dear it was, is
someone watching, what I did, what others have...). The emotions below are READOUTS of regions of
that space - names for a mix, like a psychologist's labels. Behaviour is driven by the dimensions,
not by the names. Mixtures are the rule: a loss of something dear (sadness) caused by someone I can
fight (anger) is both at once. Which emotions are possible grows with development (Lewis): newborn
- contentment, distress, interest, disgust, startle; with expectations and causes - joy, sadness,
fear, anger, surprise; with a self-model - embarrassment, empathy, jealousy, envy; with internalised
standards - pride, shame, guilt.
"""
import numpy as np

EMOTIONS = [  # (key, Russian name)
    ("contentment", "довольство"), ("distress", "дистресс"), ("interest", "интерес"), ("disgust", "отвращение"),
    ("startle", "испуг"), ("joy", "радость"), ("sadness", "грусть"), ("grief", "горе"), ("fear", "страх"),
    ("anxiety", "тревога"), ("anger", "злость"), ("frustration", "раздражение"), ("surprise", "удивление"),
    ("relief", "облегчение"), ("disappointment", "разочарование"), ("hope", "надежда"),
    ("excitement", "азарт"), ("craving", "желание"), ("satisfaction", "удовлетворение"),
    ("calmness", "спокойствие"), ("boredom", "скука"), ("confusion", "замешательство"),
    ("amusement", "веселье"), ("awe", "благоговение"), ("aesthetic", "восхищение красотой"),
    ("entrancement", "заворожённость"), ("love", "любовь"), ("adoration", "нежность"),
    ("loneliness", "одиночество"), ("nostalgia", "ностальгия"), ("gratitude", "благодарность"),
    ("trust", "доверие"), ("empathic_pain", "сочувствие"), ("horror", "ужас"), ("admiration", "восхищение другим"),
    ("envy", "зависть"), ("jealousy", "ревность"), ("schadenfreude", "злорадство"), ("contempt", "презрение"),
    ("embarrassment", "смущение"), ("awkwardness", "неловкость"), ("pride", "гордость"), ("shame", "стыд"),
    ("guilt", "вина"), ("regret", "сожаление"), ("despair", "отчаяние"), ("depression", "подавленность"),
    ("determination", "решимость"),
]
NAMES = dict(EMOTIONS)
KEYS = [k for k, _ in EMOTIONS]
STAGE_OF = {k: 0 for k in ("contentment", "distress", "interest", "disgust", "startle", "calmness",
                           "boredom", "aesthetic", "entrancement", "craving", "confusion")}
STAGE_OF.update({k: 2 for k in ("embarrassment", "awkwardness", "envy", "jealousy", "admiration",
                                "empathic_pain", "schadenfreude", "contempt", "nostalgia", "regret")})
STAGE_OF.update({k: 3 for k in ("pride", "shame", "guilt")})
STAGE_NAMES = ["новорождённый", "первичные эмоции", "осознание себя", "внутренние нормы"]
DIRS = [(-1, 0), (0, 1), (1, 0), (0, -1)]
PLACED = (4, 5)                    # classes the agent can build (block, chest): only for reading its own map
MASK = (1 << 20) - 1


def _sq(x):
    return float(np.clip(x, 0.0, 1.0))


class Limbic:
    def __init__(self, seed=0, taste=None):
        self.rng = np.random.default_rng(seed + 11)
        self.taste = taste or {}
        # learned predictors (TD on the same sensory cells as the striatum)
        self.Wh = np.zeros(MASK + 1, np.float32)       # predicted future pain  (amygdala / anterior insula)
        self.Wj = np.zeros(MASK + 1, np.float32)       # predicted future pleasure (ventral striatum)
        self.ph = self.pj = 0.0
        self.prev_cells = None
        # perception models for curiosity / aesthetics: counts of what follows what
        self.sky_model = {}
        self.err = {}                                  # context -> [fast, slow] prediction error
        self.prev_sky = None
        # social and causal knowledge
        self.blame = {}                                # kind -> how much losses come with it
        self.bad_with, self.bad_all, self.n_all = {}, 0.0, 0.0
        self.approval = {}                             # (action, what was in front) -> caregiver's tone
        self.n_approval = 0
        self.help = {}                                 # kind -> how much good comes from it (trust)
        # the self: attachments and the map of what is mine
        self.attach_being = {}                         # being id -> how dear
        self.kind_of = {}
        self.mem = {}                                  # (y, x) -> class last seen (cognitive map)
        self.mine = {}                                 # (y, x) -> effort I put into it
        self.stored = {}                               # (y, x) -> what I put in that chest
        self.attach_place = {}                         # (y, x) -> how dear this place is
        # episodic memory (fast, one-shot, emotional)
        self.episodes = []
        # affect state
        self.mood = 0.0                                # slow valence (hours)
        self.mood_slow = 0.0                           # very slow (days): depression if it stays low
        self.arousal = 0.0
        self.e = {k: 0.0 for k in KEYS}               # current emotion intensities
        self.lingering = {"sadness": 0.0, "anger": 0.0, "grief": 0.0, "fear": 0.0, "guilt": 0.0, "shame": 0.0,
                          "pride": 0.0, "joy": 0.0, "love": 0.0, "gratitude": 0.0, "horror": 0.0}
        self.blamed_now = None
        self.since_social = 0
        self.since_joy = 0
        self.look_streak = 0
        self.fails = 0
        self.age = 0
        self.fm_err = 1.0                              # how well I predict the results of my own actions
        self.first_felt = {}                           # emotion -> age when first felt
        self.counts = {k: 0 for k in KEYS}
        self.mixed = 0
        self.dsd = 0.05
        self.interest_avg = 0.05
        self.stats = {}
        self.sad_avg = 0.0
        self.since_event = 0                           # moments since anything at all happened
        self.rate_now = self.rate_life = 0.5
        self.lost_dear = []                            # [how dear, when, where] of what I lost
        self.aversion = {}                             # (action, context) -> one-shot learned 'never again' (insula)
        self.cause_text = ""

    def z(self, name, x, rate=0.002):
        """How unusual x is for me (my own running mean and spread): feelings respond to change,
        a constant background fades - like every sense does."""
        m, v = self.stats.get(name, (x, 0.01))
        m += rate * (x - m)
        v += rate * ((x - m) ** 2 - v)
        self.stats[name] = (m, v)
        return (x - m) / (np.sqrt(v) + 1e-3)

    # ---------------------------------------------------------------- development
    def stage(self):
        """Emotional development by readiness, not by a timer: expectations must be learned before
        joy/fear/anger exist, a self-model before self-conscious emotions, standards before pride."""
        s = 0
        if self.age > 1500 and (abs(self.ph) > 0.05 or abs(self.pj) > 0.05 or self.blame):
            s = 1
        if s == 1 and self.fm_err < 0.6 and self.age > 6000:
            s = 2
        if s == 2 and self.n_approval >= 15:
            s = 3
        return s

    # ---------------------------------------------------------------- curiosity: learning progress
    def _progress(self, ctx, err):
        f = self.err.setdefault(ctx, [err, err])
        f[0] += 0.3 * (err - f[0])
        f[1] += 0.03 * (err - f[1])
        return max(0.0, f[1] - f[0])

    def _sky(self, sky):
        """Predict what I see in the sky from what I saw last time I looked (visual cortex model).
        Returns learning progress on it (the pleasure of making sense of it)."""
        if len(sky) < 8:
            self.prev_sky = None
            return 0.0, 0.0
        err, n = 0.0, 0
        if self.prev_sky is not None:
            for j in range(8):
                key = (int(self.prev_sky[max(j - 1, 0)]), int(self.prev_sky[j]), int(self.prev_sky[min(j + 1, 7)]))
                c = self.sky_model.setdefault(key, np.ones(8, np.float32) * 0.1)
                err += -np.log(c[sky[j]] / c.sum())
                c[sky[j]] += 1
                n += 1
        self.prev_sky = sky.copy()
        if not n:
            return 0.0, 0.0
        err /= n
        colours = len(set(int(x) for x in sky))
        return self._progress(("sky", int(np.bincount(sky, minlength=8).argmax())), err), err * 0 + colours / 8

    # ---------------------------------------------------------------- the map of what is mine
    def _cells_in_view(self, pos, d):
        dy, dx = DIRS[d]
        ry, rx = DIRS[(d + 1) % 4]
        for a in range(5):
            for b in range(5):
                yield a * 5 + b, (pos[0] + dy * a + ry * (b - 2), pos[1] + dx * a + rx * (b - 2))

    def _see_map(self, o, act, front_before):
        """Compare what I see with what I remember. Things of mine that vanished = a loss."""
        lost, lost_items = [], {}
        view, pos, d = o["view"], o["pos"], o["dir"]
        ev = o["ev"]
        dug = {tuple(p) for p, c, own, items, cause in ev["destroyed"] if cause == "self"}
        if ev["placed"] is not None:
            p = tuple(ev["placed"])
            self.mine[p] = self.mine.get(p, 0.0) + 0.3                   # effort
        for i, p in self._cells_in_view(pos, d):
            c = int(view[i])
            if c >= 7:
                continue                                                 # a being stands there
            old = self.mem.get(p)
            if old in PLACED and c not in PLACED and p not in dug:
                # something built is gone: how dear was it? (made by me, or part of a place I love)
                dear = self.mine.get(p, 0.0) + max((self.attach_place.get((p[0] + a, p[1] + b), 0.0)
                                                   for a in (-1, 0, 1) for b in (-1, 0, 1)), default=0.0)
                if dear > 0.05:
                    lost.append((p, dear))
                    for k, v in self.stored.get(p, {}).items():
                        lost_items[k] = lost_items.get(k, 0) + v
            if c not in PLACED:
                self.mine.pop(p, None)
                self.stored.pop(p, None)
            self.mem[p] = c
        if act == 6 and front_before == 5:                               # I put my things into this chest
            f = (pos[0] + DIRS[d][0], pos[1] + DIRS[d][1])
            box = self.stored.setdefault(f, {})
            for k, v in self._inv_before.items():
                if v:
                    box[k] = box.get(k, 0) + v
        if act == 7 and front_before == 5:
            self.stored[(pos[0] + DIRS[d][0], pos[1] + DIRS[d][1])] = {}
        return lost, lost_items

    # ---------------------------------------------------------------- one moment of feeling
    def feel(self, o, act, front_before, cells, value_now, delta, inv_before, competence, goal_failed, extra=0.0):
        """o: the body's report after `act`. Returns (primary reward for learning, features for the striatum)."""
        self.age += 1
        self._inv_before = inv_before
        ev = o["ev"]
        st = self.stage()
        near = {bid: (kind, dist) for kind, bid, dist in o["near"]}
        for bid, (kind, _) in near.items():
            self.kind_of[bid] = kind
        # ---- the body (genome)
        pain = sum(dmg for who, _, dmg, _ in ev["hurt"] if who == "self")
        r = -pain / 4.0 + extra                                          # + pleasure the body reports (e.g. something new)
        taste = 0.0
        if ev["ate"]:
            hunger_before = min(20, o["hunger"] - 4)
            taste = self.taste.get(ev["ate"], 0.0) * (1.0 + max(0, 20 - hunger_before) / 10)
            r += taste
        heal = max(0, o["hp"] - getattr(self, "prev_hp", o["hp"]))    # the pain goes away: relief
        self.prev_hp = o["hp"]
        r += heal / 8.0
        r -= 0.004 * max(0, 10 - o["hunger"])
        r -= 0.03 * o["nausea"]
        r -= 0.002 * max(0, o["fatigue"] - 250) / 50
        if ev["slept"]:
            r += 0.3
        startle = 1.0 if "boom" in ev["sounds"] else 0.5 if "hiss" in ev["sounds"] else 0.0
        tone = ev["tone"]
        social = {0: 0.0, 1: 0.3, 2: 0.0, 3: -0.3}[tone] + (0.15 if "purr" in ev["sounds"] else 0.0)
        r += social
        if tone or "purr" in ev["sounds"] or any(k in ("carer", "mycat") and dd <= 2 for k, _, dd in o["near"]):
            self.since_social = 0
        else:
            self.since_social += 1
        # ---- curiosity and the sky
        sky_lp, colours = self._sky(o["sky"])
        world_lp = self._progress(("world", int(o["view"][7])), float(self.fm_surprise))
        interest = sky_lp * 3 + world_lp * 0.5
        self.look_streak = self.look_streak + 1 if len(o["sky"]) == 8 else 0
        r += interest
        # ---- predictions: harm and joy (learned)
        h = float(self.Wh[cells].sum())
        j = float(self.Wj[cells].sum())
        if self.prev_cells is not None:
            lr = 0.1 / len(cells)
            self.Wh[self.prev_cells] += lr * (pain / 4.0 + 0.95 * h - self.ph)
            self.Wj[self.prev_cells] += lr * (max(0.0, r) + 0.95 * j - self.pj)
        dh, dj = h - self.ph, j - self.pj
        self.appraised = None
        prev_h, prev_j = self.ph, self.pj
        self.ph, self.pj, self.prev_cells = h, j, cells
        # ---- what happened to what is dear to me
        if "lost_built" in o:                                            # the body reports its own placed blocks (Minecraft)
            lost, lost_items = [], {}
            for x, zz, name in o["lost_built"]:
                dear = 0.3 + max((self.attach_place.get((x + a, zz + b), 0.0) for a in (-2, -1, 0, 1, 2)
                                  for b in (-2, -1, 0, 1, 2)), default=0.0)
                lost.append(((x, zz), dear))
                if name == "chest":
                    lost_items["chest"] = lost_items.get("chest", 0) + 3
        else:
            lost, lost_items = self._see_map(o, act, front_before)
        loss = sum(d for p, d in lost) + 0.2 * sum(lost_items.values())
        dead_dear, hurt_dear, dear_kinds = 0.0, 0.0, []
        for kind, bid, tamed, cause, seen in ev["deaths"]:
            a = self.attach_being.get(bid, 0.0)
            if seen and a > 0.2:                                         # only the truly dear are grieved
                dead_dear += a
                dear_kinds.append(kind)
        for who, bid, dmg, cause in ev["hurt"]:
            if who != "self":
                hurt_dear += self.attach_being.get(bid, 0.0) * dmg / 4
        self_caused_harm = any(cause == "self" and self.attach_being.get(bid, 0) > 0.05
                               for who, bid, dmg, cause in ev["hurt"] if who != "self")
        # who is around when bad things happen (blame) or good things happen (trust)
        bad = pain / 4.0 + loss + dead_dear
        kinds_near = {k for k, _, dd in o["near"] if dd <= 4}
        if ev["explosion"] is not None:
            kinds_near.add("creeper")          # it was right there when it blew up
        # blame = how much MORE often bad things happen when this kind of being is around (lift),
        # not mere co-presence: a cat that happens to sit nearby is not blamed for a creeper
        self.bad_all = self.bad_all * 0.9998 + min(bad, 3.0)
        self.n_all = self.n_all * 0.9998 + 1
        for k in kinds_near:
            bp, n_p = self.bad_with.get(k, (0.0, 0.0))
            self.bad_with[k] = (bp * 0.9998 + min(bad, 3.0), n_p * 0.9998 + 1)
        for k, (bp, n_p) in self.bad_with.items():
            if n_p >= 5:
                base = self.bad_all / self.n_all + 1e-4
                self.blame[k] = float(np.clip((bp / n_p) / base - 1, 0, 6) / 2)
        good_from_other = (1.0 if ev["gift"] else 0.0) + (0.7 if ev["carer_did"] else 0.0)
        if good_from_other:
            self.help["carer"] = self.help.get("carer", 0.0) + 0.3 * (good_from_other - self.help.get("carer", 0.0))
        blamed = max(kinds_near, key=lambda k: self.blame.get(k, 0.0), default=None) if kinds_near else None
        if bad > 0.05 and blamed is not None and self.blame.get(blamed, 0) > 0.1:
            self.blamed_now = blamed
        # ---- attachment (Hebbian): being near someone when I feel good makes them dear
        pos_affect = max(0.0, r) + (0.2 if "purr" in ev["sounds"] else 0.0) + (0.2 if tone == 1 else 0.0)
        for bid, (kind, dist) in near.items():
            if kind in ("mycat", "carer", "cat") and dist <= 2:
                a = self.attach_being.get(bid, 0.0)
                self.attach_being[bid] = min(3.0, a + 0.02 * pos_affect + (0.3 if ev["tamed"] == bid else 0.0))
        here = tuple(o["pos"])
        safe_night = o.get("night", o["t"] % 240 >= 175) and pain == 0
        self.attach_place[here] = min(2.0, self.attach_place.get(here, 0.0) + 0.003 * (max(0.0, r) + (0.5 if safe_night else 0)))
        # affiliation (genome): infants are drawn to anything that moves by itself; what hurts
        # gets blamed and stops being attractive
        r += sum(0.03 * max(0.0, 1 - self.blame.get(k, 0.0)) for k, _, dd in o["near"] if dd <= 2 and k != "self")
        dear_near = sum(self.attach_being.get(bid, 0.0) for bid, (k, dist) in near.items() if dist <= 2) \
            + 0.5 * self.attach_place.get(here, 0.0)
        r += 0.02 * min(dear_near, 3.0)                                  # being with the ones I love
        # ---- anger's satisfaction: hurting the one I blame
        anger_prev = self.lingering["anger"]
        for who, bid, dmg, cause in ev["hurt"]:
            if cause == "self" and who in self.blame and anger_prev > 0.1:
                r += 0.5 * anger_prev * self.blame[who]
        blamed_died = [k for k, bid, tamed, cause, seen in ev["deaths"] if seen and self.blame.get(k, 0) > 0.3]
        # ---- social standards: what does my caregiver think of what I did?
        if tone in (1, 3) and act is not None:
            key = (int(act), int(front_before))
            v = 1.0 if tone == 1 else -1.0
            self.approval[key] = self.approval.get(key, 0.0) + 0.3 * (v - self.approval.get(key, 0.0))
            self.n_approval += 1
        my_norm = self.approval.get((int(act), int(front_before)), 0.0) if act is not None else 0.0
        watched = "carer" in {k for k, _, dd in o["near"]}
        # ---- the appraisal dimensions
        self.dsd += 0.01 * (abs(delta) - self.dsd)
        z = abs(delta) / (self.dsd + 1e-3)                               # how unexpected, for me, now
        v_now = float(np.tanh(1.5 * r + 0.5 * delta))
        novelty = min(1.0, _sq((z - 1.5) / 2) + (0.5 if ev["got"] and any(not inv_before.get(g) for g in ev["got"]) else 0.0))
        hz, jz, iz, fz = self.z("harm", h), self.z("joy", j), self.z("interest", interest), self.z("fails", self.fails)
        threat = _sq((hz - 0.5) / 2)
        threat_near = any(k in ("zombie", "creeper") and dd <= 3 for k, _, dd in o["near"])
        joy_ahead = _sq((jz - 0.5) / 2)
        coping = float(np.clip(0.3 + 0.7 * competence, 0, 1)) * (o["hp"] / 20)
        self.arousal += 0.3 * (min(1.0, abs(r) + 0.3 * _sq((z - 1) / 2) + startle + threat + 0.5 * novelty) - self.arousal)
        self.mood += 0.01 * (v_now - self.mood)
        self.mood_slow += 0.0005 * (v_now - self.mood_slow)
        self.since_joy = 0 if v_now > 0.2 else self.since_joy + 1
        self.fails = self.fails + 1 if goal_failed else max(0.0, self.fails - 0.003)
        happened = (novelty > 0.3 or abs(r) > 0.3 or ev["sounds"] or tone or ev["deaths"] or ev["hurt"]
                    or ev["tamed"] or o["near"] or interest > 0.1)          # something new, not the usual
        self.since_event = 0 if happened else self.since_event + 1
        self.rate_now += 0.01 * (float(bool(happened)) - self.rate_now)      # how eventful life is now ...
        self.rate_life += 0.0003 * (float(bool(happened)) - self.rate_life)  # ... compared with my life so far
        self.interest_avg += 0.005 * (interest - self.interest_avg)
        L = self.lingering
        for k in L:
            L[k] *= 0.995 if k in ("grief", "sadness", "love") else 0.98
        # losses and harms feed lasting states
        if loss + dead_dear > 0.05:
            L["sadness"] = min(1.0, L["sadness"] + 0.5 * loss + 2.0 * dead_dear)
            self.lost_dear.append([min(1.5, loss + 3.0 * dead_dear), self.age, tuple(o["pos"]), dead_dear > 0])
        if dead_dear:
            L["grief"] = min(1.0, L["grief"] + 3.0 * dead_dear)
            L["horror"] = min(1.0, L["horror"] + 2.0 * dead_dear)
        # missing what is gone: it does not fade in minutes, it comes back where we were together
        yearning = 0.0
        grief_y = 0.0
        for v, when, where, being in self.lost_dear:
            cue = 1.0 + (abs(where[0] - o["pos"][0]) + abs(where[1] - o["pos"][1]) <= 4)
            y = v * np.exp(-(self.age - when) / 2000.0) * cue * (0.25 if being else 0.1)
            yearning += y
            grief_y += y if being else 0.0
        self.lost_dear = [x for x in self.lost_dear if self.age - x[1] < 20000]
        yearning = min(1.0, yearning)
        L["sadness"] = max(L["sadness"], 0.6 * yearning)
        L["grief"] = max(L["grief"], min(1.0, grief_y))
        if self.blamed_now and bad > 0.05 and st >= 1:
            L["anger"] = min(1.0, L["anger"] + (0.3 + 0.7 * coping) * min(bad, 2.0) * self.blame.get(self.blamed_now, 0.0))
        if (pain or threat > 0.3) and st >= 1:
            L["fear"] = min(1.0, L["fear"] + 0.3 * (pain / 4 + threat) * (1.2 - coping))
        if self_caused_harm and st >= 3:
            L["guilt"] = min(1.0, L["guilt"] + 0.6)
        if tone == 3 and st >= 3:
            L["shame"] = min(1.0, L["shame"] + 0.4 * (1.2 - competence))
        achievement = (ev["got"] and novelty > 0.3) or (goal_failed is False)
        if achievement and st >= 3:
            L["pride"] = min(1.0, L["pride"] + 0.3 + (0.3 if tone == 1 else 0))
        if v_now > self.mood + 0.3:                                     # better than I am used to (adaptation)
            L["joy"] = min(1.0, L["joy"] + 0.4 * (v_now - self.mood - 0.3))
        if dear_near > 0.3:
            L["love"] = min(1.0, L["love"] + 0.01 * dear_near)
        if good_from_other:
            L["gratitude"] = min(1.0, L["gratitude"] + 0.5 * good_from_other)
        # ---- episodic memory: remember what moved me (fast, one shot)
        # ---- readouts: the names for the current mix
        E = self.e
        E["contentment"] = _sq(v_now) * (1 - self.arousal)
        E["distress"] = _sq(-v_now)
        E["interest"] = _sq((iz - 1) / 2)
        E["disgust"] = _sq(_sq(-taste) + 0.5 * o["nausea"])
        if ev["ate"] and taste < -0.2:                                   # conditioned taste aversion: one bad meal is enough
            self.aversion[("eat", ev["ate"])] = min(self.aversion.get(("eat", ev["ate"]), 0.0), taste)
        E["startle"] = startle
        E["calmness"] = _sq(0.4 + self.mood) * (1 - self.arousal) * (1 - threat)
        dull = (self.rate_life - self.rate_now) / (self.rate_life + 1e-3)
        E["boredom"] = _sq((dull - 0.3) / 0.5) * _sq(1.2 - self.arousal * 2) * (1 - threat) * float(not threat_near)
        E["confusion"] = _sq(self.fm_surprise / 3) * (1 - _sq(world_lp * 10)) * _sq(self.arousal * 2)
        E["aesthetic"] = _sq(sky_lp * 8) * (0.5 + colours)
        E["entrancement"] = E["aesthetic"] * _sq(self.look_streak / 4)
        E["craving"] = _sq((jz - 1) / 2) * _sq((20 - o["hunger"]) / 10)
        E["joy"] = L["joy"]
        E["sadness"] = L["sadness"]
        E["grief"] = L["grief"]
        E["fear"] = L["fear"] * (0.5 + 0.5 * float(threat_near or pain > 0))
        E["anxiety"] = _sq((hz - 1.5) / 2) * (1 - float(threat_near))
        E["anger"] = L["anger"]
        E["frustration"] = _sq((fz - 1) / 2) * float(goal_failed is not False)
        E["surprise"] = _sq((z - 2) / 2 + startle * 0.5 + novelty * 0.5)
        sh, sj = np.sqrt(self.stats["harm"][1]) + 1e-3, np.sqrt(self.stats["joy"][1]) + 1e-3
        E["relief"] = _sq(((prev_h - h) / sh - 1) / 2) * float(pain == 0)
        E["disappointment"] = _sq(((prev_j - j) / sj - 1) / 2) * float(taste <= 0)
        E["hope"] = _sq((jz - 0.5) / 2) * _sq(L["sadness"] + L["fear"] + _sq(-v_now))
        E["excitement"] = _sq((jz - 1.5) / 2) * _sq(self.arousal * 2)
        E["satisfaction"] = _sq(taste) + (0.5 if goal_failed is False else 0.0)
        E["amusement"] = _sq((z - 1.5) / 2) * _sq(v_now * 2) * (1 - threat) * float(not threat_near) * (1 - startle)
        E["awe"] = _sq(E["aesthetic"] * 1.5) * _sq(novelty + (1.0 if self.look_streak == 1 else 0.0))
        E["love"] = L["love"]
        E["adoration"] = _sq(dear_near) * float("purr" in ev["sounds"] or tone == 1)
        E["loneliness"] = _sq((self.since_social - 600) / 1200) * _sq(sum(self.attach_being.values()))
        E["gratitude"] = L["gratitude"]
        E["trust"] = _sq(self.help.get("carer", 0.0)) * float(watched)
        E["empathic_pain"] = _sq(hurt_dear * 2 + dead_dear)
        E["horror"] = L["horror"]
        E["admiration"] = float(ev["carer_did"] is not None) * (1 - competence)
        E["envy"] = float(o.get("carer_holds") in ("fish", "gem") and watched and not inv_before.get("fish")) * _sq(joy_ahead + 0.3)
        E["jealousy"] = float(ev["cat_with_carer"]) * _sq(max((a for b, a in self.attach_being.items()
                                                                 if self.kind_of.get(b) == "mycat"), default=0.0))
        E["schadenfreude"] = _sq(0.5 * len(blamed_died)) * _sq(L["anger"] + 0.3)
        E["contempt"] = _sq(max((self.blame.get(k, 0) for k in kinds_near), default=0.0) - 0.3) * coping * (1 - threat)
        E["embarrassment"] = float(watched) * _sq((pain > 0) * 0.5 + (tone == 3) * 0.7)
        unknown = act is not None and act != 10 and (int(act), int(front_before)) not in self.approval
        E["awkwardness"] = float(watched) * float(unknown) * _sq(self.arousal * 2) * 0.6
        E["pride"] = L["pride"]
        E["shame"] = L["shame"]
        E["guilt"] = L["guilt"]
        E["regret"] = _sq(-delta) * float(bool(lost) or self_caused_harm or pain > 0) * float(act is not None and act != 10)
        E["despair"] = _sq(L["sadness"] - 0.3) * _sq(1 - coping)
        self.sad_avg += 0.001 * (L["sadness"] + L["grief"] - self.sad_avg)    # sadness that lasts for days
        E["depression"] = _sq((self.sad_avg - 0.35) / 0.4) * _sq(1.2 - coping)
        E["determination"] = _sq(L["anger"] + L["sadness"] - 0.5) * coping
        E["nostalgia"] = self._nostalgia(o, dear_near)
        for k in KEYS:                                                   # what is not yet possible at this age
            if STAGE_OF.get(k, 1) > st:
                E[k] = 0.0
        strong = [k for k in KEYS if E[k] > 0.35]
        for k in strong:
            self.counts[k] += 1
            self.first_felt.setdefault(k, self.age)
        if len(strong) >= 2:
            self.mixed += 1
        # causes, for the diary and speech (read out of what just happened)
        cause = []
        if lost:
            cause.append(f"разрушено то, что мне дорого ({len(lost)} блоков" + (f", в сундуке было {sum(lost_items.values())} вещей" if lost_items else "") + ")")
        if dead_dear:
            cause.append("погиб тот, кого я люблю" + (f" ({'мой кот' if 'mycat' in dear_kinds else dear_kinds[0]})" if dear_kinds else ""))
        if self.blamed_now and (lost or dead_dear or pain):
            cause.append(f"виноват {self.blamed_now}")
        if ev["ate"]:
            cause.append(f"ем {ev['ate']}")
        if E["aesthetic"] > 0.35:
            cause.append("смотрю на небо")
        self.cause_text = "; ".join(cause)
        if max(E.values()) > 0.5 or lost or dead_dear:
            self._remember(o, v_now, E)
        # ---- what the striatum feels from inside (interoception of emotion)
        feat = [int(v_now * 2 + 2), min(3, int(self.arousal * 4)), min(3, int(L["anger"] * 4)),
                min(3, int(E["fear"] * 4)), min(3, int(L["sadness"] * 4)), min(3, int(dear_near * 2)),
                min(3, int(E["loneliness"] * 4))]
        self.last_valence = v_now
        self.appraised = r - dh + dj                                     # good for me = pleasure now + less harm / more joy ahead
        return r, feat

    # ---------------------------------------------------------------- memory
    def _remember(self, o, v, E):
        top = sorted(E.items(), key=lambda kv: -kv[1])[:3]
        self.episodes.append({"age": self.age, "t": o["t"], "pos": tuple(o["pos"]), "v": v,
                              "feel": [(k, round(x, 2)) for k, x in top if x > 0.2], "why": self.cause_text,
                              "near": sorted({k for k, _, dd in o["near"] if dd <= 2}),
                              "sky": int(o["sky"][0]) if len(o["sky"]) == 1 else int(np.bincount(o["sky"]).argmax()),
                              "strength": abs(v) + max(E.values())})
        if len(self.episodes) > 3000:                                    # forgetting: the weakest go first
            self.episodes.sort(key=lambda e: e["strength"] * np.exp(-(self.age - e["age"]) / 50000))
            self.episodes = self.episodes[500:]

    def _nostalgia(self, o, dear_near):
        """A warm memory from this place or this kind of sky, from a time with someone who is not here now."""
        if self.age % 10 or not self.episodes:
            return self.e.get("nostalgia", 0.0) * 0.9
        here, now_near = tuple(o["pos"]), {k for k, _, dd in o["near"] if dd <= 2}
        best = 0.0
        for ep in self.episodes[-400:]:
            if ep["v"] < 0.3 or self.age - ep["age"] < 1500:
                continue
            same_place = abs(ep["pos"][0] - here[0]) + abs(ep["pos"][1] - here[1]) <= 2
            missing = set(ep["near"]) - now_near
            if same_place and missing:
                best = max(best, ep["v"] * min(1.0, len(missing)))
        return _sq(best)

    def sleep(self):
        """Sleep: memories are consolidated (the strongest are kept) and feelings settle."""
        for k in self.lingering:
            self.lingering[k] *= 0.7
        for ep in self.episodes:
            ep["strength"] *= 0.97

    def top(self, n=3, thr=0.25):
        return [(k, x) for k, x in sorted(self.e.items(), key=lambda kv: -kv[1])[:n] if x > thr]

    def say(self):
        t = self.top()
        if not t:
            return ""
        s = " и ".join(NAMES[k] for k, _ in t)
        return s[0].upper() + s[1:] + (f" — {self.cause_text}" if self.cause_text else "")
