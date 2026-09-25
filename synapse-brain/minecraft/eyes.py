"""The brain's eyes as a separate process: headless Chromium looking at the bot's first-person
3D view. For every line on stdin, writes one 64x64 BGR frame (12288 raw bytes) to stdout."""
import sys
import time

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

url = sys.argv[1]
with sync_playwright() as pw:
    import glob
    exe = (glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome") or [None])[0]  # else Playwright's own
    browser = pw.chromium.launch(executable_path=exe, args=["--use-gl=swiftshader", "--enable-webgl",
                                                            "--ignore-gpu-blocklist"])
    page = browser.new_page(viewport={"width": 128, "height": 128})
    for _ in range(30):
        try:
            page.goto(url)
            break
        except Exception:
            time.sleep(2)
    page.wait_for_timeout(5000)
    out = sys.stdout.buffer
    for _ in sys.stdin:
        png = page.screenshot(type="png")
        f = cv2.resize(cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR), (64, 64),
                       interpolation=cv2.INTER_AREA)
        out.write(f.tobytes())
        out.flush()
