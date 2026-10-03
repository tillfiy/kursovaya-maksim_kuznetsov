"""Операции программного интерфейса: коды ответа, состав полей, авторизация, неверные параметры."""

TICKET_FIELDS = {"id", "title", "status", "created_at", "closed_at", "category", "author",
                 "first_reply_at", "reaction_minutes", "norm_minutes", "norm_violated"}


def test_list_requires_authorization(anon):
    assert anon.get("/api/tickets").status_code == 401


def test_login_with_wrong_password_is_rejected(anon):
    r = anon.post("/api/auth/login", json={"login": "demo", "password": "wrong"})
    assert r.status_code == 401


def test_me_returns_current_user(staff):
    r = staff.get("/api/me")
    assert r.status_code == 200
    assert r.json()["login"] == "demo" and r.json()["role"] == "staff"


def test_list_returns_requested_page(staff):
    r = staff.get("/api/tickets?page=1&size=20")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 20
    assert body["total"] >= 300
    assert TICKET_FIELDS | {"comments_count"} <= set(body["items"][0])


def test_list_rejects_invalid_page_size(staff):
    assert staff.get("/api/tickets?size=1000").status_code == 422
    assert staff.get("/api/tickets?page=0").status_code == 422
    assert staff.get("/api/tickets?status=unknown").status_code == 422


def test_list_filters_by_status_and_category(staff):
    r = staff.get("/api/tickets?status=closed&category_id=2&size=100")
    items = r.json()["items"]
    assert items and all(t["status"] == "closed" and t["category"]["id"] == 2 for t in items)


def test_client_sees_only_own_tickets(customer):
    items = customer.get("/api/tickets?size=100").json()["items"]
    assert all(t["author"]["id"] == 2 for t in items)


def test_ticket_card_contains_comments_and_reaction(staff):
    r = staff.get("/api/tickets/147")
    assert r.status_code == 200
    body = r.json()
    assert TICKET_FIELDS | {"body", "comments"} <= set(body)
    assert isinstance(body["comments"], list)


def test_ticket_card_not_found(staff):
    assert staff.get("/api/tickets/999999").status_code == 404


def test_create_ticket_and_unknown_category(staff):
    r = staff.post("/api/tickets", json={"title": "Тест", "body": "Описание", "category_id": 1})
    assert r.status_code == 201
    assert r.json()["status"] == "new" and r.json()["first_reply_at"] is None
    r = staff.post("/api/tickets", json={"title": "Тест", "body": "Описание", "category_id": 999})
    assert r.status_code == 404
    r = staff.post("/api/tickets", json={"title": "", "body": "Описание", "category_id": 1})
    assert r.status_code == 422


def test_staff_reply_moves_new_ticket_to_work(staff):
    ticket_id = staff.post("/api/tickets", json={"title": "Т", "body": "О", "category_id": 1}).json()["id"]
    r = staff.post(f"/api/tickets/{ticket_id}/comments", json={"body": "Взяли в работу"})
    assert r.status_code == 201
    card = staff.get(f"/api/tickets/{ticket_id}").json()
    assert card["status"] == "in_progress"
    assert card["first_reply_at"] is not None


def test_status_transitions_and_closed_ticket(staff):
    ticket_id = staff.post("/api/tickets", json={"title": "Т", "body": "О", "category_id": 1}).json()["id"]
    assert staff.patch(f"/api/tickets/{ticket_id}/status", json={"status": "closed"}).status_code == 200
    assert staff.patch(f"/api/tickets/{ticket_id}/status", json={"status": "new"}).status_code == 409
    assert staff.post(f"/api/tickets/{ticket_id}/comments", json={"body": "x"}).status_code == 409


def test_client_cannot_change_status_or_open_foreign_ticket(customer):
    assert customer.patch("/api/tickets/1/status", json={"status": "closed"}).status_code == 403
    foreign = next(i for i in range(1, 301) if customer.get(f"/api/tickets/{i}").status_code == 403)
    assert foreign


def test_summary_has_totals_by_category(staff):
    r = staff.get("/api/summary")
    assert r.status_code == 200
    body = r.json()
    assert len(body["categories"]) == 5
    assert {"total", "open", "open_violated", "violated_share"} <= set(body["totals"])
    assert body["totals"]["open"] == sum(c["open"] for c in body["categories"])


def test_ticket_card_reaction_matches_first_staff_comment(staff):
    body = staff.get("/api/tickets/147").json()
    staff_comments = [c["created_at"] for c in body["comments"] if c["author_role"] == "staff"]
    assert body["first_reply_at"] == (staff_comments[0] if staff_comments else None)
