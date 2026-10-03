-- Схема сервиса заявок. Имя схемы подставляется скриптом scripts/init_db.py.
-- По условиям ДЗ 1 индексов сверх первичных ключей нет.

DROP SCHEMA IF EXISTS {schema} CASCADE;
CREATE SCHEMA {schema};
SET search_path TO {schema};

CREATE TABLE users (
    id            serial PRIMARY KEY,
    login         text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    full_name     text NOT NULL,
    role          text NOT NULL CHECK (role IN ('client', 'staff'))
);

CREATE TABLE categories (
    id           serial PRIMARY KEY,
    name         text NOT NULL,
    norm_minutes integer NOT NULL CHECK (norm_minutes > 0)
);

CREATE TABLE tickets (
    id          serial PRIMARY KEY,
    title       text NOT NULL,
    body        text NOT NULL,
    category_id integer NOT NULL REFERENCES categories (id),
    author_id   integer NOT NULL REFERENCES users (id),
    status      text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'in_progress', 'closed')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    closed_at   timestamptz
);

CREATE TABLE comments (
    id         serial PRIMARY KEY,
    ticket_id  integer NOT NULL REFERENCES tickets (id),
    author_id  integer NOT NULL REFERENCES users (id),
    body       text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
