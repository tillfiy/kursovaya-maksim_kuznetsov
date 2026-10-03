"""Авторизация: пароль в виде PBKDF2, токен доступа с подписью HMAC.

Токен передаётся заголовком Authorization: Bearer <токен> или кукой token
(её ставит POST /api/auth/login для браузерного интерфейса).
"""

import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request

from app import config
from app.db import get_conn

ITERATIONS = 100_000


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return f"pbkdf2${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, _ = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def _sign(payload: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(user_id: int) -> str:
    payload = f"{user_id}.{int(time.time()) + config.TOKEN_TTL_SECONDS}"
    return f"{payload}.{_sign(payload)}"


def parse_token(token: str) -> int | None:
    try:
        user_id, expires, signature = token.split(".")
    except ValueError:
        return None
    if not hmac.compare_digest(_sign(f"{user_id}.{expires}"), signature):
        return None
    if int(expires) < time.time():
        return None
    return int(user_id)


def current_user(request: Request, conn=Depends(get_conn)) -> dict:
    token = None
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    if not token:
        token = request.cookies.get("token")
    user_id = parse_token(token) if token else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    user = conn.execute(
        "SELECT id, login, full_name, role FROM users WHERE id = %s", (user_id,)
    ).fetchone()
    if user is None:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    return user
