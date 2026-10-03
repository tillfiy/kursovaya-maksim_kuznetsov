SET search_path TO maksim_kuznetsov;
SELECT 'users' AS "таблица", count(*) AS "записей" FROM users
UNION ALL SELECT 'categories', count(*) FROM categories
UNION ALL SELECT 'tickets', count(*) FROM tickets
UNION ALL SELECT 'comments', count(*) FROM comments;
