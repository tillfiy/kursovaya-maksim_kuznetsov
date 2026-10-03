"""Наполнение базы данных. Воспроизводимо: фиксированное зерно генератора и
фиксированная начальная дата, перед наполнением таблицы очищаются.

    python -m scripts.seed --size small   # малое наполнение
    python -m scripts.seed --size work    # рабочее наполнение

Учётные записи: demo / demo (сотрудник, под ней снимаются замеры),
client / client (клиент). У остальных пользователей пароль тоже demo.
"""

import argparse
import random
import time
from datetime import datetime, timedelta, timezone

import psycopg

from app import config
from app.auth import hash_password

SIZES = {
    "small": {"users": 50, "categories": 5, "tickets": 300},
    "work": {"users": 3_000, "categories": 10, "tickets": 100_000},
}

CATEGORIES = [
    ("Доступ и учётные записи", 60),
    ("Оборудование", 240),
    ("Принтеры и печать", 480),
    ("Электронная почта", 120),
    ("Сеть и VPN", 60),
    ("Программное обеспечение", 480),
    ("Телефония", 240),
    ("Бухгалтерские системы", 120),
    ("Закупки", 1440),
    ("Прочее", 1440),
]

FIRST_NAMES = ["Иван", "Пётр", "Анна", "Мария", "Олег", "Елена", "Сергей", "Ольга",
               "Дмитрий", "Наталья", "Алексей", "Татьяна", "Андрей", "Ирина", "Павел"]
LAST_NAMES = ["Смирнов", "Иванов", "Кузнецов", "Попов", "Васильев", "Петров", "Соколов",
              "Михайлов", "Новиков", "Фёдоров", "Морозов", "Волков", "Алексеев", "Лебедев"]

PROBLEMS = ["Не работает", "Сломался", "Не открывается", "Ошибка в", "Нужен доступ к",
            "Медленно работает", "Не печатает", "Пропал", "Требуется настроить", "Зависает"]
OBJECTS = ["принтер", "ноутбук", "почта", "VPN", "1С", "монитор", "телефон",
           "общая папка", "браузер", "сканер", "пропуск", "корпоративный портал"]

CLIENT_PHRASES = ["Проблема повторяется", "Прикладываю описание", "Есть новости?",
                  "Уточняю детали", "Спасибо"]
STAFF_PHRASES = ["Взяли в работу", "Проверяем", "Перезагрузите, пожалуйста, устройство",
                 "Исправлено, проверьте", "Нужны дополнительные сведения"]

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
PERIOD_MINUTES = 270 * 24 * 60
SEED = 2026


def generate(size: str):
    cfg = SIZES[size]
    rng = random.Random(SEED)
    password = hash_password("demo", salt="seed")

    users = [("demo", password, "Демо Сотрудник", "staff"),
             ("client", hash_password("client", salt="seed"), "Демо Клиент", "client")]
    staff_count = max(2, cfg["users"] // 10)
    for i in range(3, cfg["users"] + 1):
        role = "staff" if i <= staff_count else "client"
        name = f"{rng.choice(LAST_NAMES)} {rng.choice(FIRST_NAMES)}"
        users.append((f"user{i}", password, name, role))
    staff_ids = [i for i, u in enumerate(users, start=1) if u[3] == "staff"]
    client_ids = [i for i, u in enumerate(users, start=1) if u[3] == "client"]

    categories = CATEGORIES[: cfg["categories"]]

    tickets, comments = [], []
    for ticket_id in range(1, cfg["tickets"] + 1):
        category_id = rng.randint(1, len(categories))
        norm = categories[category_id - 1][1]
        author_id = rng.choice(client_ids)
        created = BASE_TIME + timedelta(minutes=rng.randint(0, PERIOD_MINUTES))
        status = rng.choices(["new", "in_progress", "closed"], weights=[20, 25, 55])[0]
        title = f"{rng.choice(PROBLEMS)} {rng.choice(OBJECTS)}"
        body = f"{title}. Обращение №{ticket_id}, прошу помочь."

        moment = created
        if status == "new":
            # Сотрудник ещё не ответил, пишет только автор.
            for _ in range(rng.randint(0, 2)):
                moment += timedelta(minutes=rng.randint(5, 600))
                comments.append((ticket_id, author_id, rng.choice(CLIENT_PHRASES), moment))
        else:
            # Срок первого ответа разбросан вокруг норматива: часть заявок его нарушает.
            moment += timedelta(minutes=max(1, int(norm * rng.lognormvariate(-0.4, 0.6))))
            staff_id = rng.choice(staff_ids)
            comments.append((ticket_id, staff_id, rng.choice(STAFF_PHRASES), moment))
            for _ in range(rng.randint(1, 4)):
                moment += timedelta(minutes=rng.randint(5, 600))
                if rng.random() < 0.5:
                    comments.append((ticket_id, author_id, rng.choice(CLIENT_PHRASES), moment))
                else:
                    comments.append((ticket_id, staff_id, rng.choice(STAFF_PHRASES), moment))
        closed_at = moment + timedelta(minutes=rng.randint(10, 600)) if status == "closed" else None
        tickets.append((title, body, category_id, author_id, status, created, closed_at))

    return users, categories, tickets, comments


def seed(size: str, schema: str = config.DB_SCHEMA, verbose: bool = True):
    started = time.perf_counter()
    users, categories, tickets, comments = generate(size)
    with psycopg.connect(config.DATABASE_URL, options=f"-c search_path={schema}") as conn:
        conn.execute("TRUNCATE comments, tickets, categories, users RESTART IDENTITY CASCADE")
        with conn.cursor() as cur:
            with cur.copy("COPY users (login, password_hash, full_name, role) FROM STDIN") as cp:
                for row in users:
                    cp.write_row(row)
            with cur.copy("COPY categories (name, norm_minutes) FROM STDIN") as cp:
                for row in categories:
                    cp.write_row(row)
            with cur.copy("COPY tickets (title, body, category_id, author_id, status, created_at, closed_at) "
                          "FROM STDIN") as cp:
                for row in tickets:
                    cp.write_row(row)
            with cur.copy("COPY comments (ticket_id, author_id, body, created_at) FROM STDIN") as cp:
                for row in comments:
                    cp.write_row(row)
        conn.execute("ANALYZE")
    if verbose:
        print(f"Наполнение {size} в схеме {schema}: users={len(users)}, categories={len(categories)}, "
              f"tickets={len(tickets)}, comments={len(comments)} "
              f"за {time.perf_counter() - started:.1f} с")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--size", choices=SIZES, required=True)
    parser.add_argument("--schema", default=config.DB_SCHEMA)
    args = parser.parse_args()
    seed(args.size, args.schema)


if __name__ == "__main__":
    main()
