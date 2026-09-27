"""
The verdict of the pre-registered check (world/exams/CRITERIA.md): do the newborns learn?

    python verdict.py --label eval-20260929          # prints the verdict (Markdown) and writes it beside the results

Food: each newborn's median ticks to its first meal must be at least 5 times fewer than the random brain's on the
same places (a place where it found nothing counts as the whole limit). Wood: a wooden pickaxe on at least 5 of the
10 places. The experiment is a success if at least one newborn meets both.
"""
import argparse
import json
import os
import statistics
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "world", "exams", "own", "results.jsonl")
NEWBORNS = ("Synapse2", "Synapse3")
FOOD_FACTOR, WOOD_PLACES, LIMIT = 5.0, 5, 24000


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True)
    a = p.parse_args()
    rows = [json.loads(line) for line in open(RESULTS, encoding="utf-8")]
    rows = [r for r in rows if r.get("label") == a.label]

    def food(who):
        t = [r["first"].get("ate", LIMIT) for r in rows if r["subject"] == who and r["task"] == "forage"]
        return (statistics.median(t) if t else None), len(t), t

    def wood(who):
        rs = [r for r in rows if r["subject"] == who and r["task"] == "wood"]
        steps = {g: sum(1 for r in rs if g in r["first"]) for g in ("log", "planks", "crafting_table", "wooden_pickaxe")}
        return steps, len(rs)

    rnd, n_rnd, t_rnd = food("random")
    out = [f"# Вердикт: {a.label}", "", f"_{time.strftime('%Y-%m-%d %H:%M')}; критерий: world/exams/CRITERIA.md_", "",
           f"Случайный мозг — найти еду: медиана {rnd} тиков ({n_rnd} мест: {t_rnd})", ""]
    ok_any = False
    for who in NEWBORNS:
        med, n, t = food(who)
        steps, n_w = wood(who)
        f_ok = med is not None and rnd is not None and med * FOOD_FACTOR <= rnd
        w_ok = steps["wooden_pickaxe"] >= WOOD_PLACES
        ok_any = ok_any or (f_ok and w_ok)
        ratio = f"{rnd / med:.1f}×" if med and rnd else "—"
        out += [f"## {who}",
                f"- еда: медиана {med} тиков ({n} мест: {t}) — быстрее случайного в {ratio} → "
                f"{'✓' if f_ok else '✗'} (нужно ≥ {FOOD_FACTOR:g}×)",
                f"- дерево ({n_w} мест): бревно {steps['log']}, доски {steps['planks']}, верстак {steps['crafting_table']}, "
                f"деревянная кирка {steps['wooden_pickaxe']} → {'✓' if w_ok else '✗'} (нужно ≥ {WOOD_PLACES})",
                f"- **{'оба условия' if f_ok and w_ok else 'одно условие' if f_ok or w_ok else 'ни одного условия'}**", ""]
    out += [f"## Итог: {'УСПЕХ' if ok_any else 'ПРОВАЛ — пересматриваем подход (CRITERIA.md)'}", ""]
    text = "\n".join(out)
    print(text)
    with open(os.path.join(HERE, "world", "exams", f"verdict-{a.label}.md"), "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
