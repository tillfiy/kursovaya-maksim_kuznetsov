"""Разбор профиля, снятого scripts/profile_server.py: таблица функций и флеймграф.

    python -m scripts.profile_report heavy

Доли считаются от снимков потоков, занятых обработкой запроса (в стеке есть
функция из каталога app/), — это время обработки запросов, включая ожидание
ответа базы данных. Простаивающие потоки пула (ждут задачу) в расчёт не входят.
Флеймграф сохраняется в results/load/profile_<label>.png.
"""

import collections
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "load"


def parse(path):
    meta, stacks = {}, []
    for line in path.read_text().splitlines():
        if line.startswith("#"):
            meta = dict(kv.split("=") for kv in line[1:].split())
            continue
        stack, n = line.rsplit(" ", 1)
        stacks.append((stack.split(";"), int(n)))
    return meta, stacks


def is_own(label):
    return "(app/" in label


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "heavy"
    meta, stacks = parse(OUT / f"profile_{label}.txt")
    work = [(s, n) for s, n in stacks if any(is_own(f) for f in s)]
    total_work = sum(n for _, n in work)
    total_all = sum(n for _, n in stacks)
    print(f"Профиль «{label}»: {meta.get('snapshots')} снимков за {meta.get('duration')} с "
          f"({meta.get('rate')} раз/с); снимков потоков всего {total_all}, "
          f"из них за обработкой запроса {total_work}\n")

    inclusive = collections.Counter()
    for s, n in work:
        for f in set(s):
            inclusive[f] += n
    print("Функции сервиса (доля снимков, в которых функция есть в стеке):")
    for f, n in inclusive.most_common():
        if is_own(f):
            print(f"  {n / total_work * 100:6.1f} %  {f}")

    # Где проводится время: самая глубокая функция стека (лист) вместе с функцией сервиса,
    # из которой она вызвана.
    leaves = collections.Counter()
    for s, n in work:
        own = [f for f in s if is_own(f)][-1]
        leaves[(s[-1], own)] += n
    print("\nГорячие листья стека (функция библиотеки ← ближайшая функция сервиса):")
    for (leaf, own), n in leaves.most_common(8):
        print(f"  {n / total_work * 100:6.1f} %  {leaf}  ←  {own}")

    # Флеймграф: стеки обрезаются до первой функции сервиса, корень внизу.
    tree = {"n": 0, "kids": {}}
    for s, n in work:
        first = next(i for i, f in enumerate(s) if is_own(f))
        node = tree
        node["n"] += n
        for f in s[first:]:
            node = node["kids"].setdefault(f, {"n": 0, "kids": {}})
            node["n"] += n

    fig, ax = plt.subplots(figsize=(14, 7))
    colors = ["#e8743b", "#f2a541", "#f6c85f", "#ed9b52", "#de6b48"]
    max_depth = [0]

    def draw(node, x, depth):
        for name, kid in sorted(node["kids"].items(), key=lambda kv: -kv[1]["n"]):
            w = kid["n"] / total_work
            color = "#5b8ff9" if is_own(name) else colors[hash(name) % len(colors)]
            ax.add_patch(Rectangle((x, depth), w, 0.95, facecolor=color, edgecolor="white", linewidth=0.5))
            if w > 0.06:
                text = name if len(name) < w * 140 else name[: max(3, int(w * 140) - 1)] + "…"
                ax.text(x + 0.003, depth + 0.45, text, va="center", fontsize=6.5, clip_on=True)
            max_depth[0] = max(max_depth[0], depth + 1)
            draw(kid, x, depth + 1)
            x += w

    draw(tree, 0, 0)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, max_depth[0])
    ax.set_yticks([])
    ax.set_xlabel("доля снимков обработки запроса (синие — функции сервиса из app/)")
    ax.set_title(f"Флеймграф под нагрузкой, сценарий {label}, maksim_kuznetsov")
    fig.tight_layout()
    fig.savefig(OUT / f"profile_{label}.png", dpi=150)
    print(f"\nФлеймграф: results/load/profile_{label}.png")


if __name__ == "__main__":
    main()
