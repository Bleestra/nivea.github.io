"""
Grow the large visual cortex on the GPU by watching: no labels, only structural Hebbian plasticity and
homeostasis (the same development as in vision_bench.py, on a 4x larger cortex and picture).

What it watches (any mix):
  - recordings of the bot's own eyes: rec_*.npz from brain_server.py --record (frames of the real game)
  - videos (*.mp4, *.avi, *.mkv), e.g. MineRL Navigate, or folders of pictures (*.png, *.jpg)

    python develop_gpu.py <dir-or-file> [...] [--out ../minecraft/models/visual_cortex_gpu.npz]
                          [--neurons 32768] [--size 128] [--passes 1]
"""
import argparse
import glob
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from visual_cortex_gpu import VisualCortexGPU, retina_gpu  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def frames_from(path, size, every=4):
    """Yield uint8 BGR frames (size x size) from recordings, videos and pictures."""
    files = sorted(glob.glob(os.path.join(path, "**", "*"), recursive=True)) if os.path.isdir(path) else [path]
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if ext == ".npz":
            z = np.load(f)
            if "frames" in z.files:
                for fr in z["frames"]:
                    yield cv2.resize(fr, (size, size), interpolation=cv2.INTER_AREA)
        elif ext in (".mp4", ".avi", ".mkv", ".webm"):
            cap = cv2.VideoCapture(f)
            k = 0
            while True:
                ok, fr = cap.read()
                if not ok:
                    break
                if k % every == 0:                          # neighbouring video frames are almost the same
                    yield cv2.resize(fr, (size, size), interpolation=cv2.INTER_AREA)
                k += 1
        elif ext in (".png", ".jpg", ".jpeg", ".bmp"):
            fr = cv2.imread(f, cv2.IMREAD_COLOR)
            if fr is not None:
                yield cv2.resize(fr, (size, size), interpolation=cv2.INTER_AREA)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("sources", nargs="+")
    p.add_argument("--out", default=os.path.join(HERE, "..", "minecraft", "models", "visual_cortex_gpu.npz"))
    p.add_argument("--neurons", type=int, default=32768)
    p.add_argument("--size", type=int, default=128)
    p.add_argument("--passes", type=int, default=1)
    p.add_argument("--batch", type=int, default=64)
    a = p.parse_args()
    c = VisualCortexGPU(n=a.neurons, size=a.size, seed=1)
    if os.path.exists(a.out) and c.load(a.out):
        print("continuing the development of", a.out, flush=True)
    seen, t0 = 0, time.time()
    for _ in range(a.passes):
        for src in a.sources:
            buf = []
            for fr in frames_from(src, a.size):
                buf.append(fr)
                if len(buf) == a.batch:
                    c(retina_gpu(np.array(buf), a.size), plasticity=True)
                    seen += len(buf)
                    buf = []
                    if seen % (a.batch * 50) == 0:
                        print(f"{seen} frames, {seen / (time.time() - t0):.0f}/s", flush=True)
            if buf:
                c(retina_gpu(np.array(buf), a.size), plasticity=True)
                seen += len(buf)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    c.save(a.out)
    print(f"watched {seen} frames in {time.time() - t0:.0f} s -> {a.out}")


if __name__ == "__main__":
    main()
