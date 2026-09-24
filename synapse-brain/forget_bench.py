"""
Continual learning: after English Wikipedia, both models learn a new domain (10 MB of Python
source code) and are re-tested on BOTH domains. Knowledge is measured with learning switched
off (frozen weights; working memory on, as a transformer keeps its context), 1 MB of
held-out text per domain.

    python3 forget_bench.py            # needs data/transformer.pt from transformer_baseline.py --save
"""
import copy
import glob
import json
import os
import time

import numpy as np
import torch

from brain_lm import make_state, process
from tx_model import GPT, evaluate, train_for

HERE = os.path.dirname(os.path.abspath(__file__))
torch.set_num_threads(os.cpu_count())


def code_corpus(n_bytes=11_000_000):
    files = sorted(f for f in glob.glob("/usr/lib/python3.12/**/*.py", recursive=True) if "/test" not in f)
    parts, size = [], 0
    for f in files:
        b = open(f, "rb").read()
        parts.append(b)
        size += len(b)
        if size >= n_bytes:
            break
    return np.frombuffer(b"".join(parts)[:n_bytes], np.uint8)


def main():
    wiki = np.fromfile(os.path.join(HERE, "data", "enwik8"), np.uint8)
    code = code_corpus()
    code_learn, code_test = code[:10_000_000], code[10_000_000:11_000_000]
    wiki_test = wiki[95_000_000:96_000_000]
    X = np.concatenate([wiki[:90_000_000], code_learn, wiki_test, code_test])
    A, B, C = 90_000_000, 100_000_000, 101_000_000  # region starts: code_learn, wiki_test, code_test
    res = {}

    # ---------------- SynapseBrain
    st = make_state(0, len(X))
    process(X, st, 0, A, A, A)
    park = os.path.join(HERE, "data", "_T_forget.npy")

    def brain_eval():
        """Frozen weights (working memory on); the brain is restored afterwards."""
        np.save(park, st["T"])
        small = {k: st[k].copy() for k in ("MT", "MT2", "S", "LN")}
        out = []
        for a, b in [(B, C), (C, len(X))]:
            bits, n = process(X, st, a, b, 0, a, stp=True)
            out.append(bits / n)
            st["T"][:] = np.load(park, mmap_mode="r")
            for k, v in small.items():
                st[k][:] = v
        os.remove(park)
        return tuple(out)

    res["brain_before"] = brain_eval()
    t = time.perf_counter()
    process(X, st, A, B, B, B)  # learn code, one pass
    res["brain_code_learn_seconds"] = time.perf_counter() - t
    res["brain_after"] = brain_eval()
    del st
    print(json.dumps(res), flush=True)

    # ---------------- Transformer (checkpoint trained on enwik8 by transformer_baseline.py)
    ck = torch.load(os.path.join(HERE, "data", "transformer.pt"))
    a = ck["args"]
    m = GPT(a["layers"], a["dim"], a["heads"], a["ctx"])
    m.load_state_dict(ck["state"])
    res["tx_before"] = (evaluate(m, wiki_test, a["ctx"]), evaluate(m, code_test, a["ctx"]))
    for budget in [res["brain_code_learn_seconds"], 120.0]:
        mm = copy.deepcopy(m)
        steps = train_for(mm, code_learn, budget, 1e-3, a["batch"], a["ctx"])
        res[f"tx_after_{budget:.0f}s"] = (evaluate(mm, wiki_test, a["ctx"]), evaluate(mm, code_test, a["ctx"]), steps)
    print(json.dumps(res), flush=True)
    with open(os.path.join(HERE, "data", "forget.json"), "w") as f:
        json.dump(res, f)


if __name__ == "__main__":
    main()
