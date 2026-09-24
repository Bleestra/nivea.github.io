"""Byte-level GPT used as the transformer baseline."""
import torch
import torch.nn as nn
import torch.nn.functional as F


class Block(nn.Module):
    def __init__(s, d, h):
        super().__init__()
        s.ln1, s.ln2 = nn.LayerNorm(d), nn.LayerNorm(d)
        s.qkv, s.proj = nn.Linear(d, 3 * d), nn.Linear(d, d)
        s.fc1, s.fc2 = nn.Linear(d, 4 * d), nn.Linear(4 * d, d)
        s.h = h

    def forward(s, x):
        B, T, C = x.shape
        q, k, v = s.qkv(s.ln1(x)).view(B, T, 3, s.h, C // s.h).permute(2, 0, 3, 1, 4)
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        x = x + s.proj(y.transpose(1, 2).reshape(B, T, C))
        return x + s.fc2(F.gelu(s.fc1(s.ln2(x))))


class GPT(nn.Module):
    def __init__(s, L, d, h, ctx):
        super().__init__()
        s.emb, s.pos = nn.Embedding(256, d), nn.Parameter(torch.zeros(1, ctx, d))
        s.blocks = nn.ModuleList([Block(d, h) for _ in range(L)])
        s.ln = nn.LayerNorm(d)
        nn.init.normal_(s.pos, std=0.02)
        # GPT-2 initialisation: N(0, 0.02), residual projections scaled by 1/sqrt(2L)
        for n, q in s.named_parameters():
            if n.endswith("weight") and q.dim() == 2:
                std = 0.02 / (2 * L) ** 0.5 if n.endswith(("proj.weight", "fc2.weight")) else 0.02
                nn.init.normal_(q, std=std)
            elif n.endswith("bias"):
                nn.init.zeros_(q)

    def forward(s, idx):
        x = s.emb(idx) + s.pos[:, : idx.shape[1]]
        for b in s.blocks:
            x = b(x)
        return s.ln(x) @ s.emb.weight.T


def evaluate(model, data, ctx, batch=64):
    """Bits per byte on `data` (uint8), sliding windows: every scored byte sees >= ctx/2 bytes."""
    import math

    import numpy as np

    model.eval()
    te = torch.from_numpy(data.astype(np.int64))
    half = ctx // 2
    tot, cnt = 0.0, 0
    with torch.no_grad(), torch.autocast("cpu", dtype=torch.bfloat16):
        starts = list(range(0, len(data) - ctx - 1, half))
        for s in range(0, len(starts), batch):
            xb = torch.stack([te[i : i + ctx + 1] for i in starts[s : s + batch]])
            lp = F.cross_entropy(model(xb[:, :-1]).float().reshape(-1, 256), xb[:, 1:].reshape(-1),
                                 reduction="none").view(len(xb), -1)
            first = starts[s] == 0
            tot += lp[:, half:].sum().item() + (lp[0, :half].sum().item() if first else 0)
            cnt += lp[:, half:].numel() + (half if first else 0)
    return tot / cnt / math.log(2)


def train_for(model, data, seconds, lr, batch, ctx, seed=0):
    """Plain AdamW training on random windows of `data` for a wall-clock budget."""
    import time

    import numpy as np

    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=lr, betas=(0.9, 0.95), weight_decay=0.1)
    rng = np.random.default_rng(seed)
    d = torch.from_numpy(data.astype(np.int64))
    t0, steps = time.time(), 0
    while time.time() - t0 < seconds:
        ix = rng.integers(0, len(data) - ctx - 1, batch)
        xb = torch.stack([d[i : i + ctx + 1] for i in ix])
        with torch.autocast("cpu", dtype=torch.bfloat16):
            logits = model(xb[:, :-1])
        loss = F.cross_entropy(logits.float().reshape(-1, 256), xb[:, 1:].reshape(-1))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        steps += 1
    return steps
