"""Замер времени ответа операций контракта.

    python -m scripts.bench --label small
    python -m scripts.bench --label work

Для каждой операции: прогрев (в расчёт не входит), затем серия повторов.
Время ответа снимается на клиенте отметками времени вокруг запроса.
Из заголовков ответа берутся число запросов к базе и их суммарное время
(их выставляет сервер, см. TimingMiddleware в app/main.py).
Результат печатается таблицей и сохраняется в results/<label>.json.
"""

import argparse
import json
import os
import platform
import statistics
import subprocess
import time
from datetime import datetime
from pathlib import Path

import httpx

RESULTS = Path(__file__).resolve().parent.parent / "results"
CARD_TICKET_ID = 147


def percentile(values, p):
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def machine_info():
    try:
        cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                             capture_output=True, text=True).stdout.strip()
        mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True).stdout.strip()) // 2**30
        return f"{cpu}, {mem} ГБ ОЗУ, {platform.system()} {platform.mac_ver()[0] or platform.release()}"
    except Exception:
        return platform.platform()


def operations(client: httpx.Client):
    total = client.get("/api/tickets", params={"size": 20}).json()["total"]
    last_page = max(1, (total + 19) // 20)

    def fresh_ticket():
        r = client.post("/api/tickets", json={"title": "bench: заявка", "body": "создана замером",
                                              "category_id": 1})
        return r.json()["id"]

    comment_ticket = fresh_ticket()

    # (имя, метод, путь, тело, ожидаемый код, подготовка перед каждым вызовом)
    return [
        ("GET /api/me", "GET", lambda _: "/api/me", None, 200, None),
        ("GET /api/categories", "GET", lambda _: "/api/categories", None, 200, None),
        ("GET /api/tickets (стр. 1)", "GET",
         lambda _: "/api/tickets?page=1&size=20", None, 200, None),
        ("GET /api/tickets (фильтр)", "GET",
         lambda _: "/api/tickets?status=in_progress&category_id=2&page=1&size=20", None, 200, None),
        ("GET /api/tickets (поиск)", "GET",
         lambda _: "/api/tickets?q=принтер&page=1&size=20", None, 200, None),
        ("GET /api/tickets (посл. стр.)", "GET",
         lambda _: f"/api/tickets?page={last_page}&size=20", None, 200, None),
        ("GET /api/tickets/{id}", "GET",
         lambda _: f"/api/tickets/{CARD_TICKET_ID}", None, 200, None),
        ("GET /api/summary", "GET", lambda _: "/api/summary", None, 200, None),
        ("POST /api/tickets", "POST", lambda _: "/api/tickets",
         {"title": "bench: заявка", "body": "создана замером", "category_id": 1}, 201, None),
        ("POST /api/tickets/{id}/comments", "POST",
         lambda _: f"/api/tickets/{comment_ticket}/comments", {"body": "комментарий замера"}, 201, None),
        ("PATCH /api/tickets/{id}/status", "PATCH",
         lambda tid: f"/api/tickets/{tid}/status", {"status": "in_progress"}, 200, fresh_ticket),
    ]


def run(base_url, login, password, label, warmup, repeat):
    client = httpx.Client(base_url=base_url, timeout=120, trust_env=False)
    r = client.post("/api/auth/login", json={"login": login, "password": password})
    r.raise_for_status()
    client.headers["Authorization"] = f"Bearer {r.json()['token']}"

    results = []
    for name, method, path, body, expected, setup in operations(client):
        samples = []
        for i in range(warmup + repeat):
            arg = setup() if setup else None
            started = time.perf_counter()
            resp = client.request(method, path(arg), json=body)
            elapsed = (time.perf_counter() - started) * 1000
            if resp.status_code != expected:
                raise SystemExit(f"{name}: ожидался код {expected}, получен {resp.status_code}: {resp.text}")
            if i >= warmup:
                samples.append({
                    "total_ms": elapsed,
                    "app_ms": float(resp.headers["x-app-time-ms"]),
                    "db_ms": float(resp.headers["x-db-time-ms"]),
                    "queries": int(resp.headers["x-db-queries"]),
                })
        totals = [s["total_ms"] for s in samples]
        row = {
            "operation": name,
            "p50": statistics.median(totals),
            "p95": percentile(totals, 95),
            "max": max(totals),
            "app_p50": statistics.median(s["app_ms"] for s in samples),
            "db_p50": statistics.median(s["db_ms"] for s in samples),
            "queries": statistics.median(s["queries"] for s in samples),
        }
        results.append(row)
        print(f"  {name:<34} p50={row['p50']:9.2f}  p95={row['p95']:9.2f}  max={row['max']:9.2f} мс"
              f"  | в базе {row['db_p50']:8.2f} мс, запросов {row['queries']:g}", flush=True)

    meta = {
        "label": label,
        "date": datetime.now().isoformat(timespec="seconds"),
        "machine": machine_info(),
        "python": platform.python_version(),
        "account": login,
        "warmup": warmup,
        "repeat": repeat,
        "base_url": base_url,
    }
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{label}.json"
    out.write_text(json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\nСохранено: {out.relative_to(RESULTS.parent)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True, help="метка серии: small или work")
    parser.add_argument("--base-url", default=f"http://localhost:{os.getenv('APP_PORT', '8080')}")
    parser.add_argument("--login", default="demo")
    parser.add_argument("--password", default="demo")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--repeat", type=int, default=30)
    args = parser.parse_args()
    print(f"Замер «{args.label}»: прогрев {args.warmup}, повторов {args.repeat}, "
          f"учётная запись {args.login}, {args.base_url}\n")
    run(args.base_url, args.login, args.password, args.label, args.warmup, args.repeat)


if __name__ == "__main__":
    main()
