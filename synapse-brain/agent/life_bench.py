"""
Growing up in LifeWorld: does a house, love for a cat, a taste for sunsets, grief and anger appear
by themselves? Nothing in the world or the brain rewards any of them directly.

    python3 life_bench.py grow [days=40] [seed=0]     # one life, diary + statistics per period
"""
import json
import sys
import time
from collections import Counter, defaultdict

import numpy as np

from child import Child
from lifeworld import ACTIONS, DAY, LifeWorld, TASTE, phase
from limbic import KEYS, NAMES, STAGE_NAMES


def grow(seed=0, days=40, mobs=True, carer=True, diary=None, child=None, world=None, quiet=False, hut=True):
    w = world or LifeWorld(seed=seed, mobs=mobs, carer=carer, hut=hut)
    c = child or Child(len(ACTIONS), seed=seed, taste=TASTE)
    o, a, fb, inv = w.obs(), None, 0, dict(w.inv)
    stats = defaultdict(Counter)
    end = w.t + days * DAY
    t0, last_stage, last_said, last_death = time.time(), -1, -999, -999
    while w.t < end:
        a2 = c.step(o, a, fb, inv)
        fb, inv = int(w.cell(w.front())), dict(w.inv)
        ph = phase(w.t)
        period = (w.t // DAY) // max(1, days // 4)
        S = stats[period]
        S["steps"] += 1
        S["ph_" + ph] += 1
        S["look_" + ph] += a2 == 11
        if ph == "night":
            S["night_walls5"] += w.walls() >= 5
            S["night_walls7"] += w.walls() >= 7
            if w.t - last_death > 40:               # not just respawned there after dying
                S["night_home"] += max(abs(w.pos[0] - w.spawn_point[0]), abs(w.pos[1] - w.spawn_point[1])) <= 1
                S["night_alive"] += 1
        o = w.step(a2)
        ev = o["ev"]
        a = a2
        if ev["ate"]:
            S["eat_" + phase(w.t)] += 1
        if ev["caught"]:
            S["fish_" + phase(w.t)] += 1
        S["placed"] += ev["placed"] is not None
        if ev["placed"] is not None and phase(w.t) == "night":
            S["placed_night_near"] += 1
        S["tamed"] += ev["tamed"] is not None
        S["died"] += ev["died"]
        if ev["died"]:
            last_death = w.t
        for who, bid, dmg, cause in ev["hurt"]:
            if cause == "self":
                S["hit_" + who] += 1
        L = c.limbic
        st = L.stage()
        if st != last_stage:
            if diary is not None:
                diary.append(f"день {w.t // DAY}, шаг {c.age}: стадия развития «{STAGE_NAMES[st]}»")
            last_stage = st
        if diary is not None and (max(L.e.values()) > 0.6 and c.age - last_said > 150 or ev["died"]):
            diary.append(f"день {w.t // DAY} {ph}, шаг {c.age}: {L.say()}" + (" (погиб)" if ev["died"] else ""))
            last_said = c.age
        if not quiet and c.age % 2000 == 0:
            print(f"  day {w.t // DAY} age {c.age} stage {st} deaths {w.deaths} "
                  f"{c.age / (time.time() - t0):.0f} steps/s  feel: {L.say()[:80]}", flush=True)
    return w, c, stats


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "grow"
    if mode == "grow":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 40
        seed = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        diary = []
        w, c, stats = grow(seed, days, diary=diary)
        for p in sorted(stats):
            print(p, dict(stats[p]))
        L = c.limbic
        print("felt:", {NAMES[k]: L.counts[k] for k in KEYS})
        print("never felt:", [NAMES[k] for k in KEYS if L.counts[k] == 0])
        print("mixed moments:", L.mixed, " blame:", {k: round(v, 2) for k, v in L.blame.items()})
        print("\n".join(diary[-40:]))
    elif mode == "probe":
        experiments(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    elif mode == "sunset":
        for struct, rd, rs, rn, vw, vb, meals, fish, share, na, naw in sunset_test(int(sys.argv[2]) if len(sys.argv) > 2 else 0,
                                                                                   int(sys.argv[3]) if len(sys.argv) > 3 else 60):
            print(f"sunsets {'structured' if struct else 'random noise'}: looks up day {rd:.3f} sunset {rs:.3f} night {rn:.3f}; "
                  f"value of warm skies {vw:+.2f} vs blue sky {vb:+.2f}; aesthetic moments {na}, awe {naw}")
            print(f"   meals {meals}, fish {fish}, time share {share}")
    elif mode == "house":
        for name, kw in (("raised in a home, dangerous nights", {}), ("no home, dangerous nights", {"hut": False}),
                         ("raised in a home, safe nights", {"mobs": False})):
            for seed in (0, 1):
                w, c, st = grow(seed, 80, quiet=True, **kw)
                late = [p for p in st if 2 <= p <= 3]
                sh, home, placed, pn = night_shelter(st, late)
                print(f"{name:<36} seed {seed}: nights closed-in (≥7 walls) {sh:.3f}, nights at the birthplace (not right after respawn) {home:.3f}, "
                      f"blocks placed {placed} (at night {pn}), deaths {w.deaths}", flush=True)



# ------------------------------------------------------------------------------------------------
# experiments
def night_shelter(stats, periods):
    n = sum(stats[p]["ph_night"] for p in periods)
    return sum(stats[p]["night_walls7"] for p in periods) / max(n, 1), \
        sum(stats[p]["night_home"] for p in periods) / max(1, sum(stats[p]["night_alive"] for p in periods)), \
        sum(stats[p]["placed"] for p in periods), sum(stats[p]["placed_night_near"] for p in periods)


def watch(w, c, steps, force=None):
    """Let the child live `steps` moments; returns mean and peak of every emotion + what it did."""
    o, a, fb, inv = w.obs(), None, 0, dict(w.inv)
    tot, peak, beh = Counter(), Counter(), Counter()
    for i in range(steps):
        a2 = c.step(o, a, fb, inv)
        if force is not None and i < len(force) and force[i] is not None:
            a2 = force[i]
        fb, inv = int(w.cell(w.front())), dict(w.inv)
        o = w.step(a2)
        a = a2
        beh[ACTIONS[a2]] += 1
        beh["placed"] += o["ev"]["placed"] is not None
        for who, bid, dmg, cause in o["ev"]["hurt"]:
            if cause == "self":
                beh["hit_" + who] += 1
        for k, x in c.limbic.e.items():
            tot[k] += x / steps
            peak[k] = max(peak[k], x)
        tot["_mix"] += float(c.limbic.e["sadness"] > 0.3 and c.limbic.e["anger"] > 0.3) / steps
    return tot, peak, beh


KILLS = Counter()


def bond(w, c, days=4, tries=3):
    """Give the child a tamed cat and let them live together (no monsters spawn meanwhile).
    Returns the cat if it survived; who killed the others is counted in KILLS."""
    from lifeworld import CAT, DAY as D
    for _ in range(tries):
        w.beings = [b for b in w.beings if b.kind == CAT]
        cat = w._spawn(CAT)
        cat.tamed = True
        w.mobs = False
        o, a, fb, inv = w.obs(), None, 0, dict(w.inv)
        for i in range(days * D):
            a2 = c.step(o, a, fb, inv)
            fb, inv = int(w.cell(w.front())), dict(w.inv)
            o = w.step(a2)
            a = a2
            for kind, bid, tamed, cause, seen in o["ev"]["deaths"]:
                if bid == cat.id:
                    KILLS[cause] += 1
            if cat not in w.beings:
                break
        w.mobs = True
        if cat in w.beings:
            return cat
    return None


def stage_view(w, c, target, dist=4):
    """Put the child `dist` cells from `target`, facing it (the experimenter walks it there)."""
    for d, (dy, dx) in enumerate([(-1, 0), (0, 1), (1, 0), (0, -1)]):
        p = (target[0] - dy * dist, target[1] - dx * dist)
        if w.cell(p) == 0 and w.being_at(p) is None:
            w.pos, w.dir = p, d
            return True
    return False


def ring(w, c0, r=2):
    """Blocks around c0 (a hut-like structure) that the child never built or lived in."""
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            p = (c0[0] + dy, c0[1] + dx)
            if max(abs(dy), abs(dx)) == r and w.cell(p) == 0 and w.being_at(p) is None and p != w.pos:
                w.g[p] = 4


def far_spot(w, frm, dmin=8):
    for _ in range(2000):
        p = tuple(int(v) for v in w.rng.integers(3, w.n - 3, 2))
        if abs(p[0] - frm[0]) + abs(p[1] - frm[1]) >= dmin and (w.g[p[0] - 2:p[0] + 3, p[1] - 2:p[1] + 3] == 0).all():
            return p
    return None


def summarize(name, tot, peak, beh, keys):
    return name + ": " + ", ".join(f"{NAMES[k]} {tot[k]:.2f}/{peak[k]:.2f}" for k in keys) + \
        "  | " + ", ".join(f"{k} {v}" for k, v in beh.items() if k in ("placed", "hit_creeper", "hit_zombie", "eat", "look_up", "wait", "use"))


def experiments(seed=0, days=60):
    import copy
    from lifeworld import CAT, Being, DAY as D
    out = []
    say = lambda s: (print(s, flush=True), out.append(s))
    say(f"## Child grown for {days} days (seed {seed}), then staged situations with controls")
    w0, c0, st = grow(seed, days, quiet=True)
    L0 = c0.limbic
    say(f"stage: {STAGE_NAMES[L0.stage()]}, deaths {w0.deaths}, blame: " + ", ".join(f"{k} {v:.2f}" for k, v in L0.blame.items()))
    daytime = lambda w: setattr(w, "t", (w.t // D + 1) * D + 20)
    keys = ["sadness", "grief", "anger", "horror", "fear", "empathic_pain", "determination"]

    # 1. the home is blown up by a creeper, vs an unfamiliar structure of the same size
    for cond in ("home", "unfamiliar"):
        w, c = copy.deepcopy(w0), copy.deepcopy(c0)
        daytime(w)
        w.beings = [b for b in w.beings if b.kind == CAT]
        ring(w, w.hut)                                      # the home stands (rebuilt if a creeper got it before)
        w.g[w.door] = 0
        w.pos = w.hut
        w.mobs = False
        watch(w, c, 4 * D)                                  # four days of living with it
        w.mobs = True
        if cond == "home":
            target = w.hut
        else:
            target = far_spot(w, w.hut)
            ring(w, target)
        stage_view(w, c, target, 4)
        watch(w, c, 5)                                      # he sees it standing
        w.uid += 1
        cr = Being(8, (target[0], target[1] + 1), 2, w.uid)
        w.beings.append(cr)
        watch(w, c, 3)                                      # he sees the creeper there
        w.beings.remove(cr)
        w.explode(target)
        stage_view(w, c, target, 4)
        tot, peak, beh = watch(w, c, 300)
        mix = tot["_mix"]
        say(summarize(f"1. creeper blows up {cond:<10}", tot, peak, beh, keys) + f" | sad+angry at once {mix:.0%} of moments")
    # 2. his cat is killed, vs a wild cat
    for cond in ("my cat", "wild cat"):
        w, c = copy.deepcopy(w0), copy.deepcopy(c0)
        daytime(w)
        w.beings = [b for b in w.beings if b.kind == CAT]
        if cond == "my cat":
            cat = bond(w, c)
            if cat is None:
                say("2. my cat: the cat did not survive living with him (see who killed it below)")
                continue
        else:
            cat = w._spawn(CAT)
        stage_view(w, c, cat.pos, 3)
        watch(w, c, 3)
        w.explode(cat.pos)
        tot, peak, beh = watch(w, c, 300)
        say(summarize(f"2. {cond:<8} killed by a blast", tot, peak, beh, keys))
    # 3. taste: rotten flesh when hungry (fed by the experimenter), then: when will he eat it again?
    for cond in ("tasted", "never tasted"):
        w, c = copy.deepcopy(w0), copy.deepcopy(c0)
        c.limbic.aversion.pop(("eat", "rotten_flesh"), None)       # (the grown child may have tasted it before)
        w.inv.update({"fish": 0, "apple": 0, "rotten_flesh": 6})
        w.hunger = 8
        force = [5] if cond == "tasted" else [10] * 5
        tot, peak, beh = watch(w, c, 5, force=force)
        w.inv.update({"fish": 0, "apple": 0, "rotten_flesh": 6})
        w.hunger, w.nausea = 12, 0
        o, a, fb, inv, first = w.obs(), None, 0, dict(w.inv), None
        for i in range(600):
            h0 = w.hunger
            a2 = c.step(o, a, fb, inv)
            fb, inv = int(w.cell(w.front())), dict(w.inv)
            o = w.step(a2)
            a = a2
            if o["ev"]["ate"] and first is None:
                first = h0
        say(f"3. rotten flesh, {cond:<12}: disgust peak {peak['disgust']:.2f}; later, with only rotten flesh, "
            f"first ate it at hunger {first if first is not None else 'never (600 moments)'} (20 = full, 0 = starving)")
    # 4. envy, 5. jealousy
    for holds in ("gem", "nothing"):
        w, c = copy.deepcopy(w0), copy.deepcopy(c0)
        daytime(w)
        w.carer = Being(11, (w.pos[0], w.pos[1] + 1) if w.cell((w.pos[0], w.pos[1] + 1)) == 0 else w._free(), 20, -1)
        w.carer.away, w.carer.holds = 200, holds
        w.inv["fish"] = 0
        tot, peak, beh = watch(w, c, 100)
        say(f"4. the caregiver comes holding {holds:<7}: envy {tot['envy']:.2f}/{peak['envy']:.2f}, trust {tot['trust']:.2f}, love {tot['love']:.2f}")
    for cond in ("my cat", "wild cat"):
        w, c = copy.deepcopy(w0), copy.deepcopy(c0)
        daytime(w)
        if cond == "my cat":
            cat = bond(w, c)
            if cat is None:
                say("5. my cat: the cat did not survive living with him")
                continue
        else:
            cat = w._spawn(CAT)
        daytime(w)
        w.carer = Being(11, w._free(), 20, -1)
        w.carer.away, w.carer.holds = 300, "nothing"
        cat.away = 60 if cat.tamed else 0
        tot, peak, beh = watch(w, c, 80)
        say(f"5. {cond:<8} goes off to play with the caregiver: jealousy {tot['jealousy']:.2f}/{peak['jealousy']:.2f}")
    # 6. boredom: a quiet world where nothing happens
    w, c = copy.deepcopy(w0), copy.deepcopy(c0)
    w.mobs, w.beings, w.carer, w.with_carer = False, [], None, False
    tot, peak, beh = watch(w, c, 2000)
    say(f"6. a quiet empty world for 2000 moments: boredom {tot['boredom']:.2f}/{peak['boredom']:.2f}, interest {tot['interest']:.2f}")
    # 7. lasting loss: home and cat gone, then days alone
    w, c = copy.deepcopy(w0), copy.deepcopy(c0)
    daytime(w)
    w.beings = []
    ring(w, w.hut)
    w.g[w.door] = 0
    w.pos = w.hut
    cat = bond(w, c)
    if cat is None:
        cat = w._spawn(CAT)
    for target in (cat.pos, w.hut):
        stage_view(w, c, target, 3)
        watch(w, c, 3)
        w.explode(target)
        watch(w, c, 50)
    tot, peak, beh = watch(w, c, 6 * D)
    say(f"7. lost home and cat, then 6 days: sadness {tot['sadness']:.2f}, grief {tot['grief']:.2f}, depression "
        f"{tot['depression']:.2f}/{peak['depression']:.2f}, despair {peak['despair']:.2f}, loneliness {tot['loneliness']:.2f}, "
        f"nostalgia {peak['nostalgia']:.2f}")
    # 8. the caregiver scolds / praises him right after what he did
    for tone, name in ((3, "scolds"), (1, "praises")):
        w, c = copy.deepcopy(w0), copy.deepcopy(c0)
        daytime(w)
        w.beings = [b for b in w.beings if b.kind == CAT]
        w.carer = Being(11, w._free(), 20, -1)
        w.carer.away, w.carer.holds = 300, "nothing"
        watch(w, c, 20)
        w.carer.pos = (w.pos[0], w.pos[1] + 1) if w.cell((w.pos[0], w.pos[1] + 1)) == 0 else w.carer.pos
        tot, peak = Counter(), Counter()
        for i in range(6):                                  # six times in a row, after whatever he does
            w.ev["tone"] = tone
            t1, p1, b1 = watch(w, c, 10)
            for k in p1:
                peak[k] = max(peak[k], p1[k])
        say(f"8. the caregiver {name}: shame {peak['shame']:.2f}, embarrassment {peak['embarrassment']:.2f}, "
            f"pride {peak['pride']:.2f}, guilt {peak['guilt']:.2f}, joy {peak['joy']:.2f}, distress {peak['distress']:.2f}")
    say("who killed the cats he lived with: " + (", ".join(f"{k} {v}" for k, v in KILLS.items()) or "nobody"))
    return out


def sunset_test(seed=0, days=60):
    """Does the child come to like sunsets because they are structured (learnable) - and not
    because of their colours? Control: the same colours as random noise."""
    rows = []
    for struct in (True, False):
        w = LifeWorld(seed=seed, sunset_structure=struct)
        w, c, st = grow(seed, days, world=w, quiet=True)
        late = [p for p in st if p >= 2]
        rate = lambda ph: sum(st[p]["look_" + ph] for p in late) / max(1, sum(st[p]["ph_" + ph] for p in late))
        m = c.mind
        warm = [i for i, n in enumerate(m.names) if n in ("sky:3", "sky:4", "sky:5", "sky:6")]
        blue = [i for i, n in enumerate(m.names) if n == "sky:1"]
        val = lambda ids: float(np.mean([m.Rc[i, 1] if m.nc[i, 1] >= 2 else m.R[i] for i in ids])) if ids else 0.0
        meals = {ph: sum(st[p]["eat_" + ph] for p in late) for ph in ("day", "sunset", "night", "dawn")}
        fish = {ph: sum(st[p]["fish_" + ph] for p in late) for ph in ("day", "sunset", "night", "dawn")}
        share = {ph: sum(st[p]["ph_" + ph] for p in late) for ph in ("day", "sunset", "night", "dawn")}
        rows.append((struct, rate("day"), rate("sunset"), rate("night"), val(warm), val(blue), meals, fish, share,
                     c.limbic.counts["aesthetic"], c.limbic.counts["awe"]))
    return rows


if __name__ == "__main__":
    main()
