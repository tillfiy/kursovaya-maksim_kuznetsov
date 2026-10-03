"""Обращения к базе данных."""

TICKET_COLUMNS = """
    t.id, t.title, t.body, t.status, t.created_at, t.closed_at,
    t.category_id, c.name AS category_name, c.norm_minutes,
    t.author_id, u.full_name AS author_name
"""

TICKET_FROM = """
    FROM tickets t
    JOIN categories c ON c.id = t.category_id
    JOIN users u ON u.id = t.author_id
"""


def list_categories(conn):
    return conn.execute("SELECT id, name, norm_minutes FROM categories ORDER BY id").fetchall()


def get_category(conn, category_id):
    return conn.execute(
        "SELECT id, name, norm_minutes FROM categories WHERE id = %s", (category_id,)
    ).fetchone()


def _ticket_filter(author_id, status, category_id, q):
    where, params = [], []
    if author_id is not None:
        where.append("t.author_id = %s")
        params.append(author_id)
    if status is not None:
        where.append("t.status = %s")
        params.append(status)
    if category_id is not None:
        where.append("t.category_id = %s")
        params.append(category_id)
    if q:
        where.append("t.title ILIKE %s")
        params.append(f"%{q}%")
    return ("WHERE " + " AND ".join(where)) if where else "", params


def count_tickets(conn, author_id=None, status=None, category_id=None, q=None):
    where, params = _ticket_filter(author_id, status, category_id, q)
    return conn.execute(f"SELECT count(*) AS n FROM tickets t {where}", params).fetchone()["n"]


def list_tickets(conn, limit, offset, author_id=None, status=None, category_id=None, q=None):
    where, params = _ticket_filter(author_id, status, category_id, q)
    return conn.execute(
        f"SELECT {TICKET_COLUMNS} {TICKET_FROM} {where} "
        "ORDER BY t.created_at DESC, t.id DESC LIMIT %s OFFSET %s",
        [*params, limit, offset],
    ).fetchall()


def get_ticket(conn, ticket_id):
    return conn.execute(
        f"SELECT {TICKET_COLUMNS} {TICKET_FROM} WHERE t.id = %s", (ticket_id,)
    ).fetchone()


def first_staff_reply(conn, ticket_id):
    """Время первого ответа сотрудника по заявке (None, если ответа не было)."""
    return conn.execute(
        """
        SELECT min(cm.created_at) AS first_reply_at
        FROM comments cm JOIN users u ON u.id = cm.author_id
        WHERE cm.ticket_id = %s AND u.role = 'staff'
        """,
        (ticket_id,),
    ).fetchone()["first_reply_at"]


def count_comments(conn, ticket_id):
    return conn.execute(
        "SELECT count(*) AS n FROM comments WHERE ticket_id = %s", (ticket_id,)
    ).fetchone()["n"]


def list_comments(conn, ticket_id):
    return conn.execute(
        """
        SELECT cm.id, cm.body, cm.created_at, cm.author_id,
               u.full_name AS author_name, u.role AS author_role
        FROM comments cm JOIN users u ON u.id = cm.author_id
        WHERE cm.ticket_id = %s
        ORDER BY cm.created_at, cm.id
        """,
        (ticket_id,),
    ).fetchall()


def create_ticket(conn, title, body, category_id, author_id):
    return conn.execute(
        """
        INSERT INTO tickets (title, body, category_id, author_id)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        (title, body, category_id, author_id),
    ).fetchone()["id"]


def create_comment(conn, ticket_id, author_id, body):
    return conn.execute(
        """
        INSERT INTO comments (ticket_id, author_id, body)
        VALUES (%s, %s, %s) RETURNING id, body, created_at, author_id
        """,
        (ticket_id, author_id, body),
    ).fetchone()


def set_status(conn, ticket_id, status):
    conn.execute(
        """
        UPDATE tickets
        SET status = %s, closed_at = CASE WHEN %s = 'closed' THEN now() ELSE NULL END
        WHERE id = %s
        """,
        (status, status, ticket_id),
    )


def all_tickets_for_summary(conn):
    return conn.execute("SELECT id, category_id, status, created_at FROM tickets").fetchall()


def all_staff_replies(conn):
    return conn.execute(
        """
        SELECT cm.ticket_id, cm.created_at
        FROM comments cm JOIN users u ON u.id = cm.author_id
        WHERE u.role = 'staff'
        """
    ).fetchall()
