"""
Baseline: byte-level GPT (pre-LN, GELU, tied embeddings, AdamW, warmup + cosine), trained on
enwik8 for a fixed WALL-CLOCK budget on the same CPU, with bf16 autocast (Intel AMX) to give
it every speed advantage available on this machine.

    python3 transformer_baseline.py --budget 150 --layers 4 --dim 256
"""
import argparse
import json
import math
import os
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

p = argparse.ArgumentParser()
p.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "enwik8"))
p.add_argument("--budget", type=float, default=150.0, help="training seconds")
p.add_argument("--layers", type=int, default=4)
p.add_argument("--dim", type=int, default=256)
p.add_argument("--heads", type=int, default=4)
p.add_argument("--ctx", type=int, default=256)
p.add_argument("--batch", type=int, default=32)
p.add_argument("--lr", type=float, default=2e-3)
p.add_argument("--eval_bytes", type=int, default=5_000_000)
p.add_argument("--bf16", type=int, default=1)
p.add_argument("--seed", type=int, default=0)
p.add_argument("--out", default="")
p.add_argument("--save", default="")
args = p.parse_args()

torch.manual_seed(args.seed)
torch.set_num_threads(os.cpu_count())
raw = np.fromfile(args.data, np.uint8)
train, test = raw[:90_000_000], raw[95_000_000:95_000_000 + args.eval_bytes]
train_t = torch.from_numpy(train.astype(np.int64))


from tx_model import GPT  # noqa: E402

model = GPT(args.layers, args.dim, args.heads, args.ctx)
n_params = sum(q.numel() for q in model.parameters())
decay = [q for n, q in model.named_parameters() if q.dim() >= 2 and "pos" not in n]
rest = [q for n, q in model.named_parameters() if not (q.dim() >= 2 and "pos" not in n)]
opt = torch.optim.AdamW([{"params": decay, "weight_decay": 0.1}, {"params": rest, "weight_decay": 0.0}],
                        lr=args.lr, betas=(0.9, 0.95))
ac = torch.autocast("cpu", dtype=torch.bfloat16, enabled=bool(args.bf16))
rng = np.random.default_rng(args.seed)

t0 = time.time()
step, seen = 0, 0
while True:
    frac = (time.time() - t0) / args.budget
    if frac >= 1:
        break
    lr = args.lr * min(1.0, (step + 1) / 100) * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * frac)))
    for g in opt.param_groups:
        g["lr"] = lr
    ix = torch.from_numpy(rng.integers(0, len(train) - args.ctx - 1, args.batch))
    xb = torch.stack([train_t[i : i + args.ctx + 1] for i in ix])
    with ac:
        logits = model(xb[:, :-1])
    loss = F.cross_entropy(logits.float().reshape(-1, 256), xb[:, 1:].reshape(-1))
    opt.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    opt.step()
    step += 1
    seen += args.batch * args.ctx
    if step % 200 == 0:
        print(f"  step {step} {time.time() - t0:6.0f}s train {loss.item() / math.log(2):.3f} bpc", flush=True)
train_time = time.time() - t0

# evaluation: sliding windows, every scored byte has >= ctx/2 bytes of context
model.eval()
te = torch.from_numpy(test.astype(np.int64))
half = args.ctx // 2
tot, cnt = 0.0, 0
t1 = time.time()
with torch.no_grad(), ac:
    starts = list(range(0, len(test) - args.ctx - 1, half))
    for s in range(0, len(starts), 64):
        xb = torch.stack([te[i : i + args.ctx + 1] for i in starts[s : s + 64]])
        lg = model(xb[:, :-1]).float()
        lp = F.cross_entropy(lg.reshape(-1, 256), xb[:, 1:].reshape(-1), reduction="none").view(len(xb), -1)
        first = starts[s] == 0
        tot += lp[:, half:].sum().item() + (lp[0, :half].sum().item() if first else 0)
        cnt += lp[:, half:].numel() + (half if first else 0)
bpc = tot / cnt / math.log(2)
res = dict(params=n_params, layers=args.layers, dim=args.dim, ctx=args.ctx, budget=args.budget,
           train_time=train_time, steps=step, tokens_seen=seen, tok_per_s=seen / train_time,
           test_bpc=bpc, eval_bytes=cnt, eval_time=time.time() - t1)
print(json.dumps(res))
if args.save:
    torch.save({"args": vars(args), "state": model.state_dict()}, args.save)
if args.out:
    with open(args.out, "a") as f:
        f.write(json.dumps(res) + "\n")
