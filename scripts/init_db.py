"""Создание схемы базы данных (пересоздаёт схему целиком).

    python -m scripts.init_db
"""

import argparse
from pathlib import Path

import psycopg

from app import config

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def apply_schema(schema: str):
    sql = SCHEMA_SQL.read_text(encoding="utf-8").replace("{schema}", schema)
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
        conn.execute(sql)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default=config.DB_SCHEMA)
    args = parser.parse_args()
    apply_schema(args.schema)
    print(f"Схема {args.schema} создана")


if __name__ == "__main__":
    main()
