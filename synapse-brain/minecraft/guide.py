"""
The guide: the Minecraft Wiki (https://minecraft.wiki, CC BY-NC-SA 3.0), downloaded for Synapse to read, as a
person reads guides to learn the game. Plain text of:
  - the tutorials (the beginner's guide, mining, the Nether, the End, shelters, food, farming...), minus the
    ones about commands, mods, consoles, launchers and resource packs;
  - the article of every block, item and creature of the game (from knowledge/sim_rules.json).
Saved to guide/pages.jsonl (kept on this PC, not in the repository). The download is polite: one request at a
time, a pause between them, and it resumes where it stopped.

    python guide.py            # about 10-15 minutes the first time
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "guide")
API = "https://minecraft.wiki/api.php"
UA = "SynapseBrain-guide/1.0 (personal research, one request at a time)"
SKIP = re.compile(r"command|mod(s|ding)?\b|xbox|playstation|ps[345]|switch|launcher|resource pack|texture|server|realm|"
                  r"bedrock edition|education|map making|adding |custom |shader|optifine|java edition installation|"
                  r"legacy console|pocket edition|new nintendo|wii u|datapack|data pack|spawn command|world conversion|"
                  r"programs|mcedit|bug|speedrun|update", re.I)


def api(params):
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json", "maxlag": 5})
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            time.sleep(2 + attempt * 3)
            err = e
    raise RuntimeError(f"wiki API failed: {err}")


def tutorials():
    titles, cont = [], {}
    while True:
        d = api({"action": "query", "list": "allpages", "apprefix": "Tutorials/", "apnamespace": 0, "aplimit": 500, **cont})
        titles += [p["title"] for p in d["query"]["allpages"]]
        if "continue" not in d:
            break
        cont = d["continue"]
        time.sleep(0.3)
    return [t for t in titles if not SKIP.search(t)]


def game_things():
    rules = json.load(open(os.path.join(HERE, "knowledge", "sim_rules.json"), encoding="utf-8"))
    names = set(rules.get("blocks", {})) | set(rules.get("recipes", {})) | set(rules.get("entities", {}))
    return sorted({n.replace("_", " ").title().replace(" Of ", " of ").replace(" The ", " the ") for n in names})


def main():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "pages.jsonl")
    done = set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                p = json.loads(line)
                done.add(p["asked"])
                done.add(p["title"])
            except Exception:
                pass
    titles = tutorials() + game_things()
    todo = [t for t in titles if t not in done]
    print(f"{len(titles)} pages in the guide, {len(todo)} to download", flush=True)
    seen_titles = set(done)
    with open(path, "a", encoding="utf-8") as f:
        for i, t in enumerate(todo):
            try:
                d = api({"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "titles": t})
            except RuntimeError as e:
                print(e, flush=True)
                continue
            for page in d.get("query", {}).get("pages", {}).values():
                text = page.get("extract", "")
                title = page.get("title", t)
                if text and title not in seen_titles:            # colours of wool -> one "Wool" article
                    seen_titles.add(title)
                    f.write(json.dumps({"asked": t, "title": title, "text": text}, ensure_ascii=False) + "\n")
                    f.flush()
            if i % 50 == 0:
                print(f"{i}/{len(todo)} {t}", flush=True)
            time.sleep(0.3)
    n = sum(1 for _ in open(path, encoding="utf-8"))
    size = os.path.getsize(path) / 2 ** 20
    print(f"the guide: {n} articles, {size:.1f} MB -> {path}", flush=True)
    from guide_reader import build

    t = time.time()
    index = build()                                              # read it once into what the mind can use
    print(f"read: knowledge about {len(index)} things in {time.time() - t:.0f} s", flush=True)


if __name__ == "__main__":
    main()
