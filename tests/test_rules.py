"""Бизнес-правила варианта 2 на подготовленных данных, без обращения к сервису."""

from datetime import datetime, timedelta, timezone

from app.rules import can_transition, is_norm_violated, reaction_minutes, summarize

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)


def test_reaction_is_time_until_first_staff_reply():
    assert reaction_minutes(T0, T0 + timedelta(minutes=45), now=T0 + timedelta(days=1)) == 45


def test_reaction_without_reply_keeps_running_until_now():
    assert reaction_minutes(T0, None, now=T0 + timedelta(hours=3)) == 180


def test_norm_violated_when_reaction_exceeds_norm():
    assert is_norm_violated(T0, T0 + timedelta(minutes=61), norm_minutes=60, now=T0)


def test_norm_not_violated_on_boundary():
    assert not is_norm_violated(T0, T0 + timedelta(minutes=60), norm_minutes=60, now=T0)


def test_unanswered_ticket_violates_norm_after_deadline():
    assert is_norm_violated(T0, None, norm_minutes=60, now=T0 + timedelta(minutes=90))


def test_status_moves_only_forward():
    assert can_transition("new", "in_progress")
    assert can_transition("in_progress", "closed")
    assert not can_transition("in_progress", "new")
    assert not can_transition("closed", "in_progress")


def test_summary_counts_open_tickets_and_violations_by_category():
    categories = [{"id": 1, "name": "Сеть", "norm_minutes": 60},
                  {"id": 2, "name": "Почта", "norm_minutes": 120}]
    tickets = [
        {"id": 1, "category_id": 1, "status": "new", "created_at": T0},          # без ответа 5 ч -> нарушен
        {"id": 2, "category_id": 1, "status": "in_progress", "created_at": T0},  # ответ за 30 мин
        {"id": 3, "category_id": 1, "status": "closed", "created_at": T0},       # закрыта, в открытые не входит
        {"id": 4, "category_id": 2, "status": "in_progress", "created_at": T0},  # ответ за 200 мин -> нарушен
    ]
    replies = {2: T0 + timedelta(minutes=30), 3: T0 + timedelta(minutes=500),
               4: T0 + timedelta(minutes=200)}
    result = summarize(categories, tickets, replies, now=T0 + timedelta(hours=5))
    net, mail = result["categories"]
    assert (net["total"], net["open"], net["open_violated"], net["violated_share"]) == (3, 2, 1, 0.5)
    assert (mail["open"], mail["open_violated"], mail["violated_share"]) == (1, 1, 1.0)
    assert result["totals"] == {"total": 4, "open": 3, "open_violated": 2, "violated_share": 0.6667}
