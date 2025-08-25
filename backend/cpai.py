# backend/cpai.py
from __future__ import annotations

import time
import json
import threading
import requests

from backend.logger import log
from backend.text_utils import normalize_text
from backend.db import add_history_record, get_plate_from_db
from backend.gates import open_gate, can_open_gate, send_open_command
from backend.config import CPAI_URL
import backend.state as state  # чтобы менять флаги статуса


# -----------------------
# CPAI client
# -----------------------
class CPAIClient:
    """
    Простой клиент CodeProject.AI (ALPR).
    Возвращает унифицированный результат:
    {
      "ok": bool,
      "plate": str | None,  # сырая строка от CPAI (до normalize_text)
      "err": str | None
    }
    """
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or CPAI_URL
        self._http = requests.Session()

    def recognize_plate(self, image_bytes: bytes) -> dict:
        try:
            resp = self._http.post(
                self.base_url,
                files={"image": ("frame.jpg", image_bytes, "image/jpeg")},
                timeout=6,
            )
            if resp.status_code != 200:
                state.CPAI_CONNECTED = False
                return {"ok": False, "plate": None, "err": f"HTTP {resp.status_code}"}

            # CodeProject.AI возвращает разные ключи в разных версиях
            # поддержим и predictions, и results
            try:
                data = resp.json()
            except Exception:
                # иногда приходят "text/html" с телом ошибки
                data = {}
            preds = data.get("predictions", []) or data.get("results", []) or []

            state.CPAI_CONNECTED = True

            if not preds:
                return {"ok": True, "plate": None, "err": None}

            p = preds[0] if isinstance(preds, list) else preds
            plate_raw = (p.get("plate") or p.get("text") or "").strip()
            return {"ok": True, "plate": plate_raw or None, "err": None}

        except Exception as e:
            state.CPAI_CONNECTED = False
            return {"ok": False, "plate": None, "err": str(e)}


# -----------------------
# Функции-обёртки для совместимости со старым кодом
# -----------------------
def recognize_plate_bytes(img_bytes: bytes) -> dict:
    """
    Обёртка старого интерфейса. Берёт URL из настроек (CPAI_URL).
    """
    client = CPAIClient()
    return client.recognize_plate(img_bytes)


def handle_cpai_result(
    res: dict,
    point_name: str,
    direction: str | None = None,
    client=None,
    mqtt_open_topic: str | None = None,
) -> None:
    """
    Унифицированная обработка результата CPAI:
    - логирование ошибок;
    - нормализация номера;
    - дорешивание региона при необходимости через people.db (совместимость со старым get_plate_from_db);
    - кэширование «увиденных» номеров;
    - запись в history.db;
    - публикация номера в MQTT (если передан клиент);
    - проверка и открытие ворот (локально + опционально MQTT open-команда).

    Параметры:
      client — paho.mqtt клиент (опционально)
      mqtt_open_topic — топик для OPEN-команды (если нужен MQTT-триггер открытия)
    """
    if not res or not res.get("ok"):
        log(f"❌ CPAI ошибка: {res.get('err') if res else 'unknown'}")
        return

    plate_raw = res.get("plate")
    if not plate_raw:
        log(f"⚠️ CPAI не вернул номер для {point_name}")
        return

    # Нормализуем (латиница→кириллица, удаление мусора)
    normalized = normalize_text(plate_raw)

    # Если регион не распознан, попробуем достроить по базе
    # Пример: ABC123 -> в БД есть ABC12377 -> тогда используем её
    full_plate = normalized
    from backend.text_utils import parse_plate_parts
    base, region = parse_plate_parts(normalized)
    if base and not region:
        from_db = get_plate_from_db(base)
        if from_db:
            full_plate = from_db

    # Обновляем кэш «увиденных» номеров
    with state.seen_plates_lock:
        if point_name not in state.seen_plates:
            state.seen_plates[point_name] = {}
        state.seen_plates[point_name][full_plate] = time.time()

    log(f"✅ Новый номер {full_plate} на точке {point_name}{(' / ' + direction) if direction else ''}")

    # История
    try:
        add_history_record(full_plate, point_name)
    except Exception as e:
        log(f"⚠️ Ошибка записи в history: {e}", debug=True)

    # Публикация номера в MQTT (совместимо с processing.process_camera)
    if client:
        try:
            topic = f"{point_name}/plate"  # так делает processing.py
            client.publish(topic, full_plate)
        except Exception as e:
            log(f"⚠️ Ошибка публикации MQTT (plate): {e}", debug=True)

    # Открываем ворота, если можно
    try:
        if can_open_gate(point_name):
            open_gate(point_name)
            # При необходимости — отправка OPEN в MQTT (если дан топик)
            if client and mqtt_open_topic:
                try:
                    send_open_command(client, mqtt_open_topic, point_name)
                except Exception as e:
                    log(f"⚠️ Ошибка публикации MQTT (open): {e}", debug=True)
    except Exception as e:
        log(f"⚠️ Ошибка логики ворот: {e}", debug=True)
