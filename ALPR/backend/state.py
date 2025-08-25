# backend/state.py
from __future__ import annotations
import threading
import time

# -----------------------
# Статусы подключений
# -----------------------
MQTT_CONNECTED: bool = False
CPAI_CONNECTED: bool = False

# -----------------------
# Кэш распознанных номеров
# -----------------------
# seen_plates[point_name][plate] = timestamp последнего появления
seen_plates: dict[str, dict[str, float]] = {}
seen_plates_lock = threading.Lock()

# Минимальный интервал повторного срабатывания CPAI для одного номера (сек)
CPAI_REPEAT_INTERVAL: float = 5.0

# -----------------------
# Статус открытия ворот
# -----------------------
# gates_state[point_name] = {
#     "is_open": bool,
#     "last_change": ts
# }
gates_state: dict[str, dict[str, float | bool]] = {}
gates_lock = threading.Lock()


def set_mqtt_connected(ok: bool) -> None:
    global MQTT_CONNECTED
    MQTT_CONNECTED = ok


def set_cpai_connected(ok: bool) -> None:
    global CPAI_CONNECTED
    CPAI_CONNECTED = ok


def is_plate_recent(point: str, plate: str, interval: float | None = None) -> bool:
    """
    Проверяет, был ли номер уже недавно замечен на данной точке.
    """
    if not point or not plate:
        return False
    interval = interval or CPAI_REPEAT_INTERVAL
    now = time.time()
    with seen_plates_lock:
        last_ts = seen_plates.get(point, {}).get(plate)
        if last_ts and (now - last_ts) < interval:
            return True
    return False


def mark_gate(point: str, is_open: bool) -> None:
    """
    Обновляет состояние ворот (открыто/закрыто).
    """
    with gates_lock:
        gates_state[point] = {
            "is_open": is_open,
            "last_change": time.time(),
        }


def get_gate_state(point: str) -> dict[str, float | bool] | None:
    """
    Возвращает текущее состояние ворот для точки.
    """
    with gates_lock:
        return gates_state.get(point, None)
