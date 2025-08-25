import threading
import time
import subprocess
import sys
import os
from backend.logger import log
from backend.config import HISTORY_DB
from backend.state import gate_lock  # отдельный lock для ворот
import paho.mqtt.client as mqtt

_gate_state: dict[str, str] = {}
_gate_cycle_start_ts: dict[str, str] = {}

def _find_history_cleaner_path() -> str | None:
    root = os.path.dirname(os.path.dirname(__file__))
    c1 = os.path.join(root, "backend", "history_cleaner.py")
    c2 = os.path.join(root, "history_cleaner.py")
    if os.path.exists(c1):
        return c1
    if os.path.exists(c2):
        return c2
    return None

def call_history_cleaner(point_name: str, start_ts: str, end_ts: str):
    try:
        script = _find_history_cleaner_path()
        if not script:
            log("⚠️ history_cleaner.py не найден.", debug=True)
            return
        cmd = [sys.executable, script, "--db", HISTORY_DB, "--point", point_name,
               "--since", start_ts, "--until", end_ts]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"▶️ Запущен history_cleaner для {point_name} [{start_ts} → {end_ts}]")
    except Exception as e:
        log(f"❌ Не удалось запустить history_cleaner: {e}", debug=True)

def mark_gate_open(point_name: str, hold_s: int = 30):
    _gate_state[point_name] = "OPEN"
    start_ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _gate_cycle_start_ts[point_name] = start_ts
    log(f"Статус ворот {point_name}: OPEN")

    def _close():
        with gate_lock:
            _gate_state[point_name] = "CLOSED"
            end_ts = time.strftime("%Y-%m-%d %H:%M:%S")
            log(f"Статус ворот {point_name}: CLOSED")
            start_for_clean = _gate_cycle_start_ts.pop(point_name, start_ts)
            call_history_cleaner(point_name, start_for_clean, end_ts)

    threading.Timer(hold_s, _close).start()

# псевдонимы для совместимости
open_gate = mark_gate_open

def can_open_gate(point_name: str) -> bool:
    return _gate_state.get(point_name) == "CLOSED"

def send_open_command(client: mqtt.Client, topic: str, point_name: str):
    try:
        client.publish(topic, "1")
        log(f"Отправлена команда OPEN на {point_name}")
        mark_gate_open(point_name)
    except Exception as e:
        log(f"Ошибка публикации OPEN для {point_name}: {e}", debug=True)
