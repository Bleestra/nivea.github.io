"""
SynapseBrain-LM on the standard enwik8 split: train = first 90 MB, test = last 5 MB.

  strict frozen   : nothing changes after training except the episodic store (the text read
                    so far and its hash index - the analogue of a transformer's context)
  frozen weights + working memory : long-term synapses frozen; active cells still remember
                    their last 6 outcomes (short-term plasticity, like a context window)
  continual       : the model keeps learning while it reads the test (predict first, then learn)
"""
import json
import os
import sys
import time

import numpy as np

from brain_lm import make_state, process

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN, VALID, TOTAL = 90_000_000, 95_000_000, 100_000_000


def main(shrink=0, lr=0.002):
    data = np.fromfile(os.path.join(HERE, "data", "enwik8"), np.uint8)
    process(data[:2000].copy(), make_state(12, 2000), 0, 2000, 2000, 0)  # JIT warm-up
    st = make_state(shrink, TOTAL)
    t = time.perf_counter()
    process(data, st, 0, TRAIN, TRAIN, TRAIN, lr=lr)  # one pass, learning, nothing scored
    train_time = time.perf_counter() - t
    print(f"train: {TRAIN / 1e6:.0f} MB in {train_time:.1f} s ({TRAIN / train_time / 1e6:.2f} MB/s)", flush=True)

    res = dict(shrink=shrink, train_time=train_time, train_MBps=TRAIN / train_time / 1e6,
               memory_MB=sum(v.nbytes for v in st.values()) / 1e6)
    # evaluation modes must all start from the same trained brain; the synapse tables are
    # parked on disk instead of copied in RAM (they are several GB)
    small = {k: st[k].copy() for k in ("MT", "MT2", "MT3", "MT4", "WC", "S", "LN")}
    park = os.path.join(HERE, "data", "_T_parked.npy")
    np.save(park, st["T"])

    def restore():
        st["T"][:] = np.load(park, mmap_mode="r")
        for k, v in small.items():
            st[k][:] = v

    for mode, stp in [("strict_frozen", False), ("frozen_weights_working_memory", True)]:
        t = time.perf_counter()
        process(data, st, TRAIN, VALID, 0, TOTAL, lr=lr, stp=stp)          # read, no learning
        b, n = process(data, st, VALID, TOTAL, 0, VALID, lr=lr, stp=stp)   # score test
        res[f"test_bpc_{mode}"] = b / n
        res[f"t_{mode}"] = time.perf_counter() - t
        restore()
    os.remove(park)
    t = time.perf_counter()
    cb, cn = process(data, st, TRAIN, TOTAL, TOTAL, VALID, lr=lr)          # keep learning
    res["test_bpc_continual"] = cb / cn
    res["t_continual"] = time.perf_counter() - t
    print(json.dumps(res), flush=True)
    return res


if __name__ == "__main__":
    main(*(float(a) if "." in a else int(a) for a in sys.argv[1:]))
