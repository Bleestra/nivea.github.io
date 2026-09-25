"""
Selftest: every action of the Synapse body, done in the real game and checked.

A second player, "Tester", joins the running world (python world.py) with the same Synapse Body mod. Instead
of a brain, this script answers the body: for each of the 60 actions it prepares the scene through the
server console (RCON: give the items, put the blocks and the animals in place), does the action, and checks
what the body itself felt (did it work, and if not - why) and what changed (inventory, position, sleep...).
Everything happens on a platform in the sky far from the Synapses (x 1000, z 1000), so no one is disturbed.

    python selftest.py            # the world must be running; a small Tester window opens for a few minutes
    python selftest.py sleep fish # only these actions
"""
import json
import os
import socketserver
import sys
import threading
import time

from actions import ACTIONS, ru
from rcon import Rcon

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.join(HERE, "world")
NAME, PORT = "Tester", 5600
CX, CY, CZ = 1000, 100, 1000                      # the arena: feet at y=100 on a stone floor
DIRS = [(0, -1), (1, 0), (0, 1), (-1, 0)]         # N E S W, as the body's heading


def front(m, k, dy=0):
    fx, fz = DIRS[int(m.get("heading", 0)) % 4]
    return CX + fx * k, CY + dy, CZ + fz * k


def gained(before, after):
    b, a = before.get("items", {}), after.get("items", {})
    return [k for k, v in a.items() if v > b.get(k, 0)]


# ---------------------------------------------------------------- the tests: prepare, (pre-actions), check
def T(**kw):
    return kw


TESTS = {
    "dig_front": T(setup=lambda m: [f"setblock {x} {y} {z} dirt" for x, y, z in (front(m, 1), front(m, 1, 1))]),
    "craft_new": T(give=["oak_log 4"], check=lambda b, a: (bool(gained(b, a)), f"new: {gained(b, a)}")),
    "eat": T(give=["bread 4"], setup=lambda m: ["effect give Tester minecraft:hunger 4 255"], wait=5,
             check=lambda b, a: (bool((a.get("fev") or {}).get("ate")), f"ate {(a.get('fev') or {}).get('ate')}")),
    "attack": T(setup=lambda m: ["summon pig {} {} {} {{NoAI:1b}}".format(*front(m, 2))], wait=3),
    "attack_chosen": T(action="attack", target="zombie", wait=3,     # the brain chose whom: go at it, strike when ready
                       setup=lambda m: ["summon husk {} {} {} {{NoAI:1b}}".format(*front(m, 6))]),
    "use_item": T(give=["snowball 8"], pre=["hotbar_1"]),
    "dig_down": T(),
    "equip_armor": T(give=["iron_chestplate 1", "iron_helmet 1"],
                     check=lambda b, a: ("worn:iron_chestplate" in a.get("items", {}), "wearing iron")),
    "equip_weapon": T(pre=["hotbar_9"], give=["stone_sword 1"],
                      check=lambda b, a: (a.get("held", "").endswith("_sword"), f"held {a.get('held')}")),
    "equip_tool": T(pre=["hotbar_9"], give=["wooden_pickaxe 1"],
                    setup=lambda m: [f"setblock {x} {y} {z} stone" for x, y, z in (front(m, 1), front(m, 1, 1))],
                    check=lambda b, a: (a.get("held", "").endswith("_pickaxe"), f"held {a.get('held')}")),
    "place_block": T(give=["cobblestone 8"]),
    "craft_gear": T(give=["oak_planks 8", "stick 4", "crafting_table 1"], check=lambda b, a: (bool(gained(b, a)), f"made {gained(b, a)}")),
    "smelt": T(give=["furnace 1", "raw_iron 3", "coal 3"]),
    "sleep": T(give=["red_bed 1"], setup=lambda m: ["time set 18000"], then="sleep_in_bed"),
    "sleep_in_bed": T(action="sleep", keep=True, check=lambda b, a: (bool(a.get("sleeping")), "sleeping" if a.get("sleeping") else "awake")),
    "drop_junk": T(target="dirt", give=["dirt 8"]),
    "pillar_up": T(give=["cobblestone 8"], check=lambda b, a: ((a.get("pos") or [0, 0])[1] - (b.get("pos") or [0, 0])[1] >= 0.9, "rose")),
    "dig_up": T(setup=lambda m: ["setblock {} {} {} dirt".format(*front(m, 0, 2))]),
    "fish": T(give=["fishing_rod 1"], wait=2,
              setup=lambda m: ["fill {} 99 {} {} 99 {} water".format(*_rect(m, 2, 12))]),
    "interact": T(give=["cod 8"], setup=lambda m: ["summon cat {} {} {} {{NoAI:1b}}".format(*front(m, 2))], wait=3),
    "store": T(target="cobblestone", give=["cobblestone 16"], setup=lambda m: ["setblock {} {} {} chest".format(*front(m, 2))],
               check=lambda b, a: ("cobblestone" not in a.get("items", {}) and "cobblestone" in
                                   (((a.get("fev") or {}).get("chest") or {}).get("items") or {}), "put away, chest remembered"),
               then="take"),
    "take": T(target="cobblestone", keep=True, check=lambda b, a: ("cobblestone" in a.get("items", {}), "took it back")),
    "place_chest": T(give=["chest 1"]),
    "trade": T(give=["emerald 64"], setup=lambda m: ["summon wandering_trader {} {} {} {{NoAI:1b}}".format(*front(m, 2))], wait=3,
               check=lambda b, a: (bool((a.get("fev") or {}).get("traded")), f"traded {(a.get('fev') or {}).get('traded')}")),
    "read": T(give=["written_book[written_book_content={title:\"Kniga\",author:\"Tester\",pages:['\"чтобы получить алмаз, нужна железная кирка\"']}] 1"],
              check=lambda b, a: (bool((a.get("fev") or {}).get("read")), "read")),
    "approach": T(target="oak_log", setup=lambda m: ["setblock {} {} {} oak_log".format(*front(m, 6))]),
    "mine_target": T(target="oak_log", setup=lambda m: ["setblock {} {} {} oak_log".format(*front(m, 3))],
                     check=lambda b, a: ("oak_log" in gained(b, a), f"got {gained(b, a)}")),
    "craft_target": T(target="wooden_shovel", give=["oak_planks 4", "stick 2", "crafting_table 1"],
                      check=lambda b, a: ("wooden_shovel" in a.get("items", {}), "shovel")),
    "goto_place": T(target=lambda m: list(front(m, 6))),
    "explore": T(),
    "place_frame": T(give=["obsidian 10", "cobblestone 8"]),
    "walk": T(),
    "hit": T(setup=lambda m: ["setblock {} {} {} dirt".format(*front(m, 1, 1))]),
    "use": T(give=["cobblestone 8"], pre=["hotbar_1", "look_down_fine", "look_down_fine"]),
    "hold_use": T(give=["bread 4"], pre=["hotbar_1"], setup=lambda m: ["effect give Tester minecraft:hunger 4 255"], wait=5),
    "swap_hands": T(give=["torch 4"], pre=["hotbar_1"]),
    "drop_item": T(give=["dirt 4"], pre=["hotbar_1"]),
}
TESTS.update({                                     # a toggle is tested on and back off, so later tests start plain
    "toggle_sprint": T(then="toggle_sprint_off"), "toggle_sprint_off": T(action="toggle_sprint", keep=True),
    "toggle_sneak": T(then="toggle_sneak_off"), "toggle_sneak_off": T(action="toggle_sneak", keep=True)})
ORDER = [a for a in ACTIONS if a != "explore"] + ["explore"]          # explore walks far: last
if len(sys.argv) > 1:                             # python selftest.py forward sleep ...: only these
    ORDER = [a for a in sys.argv[1:] if a in TESTS or a in ACTIONS]


def _rect(m, a, b):
    """A pool from a to b blocks ahead, 3 wide, as x1 z1 x2 z2."""
    (x1, _, z1), (x2, _, z2) = front(m, a), front(m, b)
    fx, fz = DIRS[int(m.get("heading", 0)) % 4]
    return (min(x1, x2) - abs(fz), min(z1, z2) - abs(fx), max(x1, x2) + abs(fz), max(z1, z2) + abs(fx))


class Runner:
    def __init__(self, rc):
        self.rc, self.results = rc, []
        self.plan = []              # the queue of steps
        for name in ORDER:
            self._queue(name)
        self.pending = None         # (test name, observation before)

    def _queue(self, name):
        t = TESTS.get(name, T())
        if not t.get("keep"):
            self.plan.append(("reset", name))
        self.plan.append(("setup", name))
        self.plan += [("act", a, None, None) for a in t.get("pre", [])]
        self.plan.append(("do", name))
        if t.get("then"):
            self._queue(t["then"])

    def reset(self):
        rc = self.rc
        for cmd in ["clear Tester", "effect clear Tester", "time set day", "weather clear",
                    f"kill @e[type=!player,x={CX},y={CY},z={CZ},distance=..40]",
                    f"fill {CX - 12} {CY} {CZ - 12} {CX + 12} {CY + 5} {CZ + 12} air",
                    f"fill {CX - 12} {CY - 1} {CZ - 12} {CX + 12} {CY - 1} {CZ + 12} stone",
                    f"tp Tester {CX + 0.5} {CY} {CZ + 0.5} 180 0"]:
            rc(cmd)

    def step(self, m):
        """-> the reply to the body for this moment."""
        if self.pending:
            name, before = self.pending
            self.pending = None
            t = TESTS.get(name, T())
            act = m.get("act") or {}
            ok, detail = bool(act.get("ok", False)), act.get("why", "")
            if "check" in t:
                good, note = t["check"](before, m)
                ok, detail = ok and good, (detail + " " if detail else "") + note
            self.results.append({"action": name, "ok": ok, "detail": detail})
            print(f"  {'OK ' if ok else 'НЕТ'} {name:15} {ru(ACTIONS.index(t.get('action', name))) if t.get('action', name) in ACTIONS else ''} {detail}", flush=True)
        while self.plan:
            kind = self.plan[0][0]
            if kind == "reset":
                self.plan.pop(0)
                self.reset()
                # face north as the teleport did: the body's own heading must agree
                turns = (4 - int(m.get("heading", 0))) % 4
                pitch = int(m.get("pitch", 0))
                acts = ["turn_right"] * turns + (["look_down"] * -pitch if pitch < 0 else ["look_up"] * pitch)
                self.plan[0:0] = [("act", a, None, None) for a in acts] + [("wait", 2)]
                return {"action": 4}
            if kind == "setup":
                _, name = self.plan.pop(0)
                t = TESTS.get(name, T())
                for g in t.get("give", []):
                    self.rc(f"give Tester {g}")
                for cmd in (t["setup"](m) if "setup" in t else []):
                    self.rc(cmd)
                self.plan.insert(0, ("wait", t.get("wait", 2)))
                continue
            if kind == "wait":
                n = self.plan[0][1]
                if n <= 1:
                    self.plan.pop(0)
                else:
                    self.plan[0] = ("wait", n - 1)
                return {"action": ACTIONS.index("wait")}
            if kind == "act":
                a = self.plan.pop(0)[1]
                return {"action": ACTIONS.index(a)}
            if kind == "do":
                _, name = self.plan.pop(0)
                t = TESTS.get(name, T())
                action = t.get("action", name)
                target = t.get("target")
                if callable(target):
                    target = target(m)
                self.pending = (name, m)
                reply = {"action": ACTIONS.index(action)}
                if target is not None:
                    reply["target"] = target
                return reply
        return None


def main():
    pw = open(os.path.join(WORLD, "server", "rcon.txt")).read().strip()
    rc = Rcon(pw)
    print("server:", rc("list"), flush=True)
    for y in range(CY - 5, CY):                                  # a stone platform in the sky
        rc(f"fill {CX - 25} {y} {CZ - 25} {CX + 25} {y} {CZ + 25} stone")
    rc(f"fill {CX - 25} {CY} {CZ - 25} {CX + 25} {CY + 6} {CZ + 25} air")
    runner, done = Runner(rc), threading.Event()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            print("the Tester's body is here - testing", len(ORDER), "actions", flush=True)
            rc(f"gamemode survival {NAME}")
            runner.reset()
            for line in self.rfile:
                reply = runner.step(json.loads(line))
                if reply is None:
                    done.set()
                    return
                self.wfile.write((json.dumps(reply) + "\n").encode())

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    import native_client

    cfg = json.load(open(os.path.join(WORLD, "world.json"), encoding="utf-8"))
    client = native_client.launch(NAME, "127.0.0.1", cfg["server"].get("port", 25565), PORT, eyes=False, resolution="480x270",
                                  game=native_client.game_dir(NAME), background=True)
    ok = done.wait(timeout=1800)
    client.terminate()
    native_client.close(native_client.game_dir(NAME))               # the game itself runs as the launcher's child
    res = runner.results
    passed = sum(r["ok"] for r in res)
    print(f"\n{passed} of {len(res)} actions work" + ("" if ok else " (the test did not finish in time)"), flush=True)
    with open(os.path.join(WORLD, "selftest.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    rc.close()


if __name__ == "__main__":
    main()
