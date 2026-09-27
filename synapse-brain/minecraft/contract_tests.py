"""
The contract between the body and the brain (no game, no server; a few seconds): each answer to the body is
numbered, the body's report of an action says which answer it was, and the mind learns only from what the
body really did.

  echoed       a report with the right number: learned for that action
  stale        a report of another answer (a reconnect, a lost reply): nothing is learned about doing it
  interrupted  cut off (death, pause, the safety net): nothing is learned about doing it
  forced       the experimenter's hand: learned as what was done, and marked in the record
  aim          a step of the plan is to have X: the hands aim at what gave X when broken (learned), not at grass
  body_cannot  an action this body does not have: it waits, and the mind knows it waited
  worth        a thing is worth what it helps with (found per situation)
  schema       "crafting T gives T when the book shows it" - learned on planks and sticks, used for a table
  recipe_book  the game's recipe book, opened: its recipes become chains in the mind
  imagine      hungry, the pieces learned apart (chicken leaves chicken; eating it fed me; chickens were there):
               the way never gone whole is played in the head - go there, strike a chicken, eat
  counts       the recipe book's counts: a pickaxe needs two sticks, I have one - sticks first
  shut         with the knowledge channels shut, the guide, the reference, the path, imitation stay silent

    python contract_tests.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "agent"))
sys.path.insert(0, HERE)

from actions import ACTIONS  # noqa: E402

WAIT = ACTIONS.index("wait") if "wait" in ACTIONS else 4


def message(act=None, **kw):
    m = {"obs": [0] * 25, "health": 20, "food": 20, "items": {"oak_log": 1}, "near": [], "time": 1000, "pitch": 0,
         "xz": [0, 0], "y": 64, "dim": "overworld", "n_actions": len(ACTIONS)}
    if act is not None:
        m["act"] = act
    m.update(kw)
    return m


def brain():
    import feel_bridge
    from brain_core import Grown

    child = feel_bridge.MCChild(len(ACTIONS))
    return child, Grown(child, None, None, log=lambda *a: None)


def report(core, a, **kw):
    return {"a": a, "action": ACTIONS[a], "ok": True, "ticks": 3, "id": core.moment_id, **kw}


def test_echoed():
    child, core = brain()
    a, _, _, _ = core.decide(message())
    m = message(report(core, a))
    core.decide(m)
    assert m["_did"] == a and core.contract["stale"] == 0


def test_stale():
    child, core = brain()
    a, _, _, _ = core.decide(message())
    r = report(core, a)
    r["id"] += 7                                     # the answer to some other moment
    m = message(r)
    core.decide(m)
    assert m["_did"] == -1 and core.contract["stale"] == 1


def test_interrupted():
    child, core = brain()
    a, _, _, _ = core.decide(message())
    m = message(report(core, a, interrupted=True, ok=False))
    core.decide(m)
    assert m["_did"] == -1 and core.contract["interrupted"] == 1
    assert child.mind.last_ok is None                # "it did nothing" is not learned from a cut-off action


def test_forced():
    child, core = brain()
    core.decide(message())
    chose = None
    for force in (5, 6):
        m = message(report(core, core.a_prev))
        a, _, _, _ = core.decide(m, force=force)
        chose = m["_chose"]
        assert a == force and child.mind._last[1] == force, (a, child.mind._last)
        assert bool(m.get("_intervention")) == (chose != force)
    assert core.contract["changed"] >= 1 or chose == 6


def test_body_cannot():
    child, core = brain()
    for _ in range(40):                              # a body with 3 actions: whatever the mind wants beyond them
        m = message(n_actions=3)
        a, _, _, _ = core.decide(m)
        assert a < 3 or a == WAIT
        if m["_chose"] >= 3:
            assert a == WAIT and child.mind._last[1] == WAIT
            return
    raise AssertionError("the mind never chose beyond the body in 40 moments (try another seed)")


def test_aim():
    import feel_bridge

    child, core = brain()
    for _ in range(3):                               # the body said: oak log gave a log, grass gave dirt
        child.yields.learn("oak_log", ["oak_log"])
        child.yields.learn("grass_block", ["dirt"])
    child.mind.goal = child.mind._neuron("have:oak_log")
    mine = ACTIONS.index("mine_target")
    both = {"seen": [["grass_block", 2, "block"], ["oak_log", 6, "block"]]}
    assert feel_bridge.attention(child, mine, both) == "oak_log"
    grass = {"seen": [["grass_block", 2, "block"]]}  # the tree is out of sight: go and look, not dig the grass
    assert feel_bridge.attention(child, mine, grass) == "oak_log"
    child.mind.goal = child.mind._neuron("have:dirt")
    assert feel_bridge.attention(child, mine, both) == "grass_block"


def test_worth():
    import feel_bridge

    child, core = brain()
    m = child.mind
    g, sword = m._neuron("killed:zombie"), m._neuron("hold:wooden_sword")
    m.R[g] = 2.0
    m.helps[(g, 3)] = [20.0, 12.0, {sword: [10.0, 9.0]}]   # at night, with a sword in hand it went better
    assert feel_bridge.worth_of(child, "wooden_sword") > 0.5, "a sword is worth what fighting goes better with it"


def test_schema():
    import feel_bridge

    child, core = brain()
    sc = child.schemas
    for thing in ("oak_planks", "stick", "oak_button"):   # I made these from the book: crafting T gives T
        before = message(craftable=[thing])
        sc.aim("craft_target", thing, before)
        sc.outcome(message(items={"oak_log": 1, thing: 1}))
    m = message(craftable=["crafting_table"], items={"oak_planks": 4})
    child.m = m
    g = child.mind._neuron("have:crafting_table")         # never made a table: the schema holds for it too
    a, p = child._suggest(g)[:2]
    assert ACTIONS[a] == "craft_target" and p >= 0.5, (ACTIONS[a], p)
    assert feel_bridge.attention(child, a, m) == "crafting_table"
    m = message(items={"oak_planks": 4})                  # the book does not show it: the schema promises nothing
    assert sc.plan("have:crafting_table", m, None) is None


def test_schema_coincidence():
    child, core = brain()
    sc = child.schemas
    far = message(seen=[["oak_log", 6, "block"]])
    near = message(seen=[["oak_log", 2, "block"]])
    for kind in ["craft_target"] * 3 + ["turn_left", "look_up", "jump"] * 3:   # it came near whatever I did
        sc.aim(kind if kind != "craft_target" else "craft_target", "oak_log", far)
        if kind != "craft_target":
            sc.aimed = (kind, "oak_log", sc.aimed[2] if sc.aimed else frozenset({"see"}), {})
        sc.outcome(near)
    assert sc.p("craft_target", "reach", frozenset({"see"})) is None, "crafting 'brings logs near'"


def test_recipe_book():
    child, core = brain()
    core.decide(message())
    m = message(report(core, core.a_prev), fev={"recipes": [["wooden_pickaxe", {"oak_planks": 3, "stick": 2}, True, False]]})
    core.decide(m)
    mind = child.mind
    e = mind.idx["have:wooden_pickaxe"]
    told = {mind.names[i] for i in mind.told_pre.get(e, ())}
    assert told == {"have:oak_planks", "have:stick", "at_table"}, told
    assert any(k == "read" for k, _ in m["_events"])


def test_imagine():
    import numpy as np

    child, core = brain()
    mind = child.mind
    for _ in range(3):                                    # lived: a chicken felled leaves chicken
        child.yields.learn("mob:chicken", ["chicken"])
    fed, meat = mind._neuron("fed"), mind._neuron("have:chicken")
    eat = ACTIONS.index("eat")                            # lived: eating with chicken in the bag -> fed
    mind.ao[(fed, eat)] = [3.0, (np.array([meat], np.int32), np.array([3.0], np.float32)), 3.0, 3.0, 0.0, 0.0]
    mind._ao_index()
    mind.nev[fed], mind.steps = 3, 1000
    child.places.places["chicken"] = [[10, 64, 10, "overworld", 0, 3]]   # where I saw chickens
    mind.perceive({"hungry": 1.0})
    child.m = message(pos=[0, 64, 0])
    a, p = child._suggest(fed)[:2]                            # never went this way whole: imagined from the pieces
    assert ACTIONS[a] == "goto_place" and child.aim_at[1] == [10, 64, 10], (ACTIONS[a], child.aim_at)
    assert "ударить" in child.imagined and "есть" in child.imagined, child.imagined
    mind.perceive({"hungry": 1.0, "see:chicken": 1.0})   # the chickens in sight: strike
    child.m = message(pos=[0, 64, 0], seen=[["chicken", 6, "mob"]])
    a, p = child._suggest(fed)[:2]
    assert ACTIONS[a] == "attack" and child.aim_at[1] == "chicken", (ACTIONS[a], child.aim_at)


def test_imagine_counts():
    child, core = brain()
    mind = child.mind
    child.recipes_read = {"wooden_pickaxe": [{"oak_planks": 3, "stick": 2}, True], "stick": [{"oak_planks": 2}, False],
                          "crafting_table": [{"oak_planks": 4}, False]}
    mind.tell([("at_table", ["have:crafting_table"])], {})
    mind.perceive({"have:oak_planks": 1.0, "have:stick": 1.0, "at_table": 1.0})
    child.m = message(items={"oak_planks": 3, "stick": 1, "crafting_table": 1}, craftable=["stick"])
    g = mind._neuron("have:wooden_pickaxe")
    a, p = child._suggest(g)[:2]                              # one stick short: sticks first, not the pickaxe in vain
    assert ACTIONS[a] == "craft_target" and child.aim_at[1] == "stick", (ACTIONS[a], child.aim_at, child.imagined)


def test_stone_needs_a_pickaxe():
    child, core = brain()
    ys = child.yields
    for _ in range(3):                                    # lived: stone by hand gives nothing, with a pickaxe cobblestone
        ys.learn("stone", [], "hand")
        ys.learn("stone", ["cobblestone"], "wooden_pickaxe")
    assert ys.p("stone@wooden_pickaxe", "cobblestone") > 0.7 and ys.p("stone@hand", "cobblestone") == 0
    child.recipes_read = {"wooden_pickaxe": [{"oak_planks": 3, "stick": 2}, True]}
    mind = child.mind
    mind.tell([("at_table", ["have:crafting_table"])], {})
    mind.perceive({"have:oak_planks": 1.0, "have:stick": 1.0, "have:crafting_table": 1.0, "at_table": 1.0,
                   "see:stone": 1.0})
    child.m = message(items={"oak_planks": 3, "stick": 2, "crafting_table": 1}, seen=[["stone", 3, "block"]],
                      craftable=["wooden_pickaxe"])
    way = child.imagination.plan("have:cobblestone")     # the pickaxe first, then the stone
    kinds = [(o.kind, o.target) for o in way]
    assert kinds == [("craft_target", "wooden_pickaxe"), ("mine_target", "stone")], kinds


def test_starving_is_felt():
    child, core = brain()
    m = message()
    m["food"], m["health"] = 0, 3.0                       # 0 food is starving, not "unknown, so full"
    core.decide(m)
    assert child.mind.drives.get("ate", 0) >= 3.9, child.mind.drives


def test_hunger_wants_a_bite():
    child, core = brain()
    child.edible = {"porkchop"}
    child.mind.perceive({"have:porkchop": 1.0})
    child.m = message(items={"porkchop": 2})
    first, words = child.imagination.first_step("ate")     # hungry with a porkchop in the bag: eat it
    assert first[0] == "eat", (first, words)


def test_home():
    child, core = brain()
    core.decide(message())
    sealed = [5 * 6 + 5] * 4                              # walls at feet and head on all four sides
    m = message(report(core, core.a_prev), time=14000, sky=0, around=sealed, pos=[100, 64, 100])
    core.decide(m)                                        # night, closed in, safe: a home
    assert child.places.home(m) == [100, 64, 100], child.places.homes
    child.m = message(time=12500, pos=[140, 64, 120])     # evening, far from home: go home
    child.mind.perceive({"know:home": 1.0})
    first, words = child.imagination.first_step("safe_night")
    assert first[0] == "goto_place" and first[1] == [100, 64, 100], (first, words)


def test_could_not_get_there():
    child, core = brain()
    child.places.places["oak_log"] = [[20, 64, 0, "overworld", 0, 3]]
    core.decide(message(pos=[0, 64, 0]))
    core.last_target = [20, 64, 0]                        # I set out for the logs over there...
    m = message(report(core, ACTIONS.index("goto_place"), ok=False, why="застрял по дороге"), pos=[5, 64, 0])
    core.decide(m)                                        # ... and got stuck on the way
    assert child.places.nearest("oak_log", m) is None, "sets out again for where it just got stuck"
    child.places.now += 1000                              # a while later: worth another try
    assert child.places.nearest("oak_log", m) == [20, 64, 0]


def test_plan_is_carried_out():
    child, core = brain()
    mind = child.mind
    child.limbic.stage = lambda: 1                                 # (grown: the prefrontal cortex plans)
    child.recipes_read["oak_planks"] = [{"oak_log": 1}, False]    # the recipe book: planks from a log
    mind.tell([("have:oak_planks", ["have:oak_log"])], {}, source="книга рецептов")
    mind.planning = True
    craft = ACTIONS.index("craft_target")
    did = []
    for i in range(12):                                            # a log in my bag: the plan's step is carried out
        mind.explore_left = 0                                      # (not looking around first)
        a, _, _, _ = core.decide(message(report(core, core.a_prev) if i else None, items={"oak_log": 3}))
        did.append(ACTIONS[a])
        if a == craft and core.expect is not None:
            break
    assert did[-1] == "craft_target" and child.mind.how == "plan", (did, child.mind.how)
    assert core.expect["effect"].startswith("have:oak_planks"), core.expect
    ev = []
    m = message(report(core, craft), items={"oak_planks": 4, "oak_log": 2}, _events=ev)   # the planks came
    core.decide(m)
    assert any(k == "step" and t.startswith("✓") for k, t in m["_events"]), m["_events"]


def test_step_that_fails_is_trusted_less():
    child, core = brain()
    im = child.imagination
    from imagine import Op
    op = Op("have:oak_log", "mine_target", "oak_log", ["see:oak_log"], 0.8, "")
    before = im.trust(op)
    for _ in range(4):                                             # struck the log four times: nothing came
        im.learned("mine_target", "oak_log", "have:oak_log", False)
    assert im.trust(op) < 0.5 * before, (before, im.trust(op))
    im.learned("mine_target", "stone", "have:cobblestone", True)   # (another kind of step is not touched)
    assert im.trust(Op("have:cobblestone", "mine_target", "stone", [], 0.8, "")) == 1.0


def test_hands_aim_at_the_real_thing():
    import feel_bridge
    m = message(seen=[["spruce_log", 5, "block"], ["birch_log", 9, "block"]], craftable=["spruce_planks", "stick"])
    assert feel_bridge.concrete("mine_target", "oak_log", m) == "spruce_log"        # a log, as my plan says: this one
    assert feel_bridge.concrete("craft_target", "oak_planks", m) == "spruce_planks"  # planks of the logs I have
    assert feel_bridge.concrete("craft_target", "stick", m) == "stick"


def test_core_needed_is_what_it_failed_without():
    child, core = brain()
    k = child.core
    for i in range(3):                                   # with a pickaxe, under the sky: cobblestone
        k.learn({"see:stone", "have:wooden_pickaxe", "sky"}, {"wooden_pickaxe": 1}, set(),
                {"wooden_pickaxe": 1, "cobblestone": 1 + i}, "mine_target", "stone", True)
    for _ in range(2):                                   # without one: nothing
        k.learn({"see:stone", "sky"}, {}, set(), {}, "mine_target", "stone", True)
    k.learn({"see:stone", "have:wooden_pickaxe"}, {"wooden_pickaxe": 1}, set(),     # in a cave: cobblestone too
            {"wooden_pickaxe": 1, "cobblestone": 1}, "mine_target", "stone", True)
    need = k.ops[("mine_target", "stone")].needs("have:cobblestone")
    assert "have:wooden_pickaxe" in need and "sky" not in need, need


def test_core_made_of_what_it_used_up():
    child, core = brain()
    k = child.core
    k.learn({"have:oak_log"}, {"oak_log": 2}, {"have:oak_log", "have:oak_planks"}, {"oak_log": 1, "oak_planks": 4},
            "craft_target", "oak_planks", True)
    assert "have:oak_log" in k.ops[("craft_target", "oak_planks")].needs("have:oak_planks")


def test_core_hungry_eats_first():
    child, core = brain()
    child.limbic.stage = lambda: 1
    child.edible.add("apple")
    child.recipes_read["oak_planks"] = [{"oak_log": 1}, False]      # (something new to make, too)
    did = []
    for i in range(4):
        a, _, _, _ = core.decide(message(report(core, core.a_prev) if i else None, food=3,
                                         items={"apple": 2, "oak_log": 3}))
        did.append(ACTIONS[a])
    assert did[-1] == "eat" and child.core.goal == "ate", (did, child.core.goal)


def test_core_once_is_not_a_way():
    child, core = brain()
    k = child.core
    k.learn({"hold:fishing_rod"}, {}, {"see:sand"}, {}, "fish", None, True)     # sand came into sight as I fished
    child.m = message()
    ways = [s.op.kind for s in k.ways("see:sand", set(), {})]
    assert "fish" not in ways, ways


def test_core_what_hurt_is_dearer():
    child, core = brain()
    k = child.core
    for i in range(4):                                   # a zombie gave rotten flesh - and cost me 8 health each time
        k.learn({"see:zombie"}, {}, {"see:zombie"}, {"rotten_flesh": 1}, "attack", "zombie", True, 8.0)
        k.learn({"see:cow"}, {}, {"see:cow"}, {"beef": 1}, "attack", "cow", True, 0.0)
    for food in ("rotten_flesh", "beef"):
        for _ in range(3):
            k.learn({"have:" + food}, {food: 1}, {"ate"}, {}, "eat", food, True)
    child.m = message()
    way = k.make_plan("ate", {"see:zombie", "see:cow"}, {})
    assert way and way[0].op.target == "cow", [(s.op.kind, s.op.target) for s in (way or [])]


def test_core_does_what_eased_the_need():
    child, core = brain()
    k = child.core
    for _ in range(3):                                   # digging in eased the fear of the night, three times
        k.learn({"dark"}, {}, {"dark", "walls>=3"}, {}, "dig_down", None, True, 0.0, ["safe_night"])
    for _ in range(3):                                   # jumping about did not
        k.learn({"dark"}, {}, {"dark"}, {}, "jump", None, True, 0.0, [])
    assert k.relief("safe_night", {"dark"}, {}) == ("dig_down", None)


def test_core_sight_never_comes_free():
    child, core = brain()
    m = child.mind
    for name in ("see:pig", "sky", "at_table", "have:crafting_table"):
        m._neuron(name)
    m.told_pre[m.idx["see:pig"]] = {m.idx["sky"]}               # misread: "a pig in sight whenever the sky is"
    m.told_pre[m.idx["at_table"]] = {m.idx["have:crafting_table"]}
    k = child.core
    k.priors()
    assert "see:pig" not in k.told_implied and k.told_implied.get("at_table") == ["have:crafting_table"], k.told_implied
    child.m = message()
    way = k.make_plan("have:porkchop", {"sky"}, {})
    assert not way or way[0].op.kind != "attack", [(s.op.kind, s.op.target) for s in way]


def test_core_eats_what_it_has_before_searching():
    child, core = brain()
    k = child.core
    m = child.mind
    m._neuron("see:potatoes")
    m.base[m.idx["see:potatoes"]] = 0.2                  # potatoes were often around, all my life
    for _ in range(30):                                  # but forty walks here showed none
        k.learn(set(), {}, set(), {}, "explore", None, True)
    for _ in range(3):
        k.learn({"see:potatoes"}, {}, {"see:potatoes"}, {"potato": 1}, "mine_target", "potatoes", True)
        k.learn({"have:potato", "hungry"}, {"potato": 1}, {"ate"}, {}, "eat", "potato", True)
    k.learn({"have:mutton", "hungry"}, {"mutton": 1}, {"ate"}, {}, "eat", "mutton", True)
    for _ in range(25):                                  # mutton: tried mostly when full - it would not go down
        k.learn({"have:mutton"}, {"mutton": 1}, set(), {"mutton": 1}, "eat", "mutton", False)
    k.tell("eat", "mutton", "ate", 0.9, ["have:mutton"])
    k.tell("mine_target", "potatoes", "have:potato", 0.9, ["see:potatoes"])
    child.m = message()
    way = k.make_plan("ate", {"hungry", "have:mutton"}, {"mutton": 2})
    assert way and way[0].op.kind == "eat", [(s.op.kind, s.op.target) for s in (way or [])]


def test_night_fear_is_graded():
    import feel_bridge

    def drive(around, sky):                              # (as the child feels it at night: agent/child.py)
        m = {"around": around, "sky": sky, "light": 4, "time": 18000, "dim": "overworld"}
        v = max(feel_bridge.dark_unease(m), 0.9 * feel_bridge.exposure(m))
        return 4.0 * v * v

    open_ = drive([0, 0, 0, 0, 0, 1], 1)
    pit1 = drive([6, 6, 6, 6, 0, 1], 1)                  # dug in once: earth round my feet
    pit2 = drive([7, 7, 7, 7, 0, 1], 1)                  # twice: round my head too - the sky still open
    roofed = drive([7, 7, 7, 7, 1, 1], 0)                # a block over my head
    assert open_ > pit1 > pit2 > roofed, (open_, pit1, pit2, roofed)
    assert pit1 < open_ - 0.1 and pit2 < pit1 - 0.1      # each step eases it: felt, so it can be learned
    assert pit2 > 0.25 and roofed < 0.05, (pit2, roofed) # an open pit is still a need; a roofed one is safe


def test_core_what_eases_here():
    from core5 import situation

    child, core = brain()
    k = child.core
    field = {"sky", "dark", "need:safe_night"}
    pit = {"sky", "dark", "need:safe_night", "walls>=3", "walls>=5"}
    for _ in range(2):                                   # digging in eased the fear on open ground
        k.learn(field, {}, pit, {}, "dig_down", None, True, 0.0, ["safe_night"])
    for _ in range(3):                                   # deeper in the pit it eased nothing more
        k.learn(pit, {}, pit, {}, "dig_down", None, True, 0.0, [])
    k.learn(field, {}, field, {}, "place_up", None, False)   # a block over my head: nothing to stick to, out there
    child.m = message()
    assert k.relief("safe_night", field, {}) == ("dig_down", None)
    assert k.relief("safe_night", pit, {}) is None
    tried = {k.experiment(pit, need=True)[0] for _ in range(2000)}
    assert "dig_down" not in tried and "place_up" in tried, tried   # (never tried in a pit: worth a try there)
    assert situation(pit) in k.ops[("dig_down", None)].by_sit


def test_core_tries_again_what_eased():
    from collections import Counter

    child, core = brain()
    k = child.core
    field = {"sky", "dark", "need:safe_night"}
    pit = {"sky", "dark", "need:safe_night", "walls>=3", "walls>=5"}
    for a in ACTIONS:                                    # out in the open at night, afraid, I tried everything once
        k.learn(field, {}, field, {}, a, None, True)
    for _ in range(2):                                   # and digging in eased it, twice
        k.learn(field, {}, pit, {}, "dig_down", None, True, 0.0, ["safe_night"])
    for _ in range(3):                                   # in the pit, digging deeper eased nothing more
        k.learn(pit, {}, pit, {}, "dig_down", None, True, 0.0, [])
    child.m = message()
    assert k.eased_by_hand("safe_night") and not k.eased_by_hand("ate")
    out = Counter(k.trial("safe_night", field, {})[0] for _ in range(300))
    assert out["dig_down"] > 250, out.most_common(4)
    pit_picks = Counter(k.trial("safe_night", pit, {})[0] for _ in range(300))
    assert pit_picks["dig_down"] < 15 and not any(a in pit_picks for a in ("drop_item", "drop_junk")), pit_picks.most_common(4)


def test_core_night_hurts_not_the_day():
    from core5 import situation

    child, core = brain()
    k = child.core
    night, day = {"sky", "dark", "need:safe_night"}, {"sky", "day"}
    for _ in range(2):
        k.learn(night, {}, night, {}, "explore", None, True, 20.0)   # walked out into the night: killed
    for _ in range(6):
        k.learn(day, {}, day, {}, "explore", None, True, 0.0)
    o = k.ops[("explore", None)]
    assert o.risk(situation(night)) >= 10 and o.risk(situation(day)) == 0, (o.risk(situation(night)), o.risk(situation(day)))
    path = os.path.join(tempfile.mkdtemp(), "model.json")
    k.save(path)
    child2, _ = brain()
    child2.core.load(path)                               # remembered by situation across a sleep
    assert child2.core.ops[("explore", None)].risk(situation(night)) >= 10


def test_core_walks_where_it_remembers():
    child, core = brain()
    child.places.places["oak_log"] = [[20, 64, 0, "overworld", 0, 3]]
    child.m = message(pos=[0, 64, 0])
    way = child.core.make_plan("see:oak_log", {"sky", "day"}, {})    # (a remembered place: a walk with its own risk)
    assert way and way[0].op.kind in ("goto_place", "explore"), [(s.op.kind, s.op.target) for s in (way or [])]


def test_danger_place():
    child, core = brain()
    child.places.places["oak_log"] = [[20, 64, 0, "overworld", 0, 3]]
    child.places.hurt_here("fall", {"pos": [21, 64, 0], "dim": "overworld"}, 0)    # I fell there
    child.m = message(pos=[0, 64, 0])
    ops = child.imagination.ops("see:oak_log", set())
    goto = [o for o in ops if o.kind == "goto_place"][0]
    assert goto.p < 0.5 and "больно" in goto.why, (goto.p, goto.why)


def test_shut():
    os.environ["SYNAPSE_KNOWLEDGE"] = json.dumps({"guide": False, "recipes": False, "path": False, "imitation": False})
    try:
        import feel_bridge

        feel_bridge._RECIPES.clear()
        child, core = brain()
        assert child.development.guide is None and not child.development.path
        assert child.imitation is None and feel_bridge.recipes() == {}
        core.decide(message())
        m = message(report(core, core.a_prev, ok=False, why="нечего есть", need="have:bread"),
                    pain=[["hit", "zombie", ""]], heard=[["Bleestra", "дерево нужно для досок"]])
        core.decide(m)
        assert "have:bread" not in child.mind.idx, "the body's 'what was missing' reached the mind"
        kinds = {k for k, _ in m["_events"]}
        assert not kinds & {"guide", "recall", "develop", "imitation", "watched", "understood"}, kinds
    finally:
        del os.environ["SYNAPSE_KNOWLEDGE"]
        import feel_bridge

        feel_bridge._RECIPES.clear()


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
