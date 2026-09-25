"""
The game's own path of development: the advancement tree (what a player sees with the L key), read from the
server jar - which advancement follows which, and what each asks for (things to hold, a world to enter).
Writes knowledge/progress.json: {id: {parent, title, tree, wants: [[concept, ...] any-of per criterion]}}.

    python build_progress.py [world/server/server.jar]
"""
import io
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TREES = ("story", "nether", "end", "adventure", "husbandry")


def main():
    jar = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "world", "server", "server.jar")
    z = zipfile.ZipFile(jar)
    inner = [n for n in z.namelist() if n.startswith("META-INF/versions/") and n.endswith(".jar")]
    if inner:                                                     # 1.18+: the real server is a jar inside a jar
        z = zipfile.ZipFile(io.BytesIO(z.read(inner[0])))
    names = z.namelist()

    def tag(t, kind="item", depth=0):
        path = f"data/minecraft/tags/{kind}/{t.split(':')[-1]}.json"
        if path not in names or depth > 3:
            return []
        out = []
        for v in json.loads(z.read(path)).get("values", []):
            v = v if isinstance(v, str) else v.get("id", "")
            out += tag(v[1:], kind, depth + 1) if v.startswith("#") else [v.split(":")[-1]]
        return out

    titles = {}
    old = os.path.join(HERE, "knowledge", "advancements.json")
    if os.path.exists(old):
        titles = {k: v.get("title", k) for k, v in json.load(open(old, encoding="utf-8")).items()}
    out = {}
    for n in names:
        if not n.startswith("data/minecraft/advancement/") or not n.endswith(".json"):
            continue
        aid = n[len("data/minecraft/advancement/"):-5]
        tree = aid.split("/")[0]
        if tree not in TREES:
            continue
        d = json.loads(z.read(n))
        wants = []
        for crit in d.get("criteria", {}).values():
            trig, cond = crit.get("trigger", ""), crit.get("conditions", {})
            if trig.endswith("inventory_changed"):
                for pred in cond.get("items", []):
                    items = pred.get("items", [])
                    items = [items] if isinstance(items, str) else items
                    alts = []
                    for it in items:
                        alts += tag(it[1:]) if it.startswith("#") else [it.split(":")[-1]]
                    if alts:
                        wants.append(["have:" + a for a in alts[:6]])
            elif trig.endswith("changed_dimension") and cond.get("to"):
                wants.append(["in:" + cond["to"].split(":")[-1]])
        out[aid] = {"parent": (d.get("parent") or "").split(":")[-1] or None, "tree": tree,
                    "title": titles.get(aid, aid.split("/")[-1].replace("_", " ")), "wants": wants}
    path = os.path.join(HERE, "knowledge", "progress.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(out)} advancements, {sum(1 for a in out.values() if a['wants'])} with things to get -> {path}")


if __name__ == "__main__":
    main()
