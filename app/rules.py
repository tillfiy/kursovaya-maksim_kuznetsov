"""Бизнес-правила варианта 2: статусы заявки, срок реакции, норматив, сводка.

Функции не обращаются к базе данных и проверяются модульными тестами.
"""

from datetime import datetime

STATUSES = ("new", "in_progress", "closed")

# Заявка ведётся только вперёд: новая -> в работе -> закрыта.
# Новую можно закрыть сразу (например, дубликат); закрытая не переоткрывается.
TRANSITIONS = {
    "new": {"in_progress", "closed"},
    "in_progress": {"closed"},
    "closed": set(),
}


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, set())


def reaction_minutes(created_at: datetime, first_reply_at: datetime | None, now: datetime) -> float:
    """Срок реакции — время от создания заявки до первого ответа сотрудника.

    Пока ответа нет, срок продолжает идти: считается до момента now.
    """
    end = first_reply_at if first_reply_at is not None else now
    return max(0.0, (end - created_at).total_seconds() / 60)


def is_norm_violated(created_at: datetime, first_reply_at: datetime | None,
                     norm_minutes: int, now: datetime) -> bool:
    return reaction_minutes(created_at, first_reply_at, now) > norm_minutes


def reaction_info(ticket: dict, first_reply_at: datetime | None, now: datetime) -> dict:
    """Поля срока реакции для ответа API по одной заявке."""
    end = now if ticket["status"] != "closed" or ticket["closed_at"] is None else ticket["closed_at"]
    minutes = reaction_minutes(ticket["created_at"], first_reply_at, end)
    return {
        "first_reply_at": first_reply_at,
        "reaction_minutes": round(minutes, 1),
        "norm_minutes": ticket["norm_minutes"],
        "norm_violated": minutes > ticket["norm_minutes"],
    }


def summarize(categories: list[dict], tickets: list[dict],
              first_replies: dict[int, datetime], now: datetime) -> dict:
    """Сводка: число открытых заявок по категориям и доля открытых с нарушенным нормативом."""
    by_cat = {
        c["id"]: {
            "category_id": c["id"],
            "name": c["name"],
            "norm_minutes": c["norm_minutes"],
            "total": 0,
            "open": 0,
            "open_violated": 0,
        }
        for c in categories
    }
    for t in tickets:
        row = by_cat[t["category_id"]]
        row["total"] += 1
        if t["status"] == "closed":
            continue
        row["open"] += 1
        if is_norm_violated(t["created_at"], first_replies.get(t["id"]), row["norm_minutes"], now):
            row["open_violated"] += 1

    rows = list(by_cat.values())
    for row in rows:
        row["violated_share"] = round(row["open_violated"] / row["open"], 4) if row["open"] else 0.0

    total_open = sum(r["open"] for r in rows)
    total_violated = sum(r["open_violated"] for r in rows)
    return {
        "categories": rows,
        "totals": {
            "total": sum(r["total"] for r in rows),
            "open": total_open,
            "open_violated": total_violated,
            "violated_share": round(total_violated / total_open, 4) if total_open else 0.0,
        },
    }
