#!/bin/sh
# Full language-model comparison, run strictly one job at a time (no CPU sharing).
set -e
cd "$(dirname "$0")"
python3 lm_bench.py 0 2>&1 | grep -v -i warn | tee data/lm_brain.txt
BUDGET=$(python3 -c "import json;print(round(json.loads(open('data/lm_brain.txt').read().splitlines()[-1])['train_time']))")
python3 transformer_baseline.py --budget "$BUDGET" --layers 2 --dim 256 --ctx 128 --batch 32 --lr 4e-3 \
    --save data/transformer.pt --out data/tx_results.jsonl 2>&1 | tail -1 | tee data/lm_tx_equal.txt
python3 context_bench.py 2>&1 | grep -v -i warn | tee data/context.txt
python3 forget_bench.py 2>&1 | grep -v -i warn | tee data/forget.txt
