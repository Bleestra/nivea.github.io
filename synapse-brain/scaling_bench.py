"""
How quality grows with data: both models learn from the first 1, 3, 10, 30, 90 MB of enwik8
and are tested on the same held-out 1 MB (enwik8 bytes 95M..96M).

  SynapseBrain : one pass over the data (its natural and only mode of training).
  Transformer  : 2 layers x 256, context 128 (the best short-budget config), dropout 0.1, AdamW +
                 cosine, 4 cores + AMX bf16, a generous budget per size (480-1200 s, always far
                 more than the brain's time),
                 validation (300 kB) every 30 s and the best checkpoint kept (early stopping),
                 so it may do many epochs over small data and cannot win or lose by overfitting.
"""
import copy
import json
import math
import os
import time

import numpy as np
import torch
import torch.nn.functional as F

from brain_lm import make_state, process
from tx_model import GPT, evaluate

HERE = os.path.dirname(os.path.abspath(__file__))
torch.set_num_threads(os.cpu_count())
SIZES_MB = [1, 3, 10, 30, 90]
TX_BUDGET = {1: 480, 3: 600, 10: 720, 30: 900, 90: 1200}


def brain(data, test, size):
    X = np.concatenate([data[:size], test])
    st = make_state(0, len(X))
    t = time.perf_counter()
    process(X, st, 0, size, size, size)
    tt = time.perf_counter() - t
    park = os.path.join(HERE, "data", "_T_scaling.npy")
    np.save(park, st["T"])
    small = {k: st[k].copy() for k in ("MT", "MT2", "S", "LN")}
    b, n = process(X, st, size, len(X), 0, size, stp=True)
    wm = b / n
    st["T"][:] = np.load(park, mmap_mode="r")
    for k, v in small.items():
        st[k][:] = v
    os.remove(park)
    b, n = process(X, st, size, len(X), len(X), size)
    return dict(train_s=tt, frozen_wm=wm, continual=b / n)


def transformer(data, val, test, size, budget, seed=0):
    torch.manual_seed(seed)
    L, d, h, ctx, bs, lr0 = 2, 256, 4, 128, 32, 4e-3
    m = GPT(L, d, h, ctx, dropout=0.1)
    opt = torch.optim.AdamW(m.parameters(), lr=lr0, betas=(0.9, 0.95), weight_decay=0.1)
    tr = torch.from_numpy(data[:size].astype(np.int64))
    rng = np.random.default_rng(seed)
    best, best_state, best_t, next_eval = 1e9, None, 0.0, 30.0
    t0, step = time.time(), 0
    while True:
        el = time.time() - t0
        if el >= next_eval or el >= budget:
            v = evaluate(m, val, ctx)
            if v < best:
                best, best_state, best_t = v, copy.deepcopy(m.state_dict()), el
            m.train()
            next_eval += 30.0
            if el >= budget:
                break
        lr = lr0 * min(1.0, (step + 1) / 100) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(el / budget, 1))))
        for g in opt.param_groups:
            g["lr"] = lr
        ix = rng.integers(0, size - ctx - 1, bs)
        xb = torch.stack([tr[i : i + ctx + 1] for i in ix])
        with torch.autocast("cpu", dtype=torch.bfloat16):
            logits = m(xb[:, :-1])
        loss = F.cross_entropy(logits.float().reshape(-1, 256), xb[:, 1:].reshape(-1))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
        opt.step()
        step += 1
    m.load_state_dict(best_state)
    return dict(budget_s=budget, best_at_s=best_t, epochs=step * bs * ctx / size, val=best,
                test=evaluate(m, test, ctx))


def main():
    data = np.fromfile(os.path.join(HERE, "data", "enwik8"), np.uint8)
    val, test = data[90_000_000:90_300_000], data[95_000_000:96_000_000]
    out = os.path.join(HERE, "data", "scaling.jsonl")
    w = make_state(12, 3000)  # JIT warm-up, so timings do not include compilation
    process(data[:3000].copy(), w, 0, 3000, 3000, 0)
    process(data[:3000].copy(), w, 0, 3000, 0, 0, stp=True)
    done = {json.loads(l)["MB"] for l in open(out)} if os.path.exists(out) else set()
    for mb in SIZES_MB:
        if mb in done:  # resume after an interruption
            continue
        size = mb * 1_000_000
        r = dict(MB=mb, brain=brain(data, test, size))
        print(json.dumps(r), flush=True)
        r["transformer"] = transformer(data, val, test, size, TX_BUDGET[mb])
        print(json.dumps(r), flush=True)
        with open(out, "a") as f:
            f.write(json.dumps(r) + "\n")
    print(f"\n{'data':>6} | {'brain time':>10} {'continual':>9} {'frozen+WM':>9} | "
          f"{'tx budget':>9} {'epochs':>6} {'test':>6}")
    for line in open(out):
        r = json.loads(line)
        b, t = r["brain"], r["transformer"]
        print(f"{r['MB']:>4}MB | {b['train_s']:>9.0f}s {b['continual']:9.3f} {b['frozen_wm']:9.3f} | "
              f"{t['budget_s']:>8}s {t['epochs']:6.1f} {t['test']:6.3f}")


if __name__ == "__main__":
    main()
