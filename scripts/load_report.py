"""Таблица ступеней, точка излома и графики по результатам scripts/load_series.

    python -m scripts.load_report mixed
    python -m scripts.load_report heavy

Печатает таблицу ступеней (частота, медиана, p95, максимум, доля ошибок,
пропущенные запросы, фактическая частота), точку излома и допустимую
интенсивность, разбивку по операциям на ступени излома и сводку ресурсов по
ступеням. Сохраняет графики results/load/<label>_p95.png и <label>_resources.png.
"""

import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "load"
THRESHOLD_MS = 500


def seconds(duration):
    return int(duration[:-1]) * (60 if duration.endswith("m") else 1)


def load_steps(label):
    steps = json.loads((OUT / f"{label}_steps.json").read_text())
    rows = []
    for s in steps:
        data = json.loads((ROOT / s["file"]).read_text())
        m = data["metrics"]
        d = m["http_req_duration{phase:load}"]["values"]
        count = m["http_reqs{phase:load}"]["values"]["count"]
        rows.append({
            **s,
            "p50": d["med"], "p95": d["p(95)"], "max": d["max"],
            "errors": m["http_req_failed{phase:load}"]["values"]["rate"] * 100,
            "dropped": m.get("dropped_iterations", {}).get("values", {}).get("count", 0),
            "actual": count / seconds(data["duration"]),
            "metrics": m,
        })
    return rows


def load_resources(label):
    with open(OUT / f"{label}_resources.csv") as f:
        return [{k: float(v) for k, v in r.items()} for r in csv.DictReader(f)]


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "mixed"
    rows = load_steps(label)
    res = load_resources(label)

    print(f"Ступени серии «{label}» (время в мс)\n")
    print(f"{'частота':>8} {'p50':>9} {'p95':>9} {'max':>9} {'ошибок,%':>9} {'dropped':>8} {'факт.':>7}  порог")
    for r in rows:
        print(f"{r['rate']:>8} {r['p50']:9.1f} {r['p95']:9.1f} {r['max']:9.1f} {r['errors']:9.2f} "
              f"{r['dropped']:8.0f} {r['actual']:7.2f}  {'выдержан' if r['passed'] else 'НАРУШЕН'}")
    broken = next((r for r in rows if not r["passed"]), None)
    if broken:
        idx = rows.index(broken)
        if idx == 0:
            print("\nПорог нарушен уже на первой ступени: точки излома нет.")
        else:
            print(f"\nТочка излома: {broken['rate']} запр/с; допустимая интенсивность: {rows[idx - 1]['rate']} запр/с")
        best = max(rows, key=lambda r: r["actual"])
        print(f"Наибольшая фактическая частота: {best['actual']:.2f} запр/с (ступень {best['rate']})")

        print(f"\nОперации на ступени излома ({broken['rate']} запр/с):")
        print(f"  {'операция':<16} {'запросов':>8} {'p50':>9} {'p95':>9} {'ошибок,%':>9}")
        m = broken["metrics"]
        for key in sorted(k for k in m if k.startswith("http_req_duration{op:")):
            op = key[len("http_req_duration{op:"):-1]
            v = m[key]["values"]
            if not v.get("max"):
                continue
            fail = m.get(f"http_req_failed{{op:{op}}}", {}).get("values", {})
            n = fail.get("passes", 0) + fail.get("fails", 0)
            print(f"  {op:<16} {n:>8.0f} {v['med']:9.1f} {v['p(95)']:9.1f} {fail.get('rate', 0) * 100:9.1f}")

    print("\nРесурсы по ступеням (среднее / максимум за ступень):")
    print(f"{'частота':>8} {'CPU прил.,%':>13} {'CPU БД,%':>13} {'память прил.,МБ':>16} {'память БД,МБ':>13} "
          f"{'соедин.':>8} {'активных':>9} {'паралл.':>8}")
    for r in rows:
        part = [x for x in res if r["start"] <= x["t"] <= r["end"]]
        if not part:
            continue

        def avgmax(k):
            vals = [x[k] for x in part]
            return sum(vals) / len(vals), max(vals)

        a, d = avgmax("app_cpu"), avgmax("db_cpu")
        print(f"{r['rate']:>8} {a[0]:6.0f} / {a[1]:4.0f} {d[0]:6.0f} / {d[1]:4.0f} "
              f"{avgmax('app_mem_mb')[1]:16.0f} {avgmax('db_mem_mb')[1]:13.0f} "
              f"{avgmax('db_conn_total')[1]:8.0f} {avgmax('db_conn_active')[1]:9.0f} "
              f"{avgmax('db_parallel_workers')[1]:8.0f}")

    # p95 от частоты
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot([r["rate"] for r in rows], [r["p95"] for r in rows], "o-", label="p95 времени ответа")
    ax.axhline(THRESHOLD_MS, color="red", linestyle="--", label="порог 500 мс")
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xticks([r["rate"] for r in rows], [str(r["rate"]) for r in rows])
    ax.set_xlabel("частота, запросов в секунду")
    ax.set_ylabel("p95, мс (логарифмическая шкала)")
    ax.set_title(f"p95 от частоты, сценарий {label}, maksim_kuznetsov")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / f"{label}_p95.png", dpi=150)

    # ряд ресурсов по времени
    t = [x["t"] for x in res]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True)
    ax1.plot(t, [x["app_cpu"] for x in res], label="процессор приложения")
    ax1.plot(t, [x["db_cpu"] for x in res], label="процессор БД (контейнер)")
    ax1.set_ylabel("% от одного ядра")
    ax2.plot(t, [x["db_conn_total"] for x in res], label="соединений с БД всего")
    ax2.plot(t, [x["db_conn_active"] for x in res], label="выполняют запрос")
    ax2.plot(t, [x["db_parallel_workers"] for x in res], label="параллельных процессов БД", alpha=0.6)
    ax2.set_ylabel("соединений")
    ax2.set_xlabel("время от начала серии, с")
    for ax in (ax1, ax2):
        for r in rows:
            ax.axvspan(r["start"], r["end"], color="red" if not r["passed"] else "grey", alpha=0.08)
        ax.grid(alpha=0.3)
        ax.legend(loc="upper left", fontsize=8)
    for r in rows:
        ax1.text((r["start"] + r["end"]) / 2, ax1.get_ylim()[1] * 0.92, f"{r['rate']}/с", ha="center", fontsize=8)
    ax1.set_title(f"Потребление ресурсов по ступеням, сценарий {label}, maksim_kuznetsov")
    fig.tight_layout()
    fig.savefig(OUT / f"{label}_resources.png", dpi=150)
    print(f"\nГрафики: results/load/{label}_p95.png, results/load/{label}_resources.png")


if __name__ == "__main__":
    main()
