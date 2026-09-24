"""
Grow the bot's voice: a SynapseBrain language brain that reads everything about Minecraft.

  - the Minecraft Wiki (45k article sections, Hugging Face: KoalaBrainResearcher/Minecraft-Wiki-2023)
  - 88k wiki questions & answers (Hugging Face: lparkourer10/minecraft-wiki)
  - the bot's own reference book: every recipe and advancement of the game (knowledge/), also turned
    into exact question -> answer pairs, so crafting questions get factual answers
One pass, no GPU. Saves voice/ (about 1 GB with the default --shrink 3).

    python3 train_voice.py [--shrink 3] [--out voice]
"""
import argparse
import json
import os
import random
import sys
import time
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from brain_lm import make_state, process  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--shrink", type=int, default=3, help="memory = 6.7 GB / 2^shrink")
p.add_argument("--out", default=os.path.join(HERE, "voice"))
args = p.parse_args()
cache = os.path.join(HERE, "..", "data", "mc")
os.makedirs(cache, exist_ok=True)
HF = "https://huggingface.co/datasets/"
for name, url in [("wiki2023.jsonl", HF + "KoalaBrainResearcher/Minecraft-Wiki-2023/resolve/main/articles.jsonl"),
                  ("wiki_lp.json", HF + "lparkourer10/minecraft-wiki/resolve/main/dataset.json")]:
    f = os.path.join(cache, name)
    if not os.path.exists(f):
        print("downloading", url, flush=True)
        urllib.request.urlretrieve(url, f)

docs = []
for line in open(os.path.join(cache, "wiki2023.jsonl")):
    a = json.loads(line)
    head = a["title"] if "section" not in a else f"{a['title']} - {a['section']}"
    docs.append(f"== {head} ==\n{a['text'].strip()}\n")
for x in json.load(open(os.path.join(cache, "wiki_lp.json"))):
    docs.append(f"Q: {x['question'].strip()}\nA: {x['answer'].strip()}\n")
K = os.path.join(HERE, "knowledge")
recipes = json.load(open(os.path.join(K, "recipes.json")))
advs = json.load(open(os.path.join(K, "advancements.json")))
book = []
for name, rs in recipes.items():
    r = rs[0]
    nice = name.replace("_", " ")
    ing = ", ".join(f"{v} {k}" for k, v in r["ingredients"].items())
    where = " at a crafting table" if r.get("needs_table") else " in your inventory grid"
    book.append(f"Q: How do you craft {nice}?\nA: Craft {nice}{where} from {ing}; it makes {r['makes']}.\n")
    book.append(f"Q: What do I need to make {nice}?\nA: {ing}.\n")
for aid, a in advs.items():
    book.append(f"Q: How do I get the advancement {a['title']}?\nA: {a['description']}.\n")
    book.append(f"Q: What is {a['title']}?\nA: An advancement: {a['description']}.\n")
docs += book * 3  # the reference book is read three times - it is the bot's own manual
qa_memory = [d.split("\nA: ", 1) for d in book] + [[f"Q: {x['question'].strip()}", x["answer"].strip()]
                                                   for x in json.load(open(os.path.join(cache, "wiki_lp.json")))]
random.seed(0)
random.shuffle(docs)
text = "\n".join(docs).encode()
print(f"corpus: {len(text) / 1e6:.1f} MB ({len(book)} reference Q&A pairs)", flush=True)

data = np.frombuffer(text, np.uint8)
room = 4_000_000  # space for conversations
st = make_state(args.shrink, len(data) + room)
t = time.time()
process(np.concatenate([data, np.zeros(16, np.uint8)]), st, 0, len(data), len(data), len(data))
print(f"read in {time.time() - t:.0f} s", flush=True)
os.makedirs(args.out, exist_ok=True)
for k, v in st.items():
    np.save(os.path.join(args.out, k + ".npy"), v)
with open(os.path.join(args.out, "qa.json"), "w") as f:  # episodic memory of questions and answers
    json.dump([[q[3:].strip(), a.strip()] for q, a in qa_memory], f)
with open(os.path.join(args.out, "meta.json"), "w") as f:
    json.dump({"shrink": args.shrink, "corpus_bytes": len(data), "room": room}, f)
print("saved", args.out)
