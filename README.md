# Сервис учёта заявок в службу поддержки

Принимает заявки пользователей по категориям, ведёт их по статусам (новая → в работе → закрыта),
хранит переписку комментариями и считает срок реакции — время от создания заявки до первого ответа
сотрудника — со сравнением с нормативом категории. Учебный сервис курсовой работы по дисциплине
«Оптимизация клиент-серверных приложений», вариант 2, префикс `maksim_kuznetsov`.

## Требования

- Python 3.14 (проверено на 3.14.7);
- PostgreSQL 16 (поднимается в Docker, проверено на Docker 29.8 / Docker Compose v2);
- зависимости Python — в `requirements.txt` (FastAPI 0.142, Uvicorn 0.54, psycopg 3.3, pytest 9.1).

## Установка и запуск

    git clone <адрес репозитория>
    cd kursovaya
    cp .env.example .env
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    docker compose up -d
    python -m scripts.init_db
    python -m scripts.seed --size small
    uvicorn app.main:app --port 8080

Рабочее наполнение (100 000 заявок, около 300 000 комментариев) вместо малого:

    python -m scripts.seed --size work

Наполнение воспроизводимо: таблицы очищаются, генератор использует фиксированное зерно и
фиксированную начальную дату, поэтому повторный запуск даёт те же данные.

Число записей по таблицам:

    docker compose exec -T db psql -U maksim_kuznetsov -d maksim_kuznetsov < scripts/counts.sql

## Переменные окружения

| Переменная   | Назначение                       | Пример                                                                   |
|--------------|----------------------------------|--------------------------------------------------------------------------|
| DATABASE_URL | подключение к базе данных        | postgresql://maksim_kuznetsov:changeme@localhost:5544/maksim_kuznetsov  |
| DB_SCHEMA    | схема с таблицами сервиса        | maksim_kuznetsov                                                         |
| SECRET_KEY   | ключ подписи токенов доступа     | changeme                                                                 |
| APP_PORT     | порт сервиса (для скрипта замеров) | 8080                                                                   |
| DB_POOL_MAX  | наибольшее число соединений в пуле | 10                                                                   |
| DB_POOL_TIMEOUT | сколько секунд ждать свободного соединения, затем 503 | 5                                             |

## Проверка работоспособности

Интерфейс открывается по адресу http://localhost:8080. Учётные записи:
`demo` / `demo` — сотрудник (видит все заявки, меняет статусы; под ней снимаются замеры),
`client` / `client` — клиент (видит только свои заявки). На главной странице — список заявок
с фильтром и постраничным выводом; из него открывается карточка заявки; вкладка «Сводка» —
итоговые показатели по всем данным.

Описание API в формате OpenAPI: http://localhost:8080/docs

## Тесты

    python -m pytest

Тесты бизнес-правил (`tests/test_rules.py`) работают без базы данных. Тесты операций
(`tests/test_api.py`) сами создают отдельную схему `maksim_kuznetsov_test` и наполняют её малым
объёмом — нужен только запущенный контейнер с базой (`docker compose up -d`).

## Замеры

Сервис должен быть запущен. Замер на текущем наполнении (прогрев 5, повторов 30, учётная запись demo):

    python -m scripts.bench --label small
    python -m scripts.bench --label work
    python -m scripts.compare

Каждый ответ сервиса содержит заголовки: `X-App-Time-Ms` — время обработки запроса сервером,
`X-DB-Time-Ms` — суммарное время запросов к базе данных, `X-DB-Queries` — число запросов к базе.

## Нагрузочный тест (ДЗ 2)

Тест на k6 — каталог [load/](load/), файл `load/test.js`. Модель нагрузки открытая (executor
`constant-arrival-rate`): частота в запросах в секунду и длительность ступени задаются параметрами
запуска. Два сценария: `mixed` — операции по весам профиля нагрузки, `heavy` — только самая тяжёлая
операция (поиск по заявкам, `GET /api/tickets?q=...`). Вход выполняется один раз в `setup()` и в
результаты не попадает. Порог записан в тесте: p95 < 500 мс и доля ошибок < 1 %. Ответ 409
(недопустимый переход статуса, комментарий к закрытой заявке) — отказ по правилам варианта, а не ошибка.

Установка k6 (macOS, Apple Silicon):

    curl -LO https://github.com/grafana/k6/releases/download/v2.3.0/k6-v2.3.0-macos-arm64.zip
    unzip k6-v2.3.0-macos-arm64.zip && sudo mv k6-v2.3.0-macos-arm64/k6 /usr/local/bin/

Для испытаний сервис запускается в контейнере рядом с базой (как стенд лабораторных работ 3–4):
образ собирается из Dockerfile, в нём есть py-spy, контейнеру выдано право SYS_PTRACE.

    docker compose up -d --build api

Одна ступень вручную (база наполнена рабочим объёмом):

    k6 run -e SCENARIO=mixed -e RATE=8 -e DURATION=30s load/test.js

Серия ступеней с записью ресурсов (процессор и память контейнеров приложения и базы — docker stats,
соединения с БД — pg_stat_activity) и отчёт по ней:

    python -m scripts.seed --size work
    python -m scripts.load_series --scenario mixed --rates 2,4,8,16,32,64
    python -m scripts.load_report mixed

Перед каждой серией база наполняется заново: операции записи добавляют данные.

Профиль под нагрузкой — py-spy внутри контейнера (процесс сервиса — PID 1):

    docker compose exec api py-spy dump --pid 1
    docker compose exec api py-spy record --pid 1 --duration 20 --idle --function --output /tmp/profile.svg
    docker compose exec api py-spy record --pid 1 --duration 20 --idle --function --format raw --output /tmp/profile.txt
    docker compose cp api:/tmp/profile.txt results/load/profile_heavy.txt
    python -m scripts.profile_report heavy

Размер пула соединений и время ожидания соединения задаются переменными `DB_POOL_MAX` (10) и
`DB_POOL_TIMEOUT` (секунды), для контейнера — так: `DB_POOL_MAX=20 docker compose up -d api`.

## Программный интерфейс

Все операции, кроме входа, требуют авторизации: заголовок `Authorization: Bearer <token>`
или кука `token`, которую ставит вход. Тела запросов и ответов — JSON.

| Метод и путь                    | Параметры                                                                 | Ответ                                                                                   | Ошибки             |
|---------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|--------------------|
| POST /api/auth/login            | login, password                                                           | 200 {"token", "user"} и кука token                                                      | 401, 422           |
| POST /api/auth/logout           | —                                                                         | 204, кука удаляется                                                                     | —                  |
| GET /api/me                     | —                                                                         | 200 {"id", "login", "full_name", "role"}                                                | 401                |
| GET /api/categories             | —                                                                         | 200 [{"id", "name", "norm_minutes"}]                                                    | 401                |
| GET /api/tickets                | page ≥ 1 (1), size 1–100 (20), status (new / in_progress / closed), category_id, q (поиск по теме) | 200 {"items": [заявка + comments_count], "total", "page", "size"}; клиент видит только свои | 401, 422 |
| GET /api/tickets/{id}           | —                                                                         | 200 заявка + body, comments: [{"id", "body", "created_at", "author_name", "author_role"}] | 401, 403, 404 |
| POST /api/tickets               | title (1–200 симв.), body, category_id                                    | 201 созданная заявка со статусом new                                                    | 401, 404, 422      |
| POST /api/tickets/{id}/comments | body                                                                      | 201 комментарий; первый ответ сотрудника переводит новую заявку в работу                | 401, 403, 404, 409, 422 |
| PATCH /api/tickets/{id}/status  | status: in_progress / closed (только вперёд)                              | 200 заявка с новым статусом; только сотрудник                                           | 401, 403, 404, 409, 422 |
| GET /api/summary                | —                                                                         | 200 {"categories": [{"name", "norm_minutes", "total", "open", "open_violated", "violated_share"}], "totals"} | 401 |

Поля заявки: `id, title, status, created_at, closed_at, category {id, name}, author {id, full_name},
first_reply_at, reaction_minutes, norm_minutes, norm_violated`. Срок реакции — минуты от создания до
первого комментария сотрудника; пока ответа нет, отсчёт идёт до текущего момента (для закрытой заявки
без ответа — до закрытия). Норматив нарушен, если срок реакции больше норматива категории.

Коды ошибок: 401 — нет или неверная авторизация; 403 — заявка чужая (для клиента) или операция
только для сотрудника; 404 — заявка или категория не найдена; 409 — недопустимый переход статуса
или комментарий к закрытой заявке; 422 — неверные параметры; 503 — сервис перегружен (все соединения
с базой заняты дольше `DB_POOL_TIMEOUT`), в ответе заголовок `Retry-After`.
