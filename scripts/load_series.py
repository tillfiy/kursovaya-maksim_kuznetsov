"""Ступенчатое нагрузочное испытание с записью потребления ресурсов.

    python -m scripts.load_series --scenario mixed --rates 2,4,8,16,32
    python -m scripts.load_series --scenario heavy --rates 1,2,4,8

Для каждой ступени запускается load/test.js (k6) с заданной частотой; между
ступенями скрипт ждёт, пока процессор приложения вернётся к простою. Ступени
идут, пока порог не нарушен, и ещё --after-fail ступеней после первого нарушения.

Всё время испытания раз в секунду записываются:
  - загрузка процессора (% от одного ядра) и память процесса приложения (uvicorn);
  - загрузка процессора и память контейнера базы данных (docker stats);
  - число соединений с базой — всех и выполняющих запрос, а также параллельных
    процессов Postgres, помогающих этим запросам (pg_stat_activity).

Результаты: results/load/<scenario>_<rate>.json (итоги k6 по ступеням),
results/load/<scenario>_resources.csv (ряд ресурсов), results/load/<scenario>_steps.json
(границы ступеней по времени).
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import psutil
import psycopg

from app import config

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "load"
DB_CONTAINER = "maksim_kuznetsov_db"


def find_app_process():
    for p in psutil.process_iter(["pid", "cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if ("app.main:app" in cmd or "scripts.profile_server" in cmd) and "py-spy" not in cmd:
            return p
    raise SystemExit("Не найден процесс сервиса (uvicorn app.main:app) — запустите его")


class DockerStats(threading.Thread):
    """Читает поток `docker stats` контейнера базы и хранит последнее значение."""

    def __init__(self):
        super().__init__(daemon=True)
        self.cpu, self.mem_mb = 0.0, 0.0
        self.proc = subprocess.Popen(
            ["docker", "stats", "--format", "{{.CPUPerc}};{{.MemUsage}}", DB_CONTAINER],
            stdout=subprocess.PIPE, text=True)

    def run(self):
        for line in self.proc.stdout:
            line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).strip()
            m = re.match(r"([\d.]+)%;([\d.]+)(\w+)", line)
            if not m:
                continue
            self.cpu = float(m.group(1))
            value, unit = float(m.group(2)), m.group(3)
            self.mem_mb = value * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}.get(unit, 1)

    def stop(self):
        self.proc.terminate()


class Monitor(threading.Thread):
    def __init__(self, app, path):
        super().__init__(daemon=True)
        self.app, self.path = app, path
        self.stop_event = threading.Event()
        self.app_cpu = 0.0
        self.docker = DockerStats()

    def app_tree(self):
        procs = [self.app]
        try:
            procs += self.app.children(recursive=True)
        except psutil.Error:
            pass
        return procs

    def run(self):
        self.docker.start()
        conn = psycopg.connect(config.DATABASE_URL, autocommit=True)
        for p in self.app_tree():
            p.cpu_percent(None)
        with open(self.path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t", "app_cpu", "app_mem_mb", "db_cpu", "db_mem_mb", "db_conn_total", "db_conn_active", "db_parallel_workers"])
            start = time.time()
            while not self.stop_event.wait(1.0):
                procs = self.app_tree()
                cpu = sum(p.cpu_percent(None) for p in procs if p.is_running())
                mem = sum(p.memory_info().rss for p in procs if p.is_running()) / 2**20
                self.app_cpu = cpu
                row = conn.execute(
                    "SELECT count(*) FILTER (WHERE backend_type = 'client backend'), "
                    "count(*) FILTER (WHERE backend_type = 'client backend' AND state = 'active'), "
                    "count(*) FILTER (WHERE backend_type = 'parallel worker') "
                    "FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()").fetchone()
                w.writerow([f"{time.time() - start:.1f}", f"{cpu:.1f}", f"{mem:.1f}",
                            f"{self.docker.cpu:.1f}", f"{self.docker.mem_mb:.1f}", row[0], row[1], row[2]])
                f.flush()
        conn.close()
        self.docker.stop()


def k6_command(args, rate, out):
    env = ["-e", f"SCENARIO={args.scenario}", "-e", f"RATE={rate}", "-e", f"DURATION={args.duration}",
           "-e", f"OUT={out}"]
    if shutil.which("k6") and not args.docker_k6:
        return ["k6", "run", "-q", *env, "-e", f"BASE_URL={args.base_url}", "load/test.js"]
    base = args.base_url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
    return ["docker", "run", "--rm", "-v", f"{ROOT}:/work", "-w", "/work", "grafana/k6", "run", "-q",
            *env, "-e", f"BASE_URL={base}", "load/test.js"]


def wait_idle(monitor, limit=5.0, seconds=3, timeout=90):
    """Ждёт, пока процессор приложения и базы не опустится ниже limit % несколько секунд подряд."""
    calm, waited = 0, 0
    while calm < seconds and waited < timeout:
        time.sleep(1)
        waited += 1
        calm = calm + 1 if monitor.app_cpu < limit and monitor.docker.cpu < limit else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=["mixed", "heavy"], required=True)
    parser.add_argument("--rates", required=True, help="частоты ступеней через запятую, например 2,4,8,16")
    parser.add_argument("--duration", default="30s")
    parser.add_argument("--after-fail", type=int, default=1, help="сколько ступеней пройти после первого нарушения")
    parser.add_argument("--label", default=None, help="метка серии (по умолчанию — имя сценария)")
    parser.add_argument("--base-url", default=f"http://localhost:{os.getenv('APP_PORT', '8080')}")
    parser.add_argument("--docker-k6", action="store_true", help="запускать k6 в контейнере grafana/k6")
    args = parser.parse_args()

    label = args.label or args.scenario
    OUT.mkdir(parents=True, exist_ok=True)
    app = find_app_process()
    monitor = Monitor(app, OUT / f"{label}_resources.csv")
    monitor.start()
    time.sleep(3)
    t0 = time.time() - 3
    steps, fails_left = [], None
    print(f"Серия «{label}»: процесс сервиса PID {app.pid}, ступени {args.rates} по {args.duration}\n")
    for rate in [int(r) for r in args.rates.split(",")]:
        wait_idle(monitor)
        out = f"results/load/{label}_{rate}.json"
        start = time.time() - t0
        code = subprocess.run(k6_command(args, rate, out), cwd=ROOT).returncode
        steps.append({"rate": rate, "start": round(start, 1), "end": round(time.time() - t0, 1),
                      "passed": code == 0, "file": out})
        if code not in (0, 99):
            print(f"k6 завершился с кодом {code}")
        if code == 99 and fails_left is None:
            fails_left = args.after_fail
        elif fails_left is not None:
            fails_left -= 1
        if fails_left == 0:
            break
    wait_idle(monitor)
    time.sleep(2)
    monitor.stop_event.set()
    monitor.join()
    (OUT / f"{label}_steps.json").write_text(json.dumps(steps, ensure_ascii=False, indent=1))
    print(f"\nГотово: results/load/{label}_steps.json, results/load/{label}_resources.csv")


if __name__ == "__main__":
    main()
