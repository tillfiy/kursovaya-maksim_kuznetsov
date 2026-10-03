"""Тесты операций работают с отдельной схемой maksim_kuznetsov_test:
она создаётся и наполняется малым объёмом автоматически, рабочие данные не затрагиваются."""

import os

os.environ["DB_SCHEMA"] = "maksim_kuznetsov_test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from scripts.init_db import apply_schema  # noqa: E402
from scripts.seed import seed  # noqa: E402

TEST_SCHEMA = os.environ["DB_SCHEMA"]


@pytest.fixture(scope="session", autouse=True)
def test_database():
    apply_schema(TEST_SCHEMA)
    seed("small", TEST_SCHEMA, verbose=False)
    yield


def _login(client, login, password):
    r = client.post("/api/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200
    client.headers["Authorization"] = f"Bearer {r.json()['token']}"
    client.cookies.clear()
    return client


@pytest.fixture(scope="session")
def client(test_database):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def anon(client):
    client.headers.pop("Authorization", None)
    client.cookies.clear()
    return client


@pytest.fixture
def staff(client):
    return _login(client, "demo", "demo")


@pytest.fixture
def customer(client):
    return _login(client, "client", "client")
