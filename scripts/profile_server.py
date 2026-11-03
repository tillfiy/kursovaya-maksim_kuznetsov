"""Запуск сервиса со встроенным выборочным профилировщиком.

    python -m scripts.profile_server --delay 15 --duration 20

Сервис стартует как обычно (uvicorn app.main:app на порту APP_PORT). Через --delay
секунд профилировщик начинает с частотой --rate раз в секунду снимать стеки всех
потоков процесса (sys._current_frames) и делает это --duration секунд, после чего
пишет свёрнутые стеки в results/load/profile_<label>.txt (формат «стек;через;точку
число», как у py-spy --format raw). Разбор и флеймграф — scripts/profile_report.py.

Зачем не py-spy: на этом стенде Python 3.14 с python.org подписан с hardened runtime,
и macOS не даёт py-spy подключиться к процессу даже под sudo
(«Failed to open process ... Operation not permitted»). Встроенный профилировщик
работает внутри процесса и прав root не требует; метод тот же — выборка стеков.
"""

import argparse
import collections
import sys
import threading
import time
from pathlib import Path

import uvicorn

from app import config

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "load"


def short(path):
    """Путь к файлу кода: свой код — относительно репозитория, библиотеки — от site-packages."""
    p = str(path)
    if "site-packages/" in p:
        return p.split("site-packages/", 1)[1]
    root = str(ROOT) + "/"
    if p.startswith(root):
        return p[len(root):]
    if "lib/python3." in p:
        return p.split("lib/python3.", 1)[1].split("/", 1)[-1]
    return p


def frame_label(frame):
    code = frame.f_code
    return f"{code.co_name} ({short(code.co_filename)}:{code.co_firstlineno})"


def sampler(delay, duration, rate, out_path):
    time.sleep(delay)
    me = threading.get_ident()
    counts = collections.Counter()
    interval = 1.0 / rate
    snapshots = 0
    print(f"[profile] выборка стеков началась: {duration} с, {rate} раз/с", flush=True)
    deadline = time.perf_counter() + duration
    next_tick = time.perf_counter()
    while time.perf_counter() < deadline:
        for tid, frame in sys._current_frames().items():
            if tid == me:
                continue
            stack = []
            while frame is not None:
                stack.append(frame_label(frame))
                frame = frame.f_back
            counts[";".join(reversed(stack))] += 1
        snapshots += 1
        next_tick += interval
        time.sleep(max(0.0, next_tick - time.perf_counter()))
    with open(out_path, "w") as f:
        f.write(f"# snapshots={snapshots} rate={rate} duration={duration}\n")
        for stack, n in counts.most_common():
            f.write(f"{stack} {n}\n")
    print(f"[profile] готово: {snapshots} снимков, файл {out_path.relative_to(ROOT)}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--delay", type=float, default=15, help="через сколько секунд начать выборку")
    parser.add_argument("--duration", type=float, default=20, help="сколько секунд снимать (не меньше 10)")
    parser.add_argument("--rate", type=int, default=100, help="снимков в секунду")
    parser.add_argument("--label", default="heavy")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"profile_{args.label}.txt"
    threading.Thread(target=sampler, args=(args.delay, args.duration, args.rate, out_path), daemon=True).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=config.APP_PORT)


if __name__ == "__main__":
    main()
