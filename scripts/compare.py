"""Сопоставление замеров малого и рабочего наполнения.

    python -m scripts.compare

Читает results/small.json и results/work.json, печатает таблицу роста времени
ответа и разложение времени (база / код) на рабочем объёме, сохраняет графики
results/chart_p50.png и results/chart_split.png.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "results"


def load(label):
    data = json.loads((RESULTS / f"{label}.json").read_text(encoding="utf-8"))
    return data["meta"], {r["operation"]: r for r in data["results"]}


def main():
    _, small = load("small")
    meta, work = load("work")
    ops = list(work)

    print("Время ответа, мс (малое -> рабочее наполнение)\n")
    print(f"{'Операция':<34} {'p50 мал':>9} {'p95 мал':>9} {'max мал':>9} "
          f"{'p50 раб':>9} {'p95 раб':>9} {'max раб':>9} {'рост p50':>9}")
    for op in ops:
        s, w = small[op], work[op]
        print(f"{op:<34} {s['p50']:9.2f} {s['p95']:9.2f} {s['max']:9.2f} "
              f"{w['p50']:9.2f} {w['p95']:9.2f} {w['max']:9.2f} {w['p50'] / s['p50']:8.1f}x")

    print("\nРазложение времени на рабочем наполнении (медианы), мс\n")
    print(f"{'Операция':<34} {'операция':>9} {'в базе':>9} {'в коде':>9} {'запросов':>9} {'доля БД':>8}")
    for op in ops:
        w = work[op]
        code = w["p50"] - w["db_p50"]
        print(f"{op:<34} {w['p50']:9.2f} {w['db_p50']:9.2f} {code:9.2f} {w['queries']:9g} "
              f"{w['db_p50'] / w['p50'] * 100:7.0f}%")

    labels = [op.replace("/api/", "") for op in ops]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    xs = range(len(ops))
    ax.bar([x - 0.2 for x in xs], [small[o]["p50"] for o in ops], 0.4, label="малое наполнение")
    ax.bar([x + 0.2 for x in xs], [work[o]["p50"] for o in ops], 0.4, label="рабочее наполнение")
    ax.set_yscale("log")
    ax.set_ylabel("p50, мс (логарифмическая шкала)")
    ax.set_title("Медиана времени ответа операций, maksim_kuznetsov")
    ax.set_xticks(list(xs), labels, rotation=35, ha="right", fontsize=8)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS / "chart_p50.png", dpi=150)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    db_share = [work[o]["db_p50"] / work[o]["p50"] * 100 for o in ops]
    code_share = [100 - d for d in db_share]
    ax.bar(labels, db_share, label="в базе данных")
    ax.bar(labels, code_share, bottom=db_share, label="в коде приложения")
    for x, o in enumerate(ops):
        ax.text(x, 101, f"{work[o]['p50']:.0f} мс\n{work[o]['queries']:g} запр.",
                ha="center", va="bottom", fontsize=7)
    ax.set_ylim(0, 115)
    ax.set_ylabel("доля времени операции, %")
    ax.set_title("Куда уходит время операций на рабочем наполнении, maksim_kuznetsov")
    ax.tick_params(axis="x", rotation=35, labelsize=8)
    plt.setp(ax.get_xticklabels(), ha="right")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(RESULTS / "chart_split.png", dpi=150)
    print("\nГрафики: results/chart_p50.png, results/chart_split.png")


if __name__ == "__main__":
    main()
