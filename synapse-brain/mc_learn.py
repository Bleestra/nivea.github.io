"""
Feed the brain Minecraft knowledge: start from the brain that read English Wikipedia (enwik8,
90 MB), let it read the Minecraft Wiki (45k articles), 88k wiki Q&A pairs and CraftJarvis
gameplay instructions in one pass, then check what it learned on held-out wiki articles and
whether it forgot Wikipedia. Saves the result as data/_brain_mc.npz and prints answers.

    python3 mc_learn.py
"""
import os
import time

import numpy as np

from brain_lm import generate, make_state, process

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "data")

wiki = np.fromfile(os.path.join(D, "enwik8"), np.uint8)
mc_train = np.frombuffer(open(os.path.join(D, "mc", "mc_train.txt"), "rb").read(), np.uint8)
mc_test = np.frombuffer(open(os.path.join(D, "mc", "mc_test.txt"), "rb").read(), np.uint8)
A = 90_000_000
B = A + len(mc_train)
X = np.concatenate([wiki[:A], mc_train, mc_test, wiki[95_000_000:96_000_000], np.zeros(200_000, np.uint8)])
C, E, G = B + len(mc_test), B + len(mc_test) + 1_000_000, len(X) - 200_000

st = make_state(0, len(X))
snap = os.path.join(D, "_brain_90MB.npz")
tfile = os.path.join(D, "_brain_90MB_T.npy")
if not os.path.exists(tfile):  # unpack the big synapse table once, then map it (no 2nd copy in RAM)
    import zipfile
    with zipfile.ZipFile(snap) as zf, zf.open("T.npy") as src, open(tfile, "wb") as dst:
        while chunk := src.read(1 << 26):
            dst.write(chunk)
st["T"][:] = np.load(tfile, mmap_mode="r")
z = np.load(snap)
for k in st:
    if k in z.files and k not in ("buf", "T"):
        st[k][...] = z[k]
st["buf"][:A] = wiki[:A]
del z
park = os.path.join(D, "_T_mc.npy")
KEYS = ("MT", "MT2", "MT3", "MT4", "WC", "S", "LN")


def evaluate(tag):
    """Frozen weights + working memory on held-out Minecraft wiki and on Wikipedia."""
    np.save(park, st["T"])
    small = {k: st[k].copy() for k in KEYS}
    out = []
    for a, b in [(B, C), (C, E)]:
        bits, n = process(X, st, a, b, 0, a, stp=True)
        out.append(bits / n)
        st["T"][:] = np.load(park, mmap_mode="r")
        for k, v in small.items():
            st[k][...] = v
    os.remove(park)
    print(f"{tag}: Minecraft wiki (held out) {out[0]:.3f} bpc, Wikipedia {out[1]:.3f} bpc", flush=True)
    return out


before = evaluate("before reading Minecraft")
t = time.perf_counter()
process(X, st, A, B, B, B)
print(f"read {len(mc_train) / 1e6:.1f} MB of Minecraft text in {time.perf_counter() - t:.0f} s", flush=True)
after = evaluate("after reading Minecraft")
np.savez(os.path.join(D, "_brain_mc.npz"), **st)

prompts = [b"Q: Is the crafting table in Minecraft considered a passive item?\nA:",   # seen in training
           b"Q: How do you craft a crafting table?\nA:",                               # new questions
           b"Q: What do creepers do?\nA:",
           b"Q: How do you get obsidian?\nA:",
           b"== Nether portal ==\nA nether portal is"]
pos = G
for k, p in enumerate(prompts):
    out = generate(st, X, pos, 220, temp=0.6, seed=k, prompt=p)
    print("\n>>>", p.decode(), out.decode("utf8", "replace").split("\n\n")[0], flush=True)
    pos += len(p) + 230
