"""
Where transformers hurt: cost per generated token and memory as the context grows, and
recall of a fact seen far in the past ("needle in a haystack").

  1. Transformer with a KV cache (same 4-layer, 256-dim architecture as the baseline,
     bf16/AMX): time per token and KV-cache size at context 1k ... 64k tokens, batch 1.
     SynapseBrain-LM: time per byte and memory while reading the same text.
  2. Needles: random 32-character passwords are planted in enwik8 test text; the first
     8 characters are repeated 10 kB ... 4 MB later. Bits needed to predict the remaining
     24 characters = how well the model remembers.
"""
import math
import os
import time

import numpy as np
import torch
import torch.nn.functional as F

from brain_lm import make_state, process

HERE = os.path.dirname(os.path.abspath(__file__))
torch.set_num_threads(os.cpu_count())


def transformer_decode_cost(ctx, L=4, d=256, h=4, n_new=64):
    """Batch-1 decoding with a KV cache: attention reads all `ctx` cached keys/values."""
    torch.manual_seed(0)
    Ws = [(torch.randn(d, 3 * d) / d**0.5, torch.randn(d, d) / d**0.5,
           torch.randn(d, 4 * d) / d**0.5, torch.randn(4 * d, d) / (4 * d)**0.5) for _ in range(L)]
    E = torch.randn(256, d) * 0.02
    K = [torch.randn(1, h, ctx, d // h).bfloat16() for _ in range(L)]  # pre-allocated cache
    V = [torch.randn(1, h, ctx, d // h).bfloat16() for _ in range(L)]
    x = E[:1].view(1, 1, d)
    with torch.no_grad(), torch.autocast("cpu", dtype=torch.bfloat16):
        for rep in range(2):  # warm-up + timed
            t = time.perf_counter()
            for _ in range(n_new):
                y = x
                for l, (Wqkv, Wo, W1, W2) in enumerate(Ws):
                    q, k, v = (F.layer_norm(y, (d,)) @ Wqkv).view(1, 1, 3, h, d // h).permute(2, 0, 3, 1, 4)
                    a = F.scaled_dot_product_attention(q, K[l], V[l])  # reads all ctx keys/values
                    y = y + a.transpose(1, 2).reshape(1, 1, d) @ Wo
                    y = y + F.gelu(F.layer_norm(y, (d,)) @ W1) @ W2
                logits = F.layer_norm(y, (d,)) @ E.T
                x = E[logits.float().argmax(-1)].view(1, 1, d)
            dt = (time.perf_counter() - t) / n_new
    kv_bytes = 2 * L * ctx * d * 2  # K and V, bf16
    return dt, kv_bytes


def brain_cost(data, n_bytes):
    st = make_state(0, n_bytes)
    process(data, st, 0, 1_000_000, n_bytes, n_bytes)  # warm memory
    t = time.perf_counter()
    process(data, st, 1_000_000, n_bytes, n_bytes, n_bytes)
    dt = (time.perf_counter() - t) / (n_bytes - 1_000_000)
    mem = sum(v.nbytes for v in st.values())
    return dt, mem


def plant_needles(text, distances, n_per_dist, rng):
    """Insert passwords and their later cue. Returns new text and (start_of_rest, length) spans."""
    alphabet = np.frombuffer(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789", np.uint8)
    events = []
    pos = 50_000
    for D in distances:
        for _ in range(n_per_dist):
            pw = rng.choice(alphabet, 32)
            events.append((pos, pw, "first"))
            events.append((pos + D, pw, "again"))
            pos += 20_000
    events.sort(key=lambda e: e[0])
    out, spans, last = [], [], 0
    shift = 0
    for p, pw, kind in events:
        out.append(text[last:p])
        tag = np.frombuffer(b" password: ", np.uint8)
        piece = np.concatenate([tag, pw, np.frombuffer(b" ", np.uint8)])
        start = p + shift
        if kind == "again":
            spans.append((start + len(tag) + 8, 24, int(p - [e for e in events if e[1] is pw][0][0])))
        out.append(piece)
        shift += len(piece)
        last = p
    out.append(text[last:])
    return np.concatenate(out), spans


def needle_bits_brain(pre, text, spans):
    """Bits the brain needs for each 24-char password tail (reads 10 MB of wiki first)."""
    full = np.concatenate([pre, text])
    st = make_state(0, len(full))
    process(full, st, 0, len(pre), len(pre), 0)
    res = []
    cur = len(pre)
    for s, n, D in spans:
        a = len(pre) + s
        process(full, st, cur, a, len(full), len(full))
        b, _ = process(full, st, a, a + n, len(full), a)
        res.append((D, b / n))
        cur = a + n
    return res


def needle_bits_transformer(ckpt, text, spans):
    """Same needles for a trained transformer; it sees its last `ctx` bytes, as in training."""
    from tx_model import GPT

    ck = torch.load(ckpt)
    a = ck["args"]
    m = GPT(a["layers"], a["dim"], a["heads"], a["ctx"])
    m.load_state_dict(ck["state"])
    m.eval()
    ctx, res = a["ctx"], []
    t = torch.from_numpy(text.astype(np.int64))
    with torch.no_grad(), torch.autocast("cpu", dtype=torch.bfloat16):
        for s, n, D in spans:
            xb = t[s + n - ctx : s + n + 1].view(1, -1)
            lp = F.cross_entropy(m(xb[:, :-1]).float()[0, -n:], xb[0, -n:], reduction="sum")
            res.append((D, lp.item() / math.log(2) / n))
    return res


if __name__ == "__main__":
    data = np.fromfile(os.path.join(HERE, "data", "enwik8"), np.uint8)
    out = {}
    print("## Cost per token vs context length (batch 1, 4 cores)")
    rows = []
    for ctx in [1024, 4096, 16384, 65536]:
        dt, kv = transformer_decode_cost(ctx)
        rows.append((ctx, dt, kv))
        print(f"  transformer ctx {ctx:6d}: {dt * 1e3:6.2f} ms/token, KV cache {kv / 1e6:7.1f} MB", flush=True)
    for n in [4_000_000, 32_000_000]:
        dt, mem = brain_cost(data, n)
        print(f"  SynapseBrain after {n / 1e6:4.0f}M bytes of context: {dt * 1e6:5.2f} us/byte, "
              f"total memory {mem / 1e6:7.1f} MB (text itself: {n / 1e6:.0f} MB)", flush=True)
    out["transformer"] = rows

    print("\n## Needle in a haystack (bits per character of a 24-char random tail; random = 5.95)")
    rng = np.random.default_rng(0)
    test = data[95_000_000:100_000_000]
    dists = [100, 10_000, 100_000, 1_000_000, 3_000_000]
    text, spans = plant_needles(test[:4_000_000], dists, 5, rng)
    nb = needle_bits_brain(data[:10_000_000], text, spans)
    for D in dists:
        v = [b for d, b in nb if d == D]
        print(f"  SynapseBrain, distance {D:>9,} bytes: {np.mean(v):.2f} bits/char", flush=True)
    for name in ["transformer.pt", "transformer_10x.pt"]:
        ck = os.path.join(HERE, "data", name)
        if os.path.exists(ck):
            nt = needle_bits_transformer(ck, text, spans)
            for D in dists:
                v = [b for d, b in nt if d == D]
                print(f"  {name:<19} distance {D:>9,} bytes: {np.mean(v):.2f} bits/char", flush=True)
