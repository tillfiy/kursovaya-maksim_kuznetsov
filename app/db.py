"""Пул соединений и учёт обращений к базе данных.

Каждый запрос к базе проходит через TimedCursor: он считает число запросов
и суммарное время их выполнения в рамках одного HTTP-запроса. Итог
выводится в заголовки ответа X-DB-Queries и X-DB-Time-Ms (см. TimingMiddleware).
"""

import contextvars
import time

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app import config


class Stats:
    __slots__ = ("queries", "db_ms")

    def __init__(self):
        self.queries = 0
        self.db_ms = 0.0


current_stats: contextvars.ContextVar[Stats | None] = contextvars.ContextVar("db_stats", default=None)


class TimedCursor(psycopg.Cursor):
    def execute(self, query, params=None, **kwargs):
        started = time.perf_counter()
        try:
            return super().execute(query, params, **kwargs)
        finally:
            stats = current_stats.get()
            if stats is not None:
                stats.queries += 1
                stats.db_ms += (time.perf_counter() - started) * 1000


_pool: ConnectionPool | None = None


def open_pool(schema: str = config.DB_SCHEMA) -> ConnectionPool:
    global _pool
    _pool = ConnectionPool(
        config.DATABASE_URL,
        min_size=2,
        max_size=10,
        kwargs={
            "cursor_factory": TimedCursor,
            "row_factory": dict_row,
            "options": f"-c search_path={schema}",
        },
        open=True,
    )
    return _pool


def close_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_conn():
    """Зависимость FastAPI: соединение на время обработки запроса."""
    with _pool.connection() as conn:
        yield conn
