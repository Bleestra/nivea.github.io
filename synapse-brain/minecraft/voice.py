"""The bot's voice: the language brain grown by train_voice.py answers what it hears in chat."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from brain_lm import generate, make_state  # noqa: E402


class Voice:
    def __init__(self, path):
        meta = json.load(open(os.path.join(path, "meta.json")))
        self.st = make_state(meta["shrink"], meta["corpus_bytes"] + meta["room"])
        for k in self.st:
            f = os.path.join(path, k + ".npy")
            if os.path.exists(f):
                self.st[k][...] = np.load(f, mmap_mode="r")
        self.start = self.pos = meta["corpus_bytes"]
        self.end = meta["corpus_bytes"] + meta["room"] - 2000
        self.buf = self.st["buf"]
        self.qa = None
        qf = os.path.join(path, "qa.json")
        if os.path.exists(qf):  # hippocampal recall by content: find the memory the cue points to
            from sklearn.feature_extraction.text import TfidfVectorizer

            self.qa = json.load(open(qf))
            self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
            self.M = self.vec.fit_transform([q for q, _ in self.qa])

    def recall(self, text, threshold=0.42):
        if self.qa is None:
            return None
        sim = (self.M @ self.vec.transform([text]).T).toarray().ravel()
        k = int(sim.argmax())
        return self.qa[k][1] if sim[k] >= threshold else None

    def about_me(self, text, me):
        t = text.lower()
        if not me or not any(w in t for w in ("who are you", "кто ты", "your name", "как тебя", "what do you know",
                                                  "что ты знаешь", "how old", "сколько тебе", "расскажи о себе")):
            return None
        m = me.me
        last = ", ".join(d["item"].replace("_", " ") for d in m["discoveries"][-3:]) or "пока ничего"
        return (f"Я {m['name']}. Живу {m['age_steps']} шагов, знаю {len(m['known_items'])} вещей, "
                f"побывал в {len(m['places'])} местах, достижений: {len(m.get('advancements', []))}. "
                f"Последнее, что я открыл: {last}.")

    def reply(self, text, me=None, n=180):
        mine = self.about_me(text, me)
        if mine:
            return mine
        known = self.recall(text)
        if known:  # a clear memory answers; otherwise the language brain speaks freely
            return known[:250]
        if self.pos > self.end:
            self.pos = self.start
        prompt = f"\nQ: {text.strip()}\nA:".encode()
        out = generate(self.st, self.buf, self.pos, n, temp=0.5, seed=self.pos, prompt=prompt)
        self.pos += len(prompt) + n
        ans = out.decode("utf8", "replace").split("\n")[0].strip()
        return ans[:200] or None
