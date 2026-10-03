import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import auth, db, repo, rules

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app):
    db.open_pool()
    yield
    db.close_pool()


class TimingMiddleware:
    """Добавляет в ответ время обработки и сведения об обращениях к базе:
    X-App-Time-Ms — время обработки запроса сервером целиком,
    X-DB-Time-Ms — суммарное время запросов к базе,
    X-DB-Queries — число запросов к базе.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        stats = db.Stats()
        token = db.current_stats.set(stats)
        started = time.perf_counter()

        async def send_with_timing(message):
            if message["type"] == "http.response.start":
                total_ms = (time.perf_counter() - started) * 1000
                # ДЗ 1: кеширование любого уровня, включая клиентское, не применяется.
                headers = [(k, v) for k, v in message.get("headers", []) if k not in (b"etag", b"last-modified")]
                headers += [
                    (b"cache-control", b"no-store"),
                    (b"x-app-time-ms", f"{total_ms:.2f}".encode()),
                    (b"x-db-time-ms", f"{stats.db_ms:.2f}".encode()),
                    (b"x-db-queries", str(stats.queries).encode()),
                ]
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            db.current_stats.reset(token)


app = FastAPI(title="Служба поддержки — maksim_kuznetsov", lifespan=lifespan)
app.add_middleware(TimingMiddleware)


def now() -> datetime:
    return datetime.now(timezone.utc)


class LoginIn(BaseModel):
    login: str
    password: str


class TicketIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    category_id: int


class CommentIn(BaseModel):
    body: str = Field(min_length=1)


class StatusIn(BaseModel):
    status: Literal["new", "in_progress", "closed"]


def ticket_out(ticket: dict, first_reply_at, moment: datetime) -> dict:
    return {
        "id": ticket["id"],
        "title": ticket["title"],
        "status": ticket["status"],
        "created_at": ticket["created_at"],
        "closed_at": ticket["closed_at"],
        "category": {"id": ticket["category_id"], "name": ticket["category_name"]},
        "author": {"id": ticket["author_id"], "full_name": ticket["author_name"]},
        **rules.reaction_info(ticket, first_reply_at, moment),
    }


def load_ticket_for(conn, ticket_id: int, user: dict) -> dict:
    ticket = repo.get_ticket(conn, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if user["role"] == "client" and ticket["author_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Нет доступа к заявке")
    return ticket


# ---------- авторизация ----------

@app.post("/api/auth/login")
def login(data: LoginIn, response: Response, conn=Depends(db.get_conn)):
    user = conn.execute(
        "SELECT id, login, full_name, role, password_hash FROM users WHERE login = %s",
        (data.login,),
    ).fetchone()
    if user is None or not auth.verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    token = auth.make_token(user["id"])
    response.set_cookie("token", token, httponly=True, samesite="lax")
    del user["password_hash"]
    return {"token": token, "user": user}


@app.post("/api/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie("token")


@app.get("/api/me")
def me(user=Depends(auth.current_user)):
    return user


# ---------- справочники ----------

@app.get("/api/categories")
def categories(user=Depends(auth.current_user), conn=Depends(db.get_conn)):
    return repo.list_categories(conn)


# ---------- заявки ----------

@app.get("/api/tickets")
def list_tickets(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status: Literal["new", "in_progress", "closed"] | None = None,
    category_id: int | None = None,
    q: str | None = Query(None, max_length=100),
    user=Depends(auth.current_user),
    conn=Depends(db.get_conn),
):
    author_id = user["id"] if user["role"] == "client" else None
    total = repo.count_tickets(conn, author_id, status, category_id, q)
    rows = repo.list_tickets(conn, size, (page - 1) * size, author_id, status, category_id, q)
    moment = now()
    items = []
    for row in rows:
        item = ticket_out(row, repo.first_staff_reply(conn, row["id"]), moment)
        item["comments_count"] = repo.count_comments(conn, row["id"])
        items.append(item)
    return {"items": items, "total": total, "page": page, "size": size}


@app.get("/api/tickets/{ticket_id}")
def get_ticket(ticket_id: int, user=Depends(auth.current_user), conn=Depends(db.get_conn)):
    ticket = load_ticket_for(conn, ticket_id, user)
    comments = repo.list_comments(conn, ticket_id)
    # Первый ответ сотрудника берётся из уже загруженной переписки (комментарии упорядочены по времени).
    first_reply_at = next((c["created_at"] for c in comments if c["author_role"] == "staff"), None)
    result = ticket_out(ticket, first_reply_at, now())
    result["body"] = ticket["body"]
    result["comments"] = comments
    return result


@app.post("/api/tickets", status_code=201)
def create_ticket(data: TicketIn, user=Depends(auth.current_user), conn=Depends(db.get_conn)):
    if repo.get_category(conn, data.category_id) is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    ticket_id = repo.create_ticket(conn, data.title, data.body, data.category_id, user["id"])
    return ticket_out(repo.get_ticket(conn, ticket_id), None, now())


@app.post("/api/tickets/{ticket_id}/comments", status_code=201)
def add_comment(ticket_id: int, data: CommentIn,
                user=Depends(auth.current_user), conn=Depends(db.get_conn)):
    ticket = load_ticket_for(conn, ticket_id, user)
    if ticket["status"] == "closed":
        raise HTTPException(status_code=409, detail="Заявка закрыта")
    comment = repo.create_comment(conn, ticket_id, user["id"], data.body)
    # Первый ответ сотрудника переводит новую заявку в работу.
    if user["role"] == "staff" and ticket["status"] == "new":
        repo.set_status(conn, ticket_id, "in_progress")
    return {**comment, "author_name": user["full_name"], "author_role": user["role"]}


@app.patch("/api/tickets/{ticket_id}/status")
def change_status(ticket_id: int, data: StatusIn,
                  user=Depends(auth.current_user), conn=Depends(db.get_conn)):
    if user["role"] != "staff":
        raise HTTPException(status_code=403, detail="Статус меняет только сотрудник")
    ticket = load_ticket_for(conn, ticket_id, user)
    if not rules.can_transition(ticket["status"], data.status):
        raise HTTPException(
            status_code=409,
            detail=f"Переход {ticket['status']} -> {data.status} недопустим",
        )
    repo.set_status(conn, ticket_id, data.status)
    updated = repo.get_ticket(conn, ticket_id)
    return ticket_out(updated, repo.first_staff_reply(conn, ticket_id), now())


# ---------- сводка ----------

@app.get("/api/summary")
def summary(user=Depends(auth.current_user), conn=Depends(db.get_conn)):
    categories = repo.list_categories(conn)
    tickets = repo.all_tickets_for_summary(conn)
    first_replies = {}
    for reply in repo.all_staff_replies(conn):
        known = first_replies.get(reply["ticket_id"])
        if known is None or reply["created_at"] < known:
            first_replies[reply["ticket_id"]] = reply["created_at"]
    return rules.summarize(categories, tickets, first_replies, now())


# ---------- клиентская часть ----------

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
