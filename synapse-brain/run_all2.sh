#!/bin/sh
set -e
cd "$(dirname "$0")"
./run_lm_all.sh
python3 coh_eval.py brain brain_lm.py 90 0.8 2>&1 | grep -v -i warn | tail -1
BRAIN_ONLY=1 python3 -u scaling_bench.py 2>&1 | grep -v -i warn | tail -7
