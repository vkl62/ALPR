from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import json
import threading
import sqlite3
import time
import cv2
import re
import subprocess
from urllib.parse import urlparse

# импортируем ALPR чтобы иметь доступ к его статусам (MQTT/CPAI)
import ALPR

BASE_DIR = os.path.dirname(__file__)
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
LOG_FILE = os.path.join(BASE_DIR, "alpr.log")

# -----------------------
# Настройки
# -----------------------
def _migrate_cpai(s: dict) -> dict:
    """
    Обратная совместимость:
    - если есть cpai.url и нет host/port — распарсим и положим host/port.
    """
    cpai = s.setdefault("cpai", {})
    host = cpai.get("host")
    port = cpai.get("port")
    if (not host or not port) and cpai.get("url"):
        try:
            parsed = urlparse(cpai["url"])
            if parsed.hostname and not host:
                cpai["host"] = parsed.hostname
            if parsed.port and not port:
                cpai["port"] = parsed.port
        except Exception:
            pass

    # Дефолты
    cpai.setdefault("host", "192.168.12.11")
    cpai.setdefault("port", 32168)

    return s

def load_settings():
    """
    Загружаем settings.json.
    Если файла нет — создаём дефолт c едиными базами и новыми полями cpai.host/port.
    """
    if not os.path.exists(SETTINGS_FILE):
        data = {
            "mqtt": {"host": "127.0.0.1", "port": 1883, "base_topic": "ALPR"},
            "cpai": {"host": "192.168.12.11", "port": 32168},
            "paths": {
                "base_db": "base.db",
                "snapshots": "static/snapshots",
            },
            "capture_interval": 2,
            "debug": False,
        }
        save_settings(data)
        return data

    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _migrate_cpai(data)

def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _resolve_base_db_path(s):
    paths = s.get("paths", {}) if isinstance(s, dict) else {}
    base_db_name = paths.get("base_db") or "base.db"
    return os.path.join(BASE_DIR, base_db_name)

# Глобальные пути
settings = load_settings()
BASE_DB = _resolve_base_db_path(settings)
PEOPLE_DB = BASE_DB
POINTS_DB = BASE_DB
SNAPSHOT_DIR = os.path.join(BASE_DIR, settings["paths"].get("snapshots", "static/snapshots"))
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

def refresh_paths_from_settings():
    global settings, BASE_DB, PEOPLE_DB, POINTS_DB, SNAPSHOT_DIR
    settings = load_settings()
    BASE_DB = _resolve_base_db_path(settings)
    PEOPLE_DB = BASE_DB
    POINTS_DB = BASE_DB
    SNAPSHOT_DIR = os.path.join(BASE_DIR, settings["paths"].get("snapshots", "static/snapshots"))
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

# -----------------------
# Flask
# -----------------------
app = Flask(__name__, static_folder="static")
CORS(app)

# -----------------------
# API: Статус
# -----------------------
@app.route("/api/status")
def get_status():
    mqtt_status = "OK" if getattr(ALPR, "MQTT_CONNECTED", False) else "Нет соединения"
    cpai_status = "OK" if getattr(ALPR, "CPAI_CONNECTED", False) else "Нет соединения"
    return jsonify({"mqtt": mqtt_status, "cpai": cpai_status})

# -----------------------
# API: Лог
# -----------------------
@app.route("/api/log")
def get_log():
    if not os.path.exists(LOG_FILE):
        return jsonify({"log": []})
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return jsonify({"log": [line.strip() for line in lines]})

# -----------------------
# Статика
# -----------------------
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/static/<path:path>")
def send_static(path):
    return send_from_directory("static", path)

# -----------------------
# API: Настройки
# -----------------------
@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(load_settings())

@app.route("/api/settings", methods=["POST"])
def api_set_settings():
    """
    Обновляем settings.json. Дополнительно:
    - live-обновление ALPR.DEBUG_MODE;
    - пересчитываем пути и создаём таблицы в (возможно новой) базе.
    """
    data = request.json or {}
    s = load_settings()

    # merge на верхнем уровне и внутри "paths" и "cpai"
    if "paths" in data and isinstance(data["paths"], dict):
        s_paths = s.get("paths", {})
        s_paths.update(data["paths"])
        s["paths"] = s_paths

    if "cpai" in data and isinstance(data["cpai"], dict):
        s_cpai = s.get("cpai", {})
        s_cpai.update(data["cpai"])
        s["cpai"] = s_cpai

    for k, v in data.items():
        if k not in ("paths", "cpai"):
            s[k] = v

    # миграция/дефолты для cpai
    s = _migrate_cpai(s)
    save_settings(s)

    # live-обновление флага дебага внутри ALPR
    try:
        ALPR.DEBUG_MODE = bool(s.get("debug", False))
    except Exception:
        pass

    refresh_paths_from_settings()
    ensure_tables()

    return jsonify({"status": "ok"})

# -----------------------
# Инициализация БД (люди + точки)
# -----------------------
def ensure_tables():
    with sqlite3.connect(BASE_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                car_number TEXT UNIQUE,
                car_model TEXT,
                phone TEXT,
                address TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_id INTEGER,
                point TEXT,
                direction TEXT,
                plate TEXT,
                ts TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                mqtt_topic TEXT,
                rtp_url TEXT,
                in_camera_url TEXT,
                out_camera_url TEXT
            )
            """
        )

        # миграция совместимости: перенесём rtp_url -> in_camera_url при необходимости
        cur = conn.cursor()
        cur.execute("SELECT id, rtp_url, in_camera_url FROM points")
        for pid, rtp, in_cam in cur.fetchall():
            if rtp and not in_cam:
                conn.execute("UPDATE points SET in_camera_url=? WHERE id=?", (rtp, pid))

    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

ensure_tables()

# -----------------------
# Путь к отдельной истории (history.db из ALPR)
# -----------------------
def _history_db_path():
    try:
        return getattr(ALPR, "HISTORY_DB_PATH", os.path.join(BASE_DIR, "history.db"))
    except Exception:
        return os.path.join(BASE_DIR, "history.db")

# -----------------------
# API: People
# -----------------------
@app.route("/api/people", methods=["GET"])
def get_people():
    with sqlite3.connect(PEOPLE_DB) as conn:
        rows = conn.execute(
            "SELECT id, name, car_number, car_model, phone, address FROM people"
        ).fetchall()
        people = [
            {
                "id": r[0],
                "name": r[1],
                "car_number": r[2],
                "car_model": r[3],
                "phone": r[4],
                "address": r[5],
            }
            for r in rows
        ]
    return jsonify({"people": people})

@app.route("/api/people", methods=["POST"])
def add_person():
    data = request.json
    with sqlite3.connect(PEOPLE_DB) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO people
            (id, name, car_number, car_model, phone, address)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("id"),
                data.get("name"),
                data.get("car_number"),
                data.get("car_model"),
                data.get("phone"),
                data.get("address"),
            ),
        )
        conn.commit()
    return jsonify({"status": "ok"})

@app.route("/api/people/<int:id>", methods=["DELETE"])
def delete_person(id):
    with sqlite3.connect(PEOPLE_DB) as conn:
        conn.execute("DELETE FROM people WHERE id=?", (id,))
        conn.commit()
    return jsonify({"status": "ok"})

# -----------------------
# API: Points
# -----------------------
@app.route("/api/points", methods=["GET"])
def get_points():
    with sqlite3.connect(POINTS_DB) as conn:
        rows = conn.execute(
            "SELECT id, name, mqtt_topic, rtp_url, in_camera_url, out_camera_url FROM points"
        ).fetchall()
        points = []
        for r in rows:
            pid, name, mqtt_topic, rtp_url, in_camera_url, out_camera_url = r
            if not in_camera_url and rtp_url:
                in_camera_url = rtp_url
            points.append(
                {
                    "id": pid,
                    "name": name,
                    "mqtt_topic": mqtt_topic,
                    "rtp_url": rtp_url,
                    "in_camera_url": in_camera_url,
                    "out_camera_url": out_camera_url,
                }
            )
    return jsonify({"points": points})

@app.route("/api/points", methods=["POST"])
def add_point():
    data = request.json
    name = data.get("name")
    in_cam = data.get("in_camera_url") or data.get("rtp_url") or ""
    out_cam = data.get("out_camera_url") or ""
    mqtt_topic = data.get("mqtt_topic", name)
    with sqlite3.connect(POINTS_DB) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO points
            (id, name, mqtt_topic, rtp_url, in_camera_url, out_camera_url)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (data.get("id"), name, mqtt_topic, data.get("rtp_url"), in_cam, out_cam),
        )
        conn.commit()
    return jsonify({"status": "ok"})

@app.route("/api/points/<int:id>", methods=["DELETE"])
def delete_point(id):
    with sqlite3.connect(POINTS_DB) as conn:
        conn.execute("DELETE FROM points WHERE id=?", (id,))
        conn.commit()
    return jsonify({"status": "ok"})

# -----------------------
# API: История событий (из history.db)
# -----------------------
@app.route("/api/history", methods=["GET"])
def api_history():
    search = (request.args.get("search") or "").strip()
    date_from = (request.args.get("from") or "").strip()
    date_to = (request.args.get("to") or "").strip()
    try:
        limit = max(1, min(200, int(request.args.get("limit", 50))))
    except Exception:
        limit = 50
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except Exception:
        offset = 0

    def _start_of_day(d): return d + " 00:00:00" if len(d) == 10 else d
    def _end_of_day(d):   return d + " 23:59:59" if len(d) == 10 else d

    where = []
    args = []
    if search:
        where.append("plate LIKE ?")
        args.append(f"%{search}%")
    if date_from:
        where.append("timestamp >= ?")
        args.append(_start_of_day(date_from))
    if date_to:
        where.append("timestamp <= ?")
        args.append(_end_of_day(date_to))
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    db_path = _history_db_path()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute(f"SELECT COUNT(*) AS cnt FROM history{where_sql}", args).fetchone()["cnt"]
            items = conn.execute(
                f"""
                SELECT id, timestamp, plate, point_name
                FROM history
                {where_sql}
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                args + [limit, offset]
            ).fetchall()
            out = [{"id": r["id"], "timestamp": r["timestamp"], "plate": r["plate"], "point_name": r["point_name"]} for r in items]
        return jsonify({"items": out, "total": total, "limit": limit, "offset": offset})
    except Exception as e:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} Ошибка /api/history: {e}\n")
        return jsonify({"items": [], "total": 0, "limit": limit, "offset": offset})

# -----------------------
# Снимки
# -----------------------
def capture_and_save_single(rtsp_url, save_path):
    try:
        cap = cv2.VideoCapture(rtsp_url)
        if not cap or not cap.isOpened():
            try:
                cap.release()
            except Exception:
                pass
            return False
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return False
        cv2.imwrite(save_path, frame)
        return True
    except Exception as e:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} Ошибка capture_and_save_single {e}\n")
        return False

@app.route("/api/refresh_snapshots", methods=["POST"])
def refresh_snapshots():
    updated = []
    with sqlite3.connect(POINTS_DB) as conn:
        rows = conn.execute(
            "SELECT id, name, in_camera_url, out_camera_url, rtp_url FROM points"
        ).fetchall()
    for r in rows:
        pid, name, in_cam, out_cam, rtp = r
        if not in_cam and rtp:
            in_cam = rtp  # совместимость
        safe = re.sub(r"[^A-Za-z0-9_\-]", "_", (name or f"pt{pid}"))
        if in_cam:
            path_in = os.path.join(SNAPSHOT_DIR, f"{safe}_in.jpg")
            ok = capture_and_save_single(in_cam, path_in)
            updated.append({"point": name, "dir": "IN", "ok": ok})
        if out_cam:
            path_out = os.path.join(SNAPSHOT_DIR, f"{safe}_out.jpg")
            ok = capture_and_save_single(out_cam, path_out)
            updated.append({"point": name, "dir": "OUT", "ok": ok})
    return jsonify({"updated": updated})

# -----------------------
# ALPR запуск
# -----------------------
def run_alpr():
    try:
        ALPR.main()
    except Exception as e:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} Ошибка запуска ALPR: {e}\n")

# -----------------------
# API: Перезапуск службы ALPR
# -----------------------
@app.route("/api/restart", methods=["POST"])
def api_restart():
    """
    Асинхронный перезапуск службы Windows через внешний батник.
    По умолчанию служба называется 'alpr'.
    Можно задать имя службы полем request.json.service (необязательно).
    """
    service_name = (request.json or {}).get("service") or "alpr"
    bat_path = os.path.join(BASE_DIR, "restart_alpr.bat")
    if not os.path.exists(bat_path):
        return jsonify({"status": "error", "error": "restart_alpr.bat not found"}), 500

    try:
        # Запускаем detached: cmd /c start "" restart_alpr.bat service_name
        subprocess.Popen(
            ["cmd", "/c", "start", "", bat_path, service_name],
            cwd=BASE_DIR,
            shell=False
        )
        return jsonify({"status": "restarting", "service": service_name})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == "__main__":
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    threading.Thread(target=run_alpr, daemon=True).start()
    app.run(host="0.0.0.0", port=8081)
