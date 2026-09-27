"""
Contract tests of the mind's learning from its own actions (no game, a few seconds):

  executed    what comes next is learned for the action the body really did, not the one the mind chose
  not_done    an action that never reached a body teaches nothing about doing it
  bounded     every "how often my action worked" is a share of tries: in [0, 1], successes <= tries
  coincidence it gets dark after dusk whatever I do: the action I happen to do at dusk is not its cause
  real_cause  it gets dark only when I do it at dusk: that action is found as the way
  two_ways    two real ways to the same thing: neither is dismissed because of the other
  pain        pain is never a thing to want, even when it came with a joy
  untried     not knowing how to get something, what I have never tried for it comes before repeating
  catching_up ... but once tried, it pulls no more (not "wait" 400 times until it has been tried as often)
  in_vain     what I did again and again for it in vain pulls less and less (not 165 sticks for food)
  blocked     what I meant and was refused (a veto) counts as tried: not reached for again and again
  futile      it learns when an action does nothing (smelting without a furnace) and does not reach for it there
  drive       never sheltered, nothing told: the fear of the dark makes shelter wanted, and the way is found
  need        a strong need (starving) breaks into what I decided, and I go back to it after
  routine     a way that worked is remembered whole (only the steps that changed something) and followed
              while the skill is young: the first nights go faster
  artifacts   a way remembered keeps the steps that lead to it (planks, sticks), not the grass broken on the way
  focus       frightened or needy, what I decided yields only to what ends the need - not to any wish
  need_passes when the need that made a goal passes (day came), the goal goes; a strong need breaks into any goal
  helper      "with it, it goes better" compared in one kind of situation (dirt in hand does not heal)
  glance      a new wish must win three times in a row to replace what I decided (not at a glance)
  step        a step on the way to what I decided (a table for the pickaxe) is not another wish to switch to

    python mind_tests.py
"""
import sys

import numpy as np

from mind import Mind

N_ACT = 8
OBS = (np.zeros(25, np.int64), 0, 0)


def mind(seed=0):
    m = Mind(N_ACT, seed=seed)
    m.contingency = True
    m.planning = False                    # the test decides what is pursued and what is done
    return m


def live(m, world, act, steps, goal=None, seed=0):
    """world(t, a_done) -> the state after moment t; act(t, rng) -> the action the body really does at t."""
    rng = np.random.default_rng(seed)
    did = None
    for t in range(steps):
        if goal is not None:
            m.goal = m._neuron(goal)
        state = world(t, did)
        m.step(OBS, state, 0.0, did=did)
        did = act(t, rng)
    return m


def test_executed():
    m = mind()
    # "got" comes right after action 2 was done; the mind's own choice is never the one done (did = 2 or 5)
    live(m, lambda t, a: {"got": 1.0} if a == 2 else {}, lambda t, rng: 2 if t % 3 == 0 else 5, 600)
    g = m.idx["got"]
    ways = {a for (e, a) in m.ao if e == g}
    assert ways == {2}, f"learned for {ways}, not for what was done (2)"
    assert m.a_count[2] > 0 and m.a_count[5] > 0 and m.a_count.sum() == m.a_count[2] + m.a_count[5]


def test_not_done():
    m = mind()
    live(m, lambda t, a: {"got": 1.0} if t % 2 == 0 else {}, lambda t, rng: -1, 200)
    assert not m.ao, "a step that was never done got credit"
    assert m.a_count.sum() == 0


def test_bounded():
    m = mind(1)
    names = [f"c{i}" for i in range(12)]

    def world(t, a):
        r = np.random.default_rng(t)
        return {k: 1.0 for k in names if r.random() < 0.3}
    live(m, world, lambda t, rng: int(rng.integers(N_ACT)), 4000, goal="c3")
    assert m.ao
    for (e, a), rec in m.ao.items():
        p, p0 = m.ao_effect(rec, 0.0)
        assert rec[3] <= rec[2] and rec[5] <= rec[4], rec
        assert 0.0 <= p <= 1.0 and 0.0 <= p0 <= 1.0, (m.names[e], a, p, p0)


def dusk_world(cause=None):
    """Every 10 moments: dusk, then dark. cause: only this action, done at dusk, brings the dark."""
    def world(t, a):
        if t % 10 == 8:
            return {"dusk": 1.0}
        if t % 10 == 9 and (cause is None or a in cause):
            return {"dark": 1.0}
        return {}
    return world


def at_dusk(t, rng):
    if t % 10 == 8:
        return 1 if rng.random() < 0.6 else int(rng.integers(N_ACT))     # at dusk mostly "look up"
    return int(rng.integers(N_ACT))


def plan_at_dusk(m):
    active = np.zeros(len(m.val), bool)
    active[m.idx["dusk"]] = True
    return m.ao_plan(m.idx["dark"], active)


def test_coincidence():
    m = live(mind(), dusk_world(), at_dusk, 3000, goal="dark")
    a = plan_at_dusk(m)
    assert a is None, f"took action {a} for the cause of the dark (it comes anyway)"


def test_real_cause():
    m = live(mind(), dusk_world(cause={1}), at_dusk, 3000, goal="dark")
    assert plan_at_dusk(m) == 1


def test_two_ways():
    def act(t, rng):
        if t % 10 == 8:
            return int(rng.choice([1, 2, 3, 4]))
        return int(rng.integers(N_ACT))
    m = live(mind(), dusk_world(cause={1, 2}), act, 4000, goal="dark")
    assert plan_at_dusk(m) in (1, 2)
    g = m.idx["dark"]
    for a in (1, 2):
        rec = m.ao[(g, a)]
        p, p0 = m.ao_effect(rec, m.nev[g] / m.steps)
        assert p >= 2 * p0, (a, p, p0)


def test_pain_not_wanted():
    m = mind()
    m.aversive = ("pain:",)
    live(m, lambda t, a: {"pain:zombie": 1.0} if t % 7 == 0 else {"calm": 1.0}, lambda t, rng: 0, 200)
    i = m.idx["pain:zombie"]
    m.R[i] = m.Rc[i] = 2.0                         # it came with a joy (hit while I struck back)
    assert m.desire(np.zeros(len(m.val), bool))[i] < 0, "pain became a thing to want"


def test_step_is_not_a_new_wish():
    m = mind(3)
    m.planning = True
    m.tell([("have:pickaxe", ["have:table"]), ("have:table", ["have:planks"])], {"have:pickaxe": 1.0, "have:table": 0.9})
    m.perceive({"have:planks": 1.0})
    m.intent = m.idx["have:pickaxe"]
    active = m.val > 0
    for _ in range(50):
        m.intent_fails = 3                         # (the pickaxe is far off and has failed: the table looks nearer)
        m.deliberate(active)
        assert m.intent == m.idx["have:pickaxe"], "switched to a step of its own plan: " + m.names[m.intent]


def first_success(try_new, seed):
    """A goal that only action 6 brings (the mind chooses; nothing known yet): moments until the first time."""
    m = mind(seed)
    m.try_new_goal = try_new
    m.drives = {"fed": 1.0}                         # (hungry)
    g = m._neuron("fed")
    k = m.gkeys(m.flat.cells(OBS), g)
    m.G[k, 0] += 1.0 / len(k)                      # a wrong belief: "action 0 gets me fed" (as toggling sprint did)
    m.tries[g] = 20                                # ... and 20 times I set out to get fed, in vain
    did = None
    for t in range(400):
        m.goal = g
        m.step(OBS, {"fed": 1.0} if did == 6 else {"hungry": 1.0}, 0.0)
        if did == 6:
            return t
        did = m._last[1]
    return 400


def test_untried_first():
    with_it = [first_success(2.0, s) for s in range(6)]
    without = [first_success(0.0, s) for s in range(6)]
    assert max(with_it) <= 3 * N_ACT and sum(with_it) * 3 < sum(without),         f"not knowing how, it kept to what it had tried in vain: {with_it} (without the pull: {without})"


def two_wishes(seed=6):
    m = mind(seed)
    m.planning = True
    m.tell([("have:a", ["have:x"]), ("have:b", ["have:x"])], {"have:a": 0.15, "have:b": 1.0})
    m.perceive({"have:x": 1.0})
    m.intent = m.idx["have:a"]
    return m, m.val > 0


def test_not_at_a_glance():
    m, active = two_wishes()
    for k in range(2):
        m.deliberate(active)
        assert m.intent == m.idx["have:a"], f"a wish that won {k + 1} times replaced what I decided"
    m.deliberate(active)
    assert m.intent == m.idx["have:b"], "a wish that keeps winning never replaced it"


def test_rest_after_giving_up():
    def choose(gave_up):
        m = mind(7)
        m.planning = True
        m.tell([("have:a", ["have:x"]), ("have:b", ["have:x"])], {"have:a": 1.0, "have:b": 0.6})
        m.perceive({"have:x": 1.0})
        if gave_up:
            m.given_up[m.idx["have:a"]] = m.steps          # no way to it a moment ago
        m.deliberate(m.val > 0)
        return m.names[m.intent]
    assert choose(False) == "have:a" and choose(True) == "have:b", "given up a moment ago, back at the next glance"


def vain_success(vain, seed):
    """Every action tried once for it already; action 0 believed in strongly and wrongly: moments until the
    goal (only action 6 brings it) comes."""
    m = mind(seed)
    g = m._neuron("fed")
    k = m.gkeys(m.flat.cells(OBS), g)
    m.G[k, 0] += 1.0 / len(k)
    m.tries[g] = 20
    m.goal_tried[g] = np.ones(N_ACT, np.float32)
    m.vain_n = vain
    m.drives = {"fed": 1.0}                         # (hungry: being fed is what I am after)
    did = None
    for t in range(400):
        m.goal = g
        m.goal_t = m.steps
        m.step(OBS, {"fed": 1.0} if did == 6 else {"hungry": 1.0}, 0.0)
        if did == 6:
            return t
        did = m._last[1]
    return 400


def test_in_vain():
    with_it = [vain_success(20, s) for s in range(6)]
    without = [vain_success(10 ** 9, s) for s in range(6)]
    assert sum(with_it) * 2 < sum(without), f"did the same in vain again and again: {with_it} (without: {without})"


def test_nothing_to_eat():
    m = mind(8)
    g = m._neuron("fed")
    k = m.gkeys(m.flat.cells(OBS), g)
    m.G[k, 0] += 1.0 / len(k)                       # "eat" (0) is what fed me - when there was food
    m.tries[g] = 20
    m.goal_tried[g] = np.ones(N_ACT, np.float32)
    m.goal_vain[g] = np.full(N_ACT, float(m.vain_n), np.float32)
    m.goal_vain[g][0] = 0                           # (eating failed each time: it did nothing, so it was not "in vain")
    m.okb[0], m.a_n[0] = -4.0, 200                  # learned: eating does nothing here (nothing to eat)
    m.ao_lift = lambda goal: 0                      # ... and "eat" is what does it, anywhere
    m.ao_plan = lambda goal, active: None
    chose = []
    for t in range(60):
        m.goal, m.goal_t, m.last_ok = g, m.steps, None
        chose.append(m.step(OBS, {"empty": 1.0}, 0.0))
    assert chose.count(0) <= 8, f"pressed 'eat' with nothing to eat {chose.count(0)} times of 60"


def test_all_in_vain_still_search():
    m = mind(8)
    g = m._neuron("fed")
    m.tries[g] = 20
    m.goal_tried[g] = np.ones(N_ACT, np.float32)
    m.goal_vain[g] = np.full(N_ACT, float(m.vain_n), np.float32)   # no food around: all I did was in vain
    m.suggest = lambda goal: (6, 0.5) if goal == g else None        # I imagine: search further (6)
    chose = []
    for t in range(60):
        m.goal, m.goal_t, m.last_ok = g, m.steps, None
        chose.append(m.step(OBS, {"forest": 1.0}, 0.0))
    assert chose.count(6) >= 40, f"searched only {chose.count(6)} times of 60 with nothing else to do"


def test_no_catching_up():
    import itertools
    m = mind(5)
    g = m._neuron("killed:creeper")
    m.tries[g] = 30
    m.goal_tried[g] = np.full(N_ACT, 10.0, np.float32)
    m.goal_tried[g][4] = 0                          # one action ("wait") was never tried for it, the rest often
    seq = []
    for t in range(40):
        m.goal = g
        m.goal_t = m.steps
        m.step(OBS, {"night": 1.0}, 0.0)
        seq.append(m._last[1])
    longest = max(len(list(x)) for k, x in itertools.groupby(seq) if k == 4) if 4 in seq else 0
    assert 1 <= longest <= 2, f"the one never tried was tried {longest} times in a row (catching up)"


def test_blocked_is_tried():
    m = mind(8)
    g = m._neuron("fed")
    m.tries[g] = 20
    chose6 = 0
    for t in range(120):
        m.goal = g
        m.goal_t = m.steps
        a = m.step(OBS, {"hungry": 1.0}, 0.0)
        if a == 6:                                  # "eat" is always refused (food that once made me sick): wait
            chose6 += 1
            m.acted(4)
    assert chose6 < 2 * 120 / N_ACT, f"reached {chose6} of 120 times for what is always refused, as if never tried"


def test_futile():
    m = mind(9)
    rng = np.random.default_rng(1)
    did, furnace_before = None, False
    for t in range(600):                            # "smelt" (3) does something only with a furnace near
        furnace = bool(rng.random() < 0.5)
        m.last_ok = None if did is None else (furnace_before if did == 3 else True)
        m.step(OBS, {"furnace": 1.0} if furnace else {"field": 1.0}, 0.0, did=did)
        did, furnace_before = int(rng.integers(N_ACT)), furnace
    near, far = np.zeros(len(m.val), bool), np.zeros(len(m.val), bool)
    near[m.idx["furnace"]], far[m.idx["field"]] = True, True
    p_near, p_far = m.p_ok(near)[0][3], m.p_ok(far)[0][3]
    assert p_near > 0.8 and p_far < 0.2, f"smelting: near a furnace {p_near:.2f}, in a field {p_far:.2f}"
    g = m._neuron("fed")                             # not knowing how to get fed, in the field: not smelting
    m.tries[g] = 20
    chose = []
    for t in range(80):
        m.goal, m.goal_t, m.last_ok = g, m.steps, None
        chose.append(m.step(OBS, {"field": 1.0}, 0.0))
    assert chose.count(3) <= 2, f"tried smelting in a field {chose.count(3)} times of 80"


def shelter_nights(seed, nights=25, length=40, drive=True, n_act=30, seq=(2, 5, 7), routines=True):
    """Nights: open (fear 1.0) -> dig -> deeper (0.6) -> dig -> walls all round (0.3) -> a lid -> sheltered (0,
    "safe_night"): three right actions of thirty, in order. Never sheltered before, nothing told.
    -> moments to shelter, night by night."""
    m = Mind(n_act, seed=seed)
    m.contingency = True
    m.use_routines = routines
    fear = [1.0 - k / len(seq) for k in range(len(seq) + 1)]
    took = []
    for night in range(nights):
        phase, did = 0, None
        for t in range(length):
            if did is not None and phase < len(seq) and did == seq[phase]:
                phase += 1
            m.drives = {"safe_night": fear[phase]} if drive else {}
            state = {"night": 1.0, "depth%d" % phase: 1.0}
            if phase == len(seq):
                state["safe_night"] = 1.0
            view = np.zeros(25, np.int64)
            view[12] = phase + 1                     # what I see around me: deeper, walls, the lid
            m.step((view, 0, 0), state, 0.0, did=did)
            did = m._last[1] if m._last is not None else None
            if phase == len(seq):
                took.append(t)
                break
        else:
            took.append(length)
        m.drives = {}
        m.step(OBS, {"day": 1.0}, 0.0)               # morning: the night is over
        m.goal = m.intent = None
    return took


def test_drive_finds_shelter():
    with_it = [np.mean(shelter_nights(s)[-5:]) for s in range(4)]
    without = [np.mean(shelter_nights(s, drive=False)[-5:]) for s in range(4)]
    assert np.mean(with_it) <= 8 and np.mean(without) > 2 * np.mean(with_it),         f"moments to shelter in the last nights: {with_it} (without the drive: {without})"


def test_need_breaks_in():
    m, active = two_wishes()
    m.intent = m.idx["have:b"]                      # busy with something dear...
    m.deliberate(active)
    assert m.intent == m.idx["have:b"]
    m._neuron("fed")
    m.drives = {"fed": 2.4}                         # ... and starving: the need breaks in (and is gone back from)
    m.deliberate(m.val > 0)
    assert m.names[m.intent] == "fed" and m.intent_saved == m.idx["have:b"], m.names[m.intent]


def test_routine_speeds_learning():
    with_it = np.mean([np.mean(shelter_nights(s)[:10]) for s in range(6)])
    without = np.mean([np.mean(shelter_nights(s, routines=False)[:10]) for s in range(6)])
    assert with_it < 0.9 * without, f"first nights: {with_it:.1f} moments with routines, {without:.1f} without"


def test_routine_without_artifacts():
    m = mind(11)
    g, planks, stick, grass = (m._neuron(k) for k in ("have:pickaxe", "have:planks", "have:stick", "broke:grass"))
    m.tell([("have:pickaxe", ["have:planks", "have:stick"])], {})
    m._path = [(3, frozenset({grass})), (5, frozenset({planks})), (6, frozenset({stick})), (7, frozenset({g}))]
    m._path_ctx = frozenset()
    m._learn_routine(g)
    assert m.routines[g][0]["acts"] == [5, 6, 7], m.routines[g][0]["acts"]   # not "break grass to get a pickaxe"


def test_danger_keeps_focus():
    m = mind(12)
    m.planning = True
    m.tell([("have:a", ["have:x"]), ("have:b", ["have:x"])], {"have:a": 0.5, "have:b": 1.0})
    m.perceive({"have:x": 1.0})
    active = m.val > 0
    m.urgent_ctx = (3,)
    m.ctx = 3                                       # frightened (hungry, hurt) - but nothing it wants ends it
    m.intent = m.idx["have:a"]
    for _ in range(4):
        m.deliberate(active)
        assert m.intent == m.idx["have:a"], "danger broke what I decided for a wish that does not end it"


def test_need_passes_and_breaks_in():
    m = mind(13)
    m.planning = True
    m.tell([("have:a", ["have:x"])], {"have:a": 1.0})
    night = m._neuron("safe_night")
    m.drives = {"safe_night": 3.0}
    m.intent = m.goal = night
    m.goal_t = m.steps
    m.drives = {}                                   # the day came: the need that made it passed
    for _ in range(12):
        m.step(OBS, {"have:x": 1.0}, 0.0)
    assert m.intent != night and m.goal != night, "still after a safe night by day"
    m.goal = m._neuron("have:a")                    # busy - and then starving: the stomach breaks in
    m.intent, m.goal_t = m.goal, m.steps
    m.drives = {"fed": 4.0}
    for _ in range(12):
        m.step(OBS, {"have:x": 1.0}, 0.0)
    assert m.goal == m.idx["fed"], m.names[m.goal] if m.goal is not None else None


def test_dire_need_first():
    m = mind(15)
    m.planning = True
    m.tell([("have:gem", ["have:x"])], {"have:gem": 3.9})      # something dearer than anything, and at hand
    m.perceive({"have:x": 1.0})
    fed = m._neuron("fed")
    m.drives = {"fed": 3.0}                                   # starving
    for _ in range(10):
        m.intent = None
        m.deliberate(m.val > 0)
        assert m.intent == fed, "starving, and after a gem"


def test_need_without_a_way():
    m = mind(14)
    m.planning = True
    fed, bowl = m._neuron("fed"), m._neuron("have:bowl")
    m.tell([("fed", ["have:bowl"]), ("have:bowl", ["have:spoon"]), ("have:spoon", ["have:bowl"])], {})   # out of reach
    m.drives = {"fed": 4.0}
    m.deliberate(m.val > 0)
    assert m.intent == fed, "starving, with no way I know of - and not even trying"


def test_need_not_through_a_failing_step():
    m = mind(14)
    m.planning = True
    ate, dirt = m._neuron("ate"), m._neuron("reach:dirt")
    m.tell([("ate", ["reach:dirt"])], {})           # dirt was around whenever I ate (not what fed me)
    m.drives = {"ate": 4.0}
    sub = m.deliberate(m.val > 0)
    assert m.intent == ate and sub == dirt, "the step I believe in is tried first"
    m.intent_fails = 3                              # the step failed again and again
    sub = m.deliberate(m.val > 0)
    assert m.intent == ate and sub == ate, "hungry, still going for the dirt that keeps failing"
    m.intent_fails = 0
    m.suggest = lambda g: (6, 0.7) if g == ate else None     # I can imagine the way to food
    sub = m.deliberate(m.val > 0)
    assert sub == ate, "hungry, going for the dirt that was around, though I can imagine the way to food"


def test_need_sees_a_way_later():
    m = mind(14)
    m.planning = True
    ate, grass = m._neuron("ate"), m._neuron("see:grass_block")
    m.tell([("ate", ["see:grass_block"])], {})      # grass was around whenever I ate
    m.intent = ate                                  # I meant to eat, before I was hungry: the step is the grass
    m.goal, m.goal_t = grass, 0
    m.suggest = lambda g: (6, 0.9) if g == ate else None     # hungry now, and there are apples in my bag
    m.drives = {"ate": 3.0}
    goals = []
    for t in range(12):
        m.step(OBS, {"sea": 1.0}, 0.0)
        goals.append(m.goal)
    assert goals[-1] == ate, f"hungry with apples in the bag, still after the grass: {[m.names[g] if g is not None else None for g in goals]}"


def sky_meals(seed, sky_needed, steps=400):
    """Days: the sky is out 2 moments of 5, and I eat now and then - always under the sky (so "the sky comes
    before eating" is learned). Then a cave: climbing (1) shows the sky for a moment, eating (0) feeds me -
    with the sky just before it, or (sky_needed=False) anyway. -> the mind after the cave."""
    m = mind(seed)
    live(m, lambda t, a: {"sky": 1.0, "ate": 1.0} if a == 0 else {"sky": 1.0} if t % 5 < 2 else {"dark": 1.0},
         lambda t, rng: 0 if t % 25 == 0 else int(rng.integers(2, N_ACT)), 500)
    ate, sky = m.idx["ate"], m.idx["sky"]
    assert sky in m.pre(ate), "the sky before eating was not even learned"
    m.planning = True
    m.drives = {"ate": 3.0}
    prev = None
    for t in range(steps):
        a = m._last[1] if m._last is not None else None
        st = {"dark": 1.0}
        if a == 1:
            st = {"sky": 1.0}
        elif a == 0 and (not sky_needed or prev == 1):
            st = {"ate": 1.0, "dark": 1.0}
        m.step(OBS, st, 0.0)
        prev = a
    return m, ate, sky


def test_false_link_found():
    import mind as M
    m, ate, sky = sky_meals(3, sky_needed=False)
    assert m.link_false(ate, sky) and sky not in m.pre(ate), \
        f"ate without the sky, still thinks it needs it (tests {m.links.get((ate, sky))})"


def test_real_link_kept():
    m, ate, sky = sky_meals(3, sky_needed=True)
    n = m.links.get((ate, sky), [0, 0])[0]
    assert not m.link_false(ate, sky) and sky in m.pre(ate), f"a real condition was thrown away ({m.links.get((ate, sky))})"
    assert n <= 4, f"tested a real condition {n} times"


def test_no_hunger_no_wish_to_eat():
    m = mind(2)
    ate = m._neuron("ate")
    m.R[ate] = m.Rc[ate] = 1.0                      # eating was very good (when I was hungry)
    m.nc[ate], m.nev[ate] = 5, 10
    active = np.zeros(len(m.val), bool)
    m.drives = {}
    assert m.desire(active)[ate] <= 0, "full, and still wants to eat"
    m.drives = {"ate": 2.0}
    assert m.desire(active)[ate] >= 2.0, "hungry, and does not want to eat"


def test_helper_not_a_situation():
    m = mind(4)
    m.helper_kinds = ("hold:",)
    rng = np.random.default_rng(0)
    dirt, sword = m._neuron("hold:dirt"), m._neuron("hold:sword")
    healthy, killed = m._neuron("healthy"), m._neuron("killed:zombie")
    for _ in range(400):
        calm = rng.random() < 0.5                   # calm days: dirt in hand, health comes back; nights: fighting
        m.goal_ctx = 0 if calm else 3
        m._goal_on = np.array([dirt] if calm and rng.random() < 0.9 else [sword] if rng.random() < 0.5 else [], int)
        m._helps_learn(healthy, rng.random() < (0.9 if calm else 0.3))    # dirt or not, it is the situation
        m.goal_ctx = 3
        has = rng.random() < 0.5
        m._goal_on = np.array([sword] if has else [], int)
        m._helps_learn(killed, rng.random() < (0.8 if has else 0.3))      # the sword really helps
    active = np.zeros(len(m.val), bool)
    for ctx in (0, 3):
        m.ctx = ctx
        assert dirt not in [h for h, _, _ in m.helpers(healthy, active)], f"dirt in hand 'helps' health (ctx {ctx})"
    m.ctx = 3
    assert sword in [h for h, _, _ in m.helpers(killed, active)], "the sword that helps was not found"


def test_habits_do_not_run_away():
    from brain_agent import BrainAgent, W_MAX

    b = BrainAgent(4, seed=0)
    obs = (np.zeros(30, np.int64),) * 5
    cells = np.arange(20, dtype=np.int64)
    for i in range(3000):                               # another's choices, huge rewards and a nonsense one
        r = float("nan") if i == 7 else (1e6 if i % 2 else -1e6)
        b.learn(cells, i % 4, r, obs, cells, b.W[cells].sum(0), (i + 1) % 4, False)
    b.remember(cells, 0, 1e6, cells, False)
    for _ in range(600):
        b.remember(cells, 1, -1e6, cells, False)
    b.replay(200)
    assert np.isfinite(b.W).all() and np.abs(b.W).max() <= W_MAX, np.abs(b.W).max()


if __name__ == "__main__":
    failed = 0
    for name, fn in [(k, v) for k, v in dict(globals()).items() if k.startswith("test_")]:
        try:
            fn()
            print("ok  ", name)
        except AssertionError as e:
            failed += 1
            print("FAIL", name, "-", e)
    sys.exit(1 if failed else 0)
