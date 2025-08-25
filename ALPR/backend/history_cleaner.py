# -*- coding: utf-8 -*-
import argparse
import sqlite3
import os
import sys

def parse_args():
    p = argparse.ArgumentParser(description="Удаление дублей номеров в history за указанный интервал.")
    p.add_argument("--db", required=True, help="Путь к history.db")
    p.add_argument("--point", required=True, help="Имя точки (без \\in/\\out), например 'Ворота'")
    p.add_argument("--since", required=True, help="Начало интервала (YYYY-MM-DD HH:MM:SS)")
    p.add_argument("--until", required=True, help="Конец интервала (YYYY-MM-DD HH:MM:SS)")
    # режим: по умолчанию удаляем дубли по (plate, point_name) — оставляем самую раннюю запись
    return p.parse_args()

def main():
    args = parse_args()
    db_path = args.db
    point_base = args.point
    ts_from = args.since
    ts_to = args.until

    if not os.path.exists(db_path):
        print(f"[history_cleaner] DB not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Берем записи для point_name начинающихся с "point_base\"
    like_prefix = point_base + "\\%"
    c.execute("""
        SELECT id, timestamp, plate, point_name
        FROM history
        WHERE timestamp >= ? AND timestamp <= ?
          AND point_name LIKE ?
        ORDER BY timestamp ASC, id ASC
    """, (ts_from, ts_to, like_prefix))
    rows = c.fetchall()

    seen = set()           # (plate, point_name)
    to_delete = []

    for rid, ts, plate, pnt in rows:
        key = (plate, pnt)
        if key in seen:
            to_delete.append(rid)  # дубликат — удаляем
        else:
            seen.add(key)          # первую оставляем

    deleted = 0
    if to_delete:
        # Чистим батчами по 500 на всякий
        for i in range(0, len(to_delete), 500):
            chunk = to_delete[i:i+500]
            c.execute(f"DELETE FROM history WHERE id IN ({','.join('?'*len(chunk))})", chunk)
        conn.commit()
        deleted = len(to_delete)

    conn.close()
    print(f"[history_cleaner] point='{point_base}' window=[{ts_from}..{ts_to}] deleted={deleted}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
