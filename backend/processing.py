# backend/processing.py
from __future__ import annotations

import time
from datetime import datetime

from backend import db, text_utils, state, gates
from backend.logger import log
from backend.mqtt_wrap import publish_message


def handle_recognized_plate(point: str, plate_raw: str, ts: int | None = None):
    """
    Обрабатывает распознанный номер (от CPAI).
    Включает:
      - нормализацию,
      - достройку региона (по базе people.db),
      - проверку повторов,
      - сохранение в историю,
      - публикацию в MQTT,
      - вызов логики управления воротами.
    """
    plate = text_utils.normalize_text(plate_raw)
    if not plate:
        log(f"⚠️ Пустой или некорректный номер: {plate_raw}")
        return

    base, region = text_utils.parse_plate_parts(plate)

    # Если регион не распознан — ищем в базе
    if base and not region:
        full_plate = db.get_plate_from_db(base)
        if full_plate:
            log(f"✅ Достроен номер: {plate} → {full_plate}")
            plate = full_plate

    if not plate:
        log(f"⚠️ Номер отклонён: {plate_raw}")
        return

    # Проверка повторов (чтобы не дублировать события)
    if state.is_plate_recent(point, plate):
        log(f"⏩ Пропуск повтора номера {plate} ({point})")
        return

    ts = ts or int(time.time())

    # Сохраняем в историю
    db.add_history_record(plate, point, ts)

    # Публикация в MQTT
    publish_plate(point, plate, ts)

    # Логика ворот
    gates.handle_plate(point, plate, ts)


def publish_plate(point: str, plate: str, ts: int):
    """
    Публикация информации о номере в MQTT.
    """
    last_seen = db.get_last_seen(plate)
    data = {
        "plate": plate,
        "point": point,
        "ts": ts,
        "last_seen": last_seen,
        "iso_time": datetime.fromtimestamp(ts).isoformat(),
    }
    import json
    payload = json.dumps(data, ensure_ascii=False)
    publish_message("plates", payload)
    log(f"📤 Опубликован номер: {plate} ({point})")
