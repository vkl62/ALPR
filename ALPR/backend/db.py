# backend/db.py
from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Optional, Dict, Any, Tuple

from backend.config import DB_HISTORY_PATH, DB_PEOPLE_PATH
from backend.logger import log

# -----------------------
# Соединения с БД (ленивые, потокобезопасно)
# -----------------------

_history_conn_lock = threading.Lock()
_people_conn_lock = threading.Lock()
_history_conn: Optional[sqlite3.Connection] = None
_people_conn: Optional[sqlite3.Connection] = None


def _row_factory(cursor, row):
    return {d[0]: row[idx] for idx, d in enumerate(cursor.description)}


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = _row_factory
    # Немного прагм под запись событий
    with conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _get_history_conn() -> sqlite3.Connection:
    global _history_conn
    if _history_conn is None:
        with _history_conn_lock:
            if _history_conn is None:
                os.makedirs(os.path.dirname(DB_HISTORY_PATH) or ".", exist_ok=True)
                _history_conn = _connect(DB_HISTORY_PATH)
                _init_history_db(_history_conn)
    return _history_conn


def _get_people_conn() -> sqlite3.Connection:
    global _people_conn
    if _people_conn is None:
        with _people_conn_lock:
            if _people_conn is None:
                os.makedirs(os.path.dirname(DB_PEOPLE_PATH) or ".", exist_ok=True)
                _people_conn = _connect(DB_PEOPLE_PATH)
                _init_people_db(_people_conn)
    return _people_conn


# -----------------------
# Схемы и миграции
# -----------------------

def _init_history_db(conn: sqlite3.Connection) -> None:
    """
    Таблицы:
      history(id, plate, point, ts)
      last_seen(plate primary key, ts) — для ускоренного запроса последнего визита
    """
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history(
              id     INTEGER PRIMARY KEY AUTOINCREMENT,
              plate  TEXT NOT NULL,
              point  TEXT NOT NULL,
              ts     INTEGER NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS last_seen(
              plate TEXT PRIMARY KEY,
              ts    INTEGER NOT NULL
            );
            """
        )
        # Индексы
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_plate_ts ON history(plate, ts DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_ts ON history(ts);")


def _init_people_db(conn: sqlite3.Connection) -> None:
    """
    База «людей» (минимально необходимая схема для поиска номера).
    Ожидаемые поля:
      plates(plate TEXT PRIMARY KEY, fio TEXT, brand TEXT, address TEXT)
    Если у тебя собственная схема — модуль работает и с ней, важно наличие столбца plate.
    """
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS plates(
              plate   TEXT PRIMARY KEY,
              fio     TEXT,
              brand   TEXT,
              address TEXT
            );
            """
        )


# -----------------------
# Публичные функции (совместимость со старым модулем)
# -----------------------

def init_db() -> None:
    """
    Явная инициализация обеих БД (необязательна, т.к. lazy).
    """
    _ = _get_history_conn()
    _ = _get_people_conn()
    log("🗄️ DB: инициализация завершена")


def add_history_record(plate: str, point: str, ts: Optional[int] = None) -> None:
    """
    Добавляет запись в историю и обновляет last_seen.
    """
    if not plate:
        return
    if ts is None:
        ts = int(time.time())

    conn = _get_history_conn()
    with conn:
        conn.execute(
            "INSERT INTO history(plate, point, ts) VALUES(?, ?, ?)",
            (plate, point, ts),
        )
        # upsert в last_seen
        conn.execute(
            """
            INSERT INTO last_seen(plate, ts) VALUES(?, ?)
            ON CONFLICT(plate) DO UPDATE SET ts=excluded.ts
            """,
            (plate, ts),
        )
    # отладка
    log(f"📝 История: {plate} @ {point} ({ts})", debug=True)


def get_last_seen(plate: str) -> Optional[int]:
    """
    Возвращает timestamp последнего визита номера.
    Работает быстро по таблице last_seen.
    """
    if not plate:
        return None
    conn = _get_history_conn()
    row = conn.execute("SELECT ts FROM last_seen WHERE plate = ?", (plate,)).fetchone()
    return int(row["ts"]) if row and row.get("ts") is not None else None


def get_plate_from_db(base: str) -> Optional[str]:
    """
    Достраивает номер по базе людей, если у распознавания нет региона.
    Логика:
      1) Ищем точное совпадение в people по полю plate (на случай если base уже полный).
      2) Ищем plate, который начинается на base и дальше идут только цифры региона (1–3 цифры).
         Выбираем «наиболее длинное» совпадение (на случай нескольких регионов).
    Примеры:
      base='В368РМ' → найдёт 'В368РМ62'
      base='A123AA' → найдёт 'A123AA777'
    """
    if not base:
        return None
    conn = _get_people_conn()

    # 1) точное совпадение
    row = conn.execute(
        "SELECT plate FROM plates WHERE plate = ? LIMIT 1",
        (base,),
    ).fetchone()
    if row and row.get("plate"):
        return row["plate"]

    # 2) начинается с base + регион (1-3 цифры в конце)
    # Примечание: SQLite LIKE без регистрозависимости, но лучше нормализовать номера заранее.
    # Здесь предполагаем, что номера уже нормализованы во внешнем коде.
    like_pat = base + "%"

    rows = conn.execute(
        """
        SELECT plate FROM plates
        WHERE plate LIKE ?
        """,
        (like_pat,),
    ).fetchall()

    # Отберём только те, у кого хвост — 1-3 цифры
    best: Tuple[str, int] | None = None
    for r in rows or []:
        p = r.get("plate") or ""
        tail = p[len(base):]
        if tail.isdigit() and 1 <= len(tail) <= 3:
            # Выберем максимально длинный полный номер (на случай конкуренции)
            cand = (p, len(p))
            if best is None or cand[1] > best[1]:
                best = cand

    return best[0] if best else None


# -----------------------
# Вспомогательные функции (могут пригодиться веб-интерфейсу)
# -----------------------

def fetch_history(plate: Optional[str] = None, limit: int = 100, offset: int = 0) -> list[Dict[str, Any]]:
    """
    Возвращает список записей истории, свежие первыми.
    """
    conn = _get_history_conn()
    if plate:
        rows = conn.execute(
            """
            SELECT plate, point, ts
            FROM history
            WHERE plate = ?
            ORDER BY ts DESC
            LIMIT ? OFFSET ?
            """,
            (plate, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT plate, point, ts
            FROM history
            ORDER BY ts DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return rows or []


def upsert_person_plate(plate: str, fio: Optional[str] = None, brand: Optional[str] = None, address: Optional[str] = None) -> None:
    """
    Утилита для добавления/обновления записи в people.db (может использоваться из админки).
    """
    if not plate:
        return
    conn = _get_people_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO plates(plate, fio, brand, address)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(plate) DO UPDATE SET
              fio=COALESCE(excluded.fio, fio),
              brand=COALESCE(excluded.brand, brand),
              address=COALESCE(excluded.address, address)
            """,
            (plate, fio, brand, address),
        )
    log(f"👤 People: сохранён {plate}", debug=True)


def close_connections() -> None:
    """
    Закрыть соединения (например, при остановке сервера).
    """
    global _history_conn, _people_conn
    with _history_conn_lock:
        if _history_conn is not None:
            try:
                _history_conn.close()
            except Exception:
                pass
            _history_conn = None
    with _people_conn_lock:
        if _people_conn is not None:
            try:
                _people_conn.close()
            except Exception:
                pass
            _people_conn = None
