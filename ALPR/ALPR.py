# ALPR.py
from __future__ import annotations

import json
import time
from datetime import datetime

from backend import cpai, db, text_utils, state
from backend.mqtt_wrap import start_mqtt, publish_message
from backend.logger import log
from backend.config import TOPIC_PREFIX


# -----------------------
# Обработка сообщения от MQTT (камеры / BlueIris)
# -----------------------

def on_mqtt_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8", errors="ignore")
    except Exception:
        payload = ""
    log(f"📥 MQTT {msg.topic} = {payload}", debug=True)

    # Ожидаем JSON вида {"point": "Vorota", "snapshot": "path/to/file.jpg"}
    try:
        data = json.loads(payload)
    except Exception:
        log("⚠️ Некорректный JSON в MQTT-сообщении", debug=True)
        return

    point = data.get("point") or "unknown"
    snapshot_path = data.get("snapshot")

    if not snapshot_path:
        log(f"⚠️ Нет snapshot в сообщении от {point}")
        return

    # Запускаем обработку
    process_snapshot(point, snapshot_path)


# -----------------------
# Основная логика обработки кадра
# -----------------------

def process_snapshot(point: str, snapshot_path: str):
    """
    Обработка нового кадра от камеры.
    """
    log(f"🖼️ Получен кадр от {point}: {snapshot_path}")

    # Отправляем в CPAI
    try:
        results = cpai.send_to_cpai(snapshot_path)
    except Exception as e:
        log(f"❌ Ошибка CPAI: {e}")
        state.set_cpai_connected(False)
        return

    state.set_cpai_connected(True)

    if not results:
        log(f"ℹ️ CPAI: номера не распознаны для {point}")
        return

    for plate_raw in results:
        plate = text_utils.normalize_text(plate_raw)
        base, region = text_utils.parse_plate_parts(plate)

        # Если база определена, но региона нет — ищем достройку в people.db
        if base and not region:
            full_plate = db.get_plate_from_db(base)
            if full_plate:
                log(f"✅ Достроен номер: {plate} → {full_plate}")
                plate = full_plate

        if not plate:
            log(f"⚠️ Номер не прошёл валидацию: {plate_raw}")
            continue

        # Проверка повторов
        if state.is_plate_recent(point, plate):
            log(f"⏩ Пропуск повторного номера {plate} ({point})")
            continue

        # Сохраняем в историю
        ts = int(time.time())
        db.add_history_record(plate, point, ts)

        # MQTT публикация
        publish_plate(point, plate, ts)


def publish_plate(point: str, plate: str, ts: int):
    """
    Публикует результат распознавания в MQTT.
    """
    last_seen = db.get_last_seen(plate)
    data = {
        "plate": plate,
        "point": point,
        "ts": ts,
        "last_seen": last_seen,
        "iso_time": datetime.fromtimestamp(ts).isoformat(),
    }
    payload = json.dumps(data, ensure_ascii=False)
    publish_message("plates", payload)
    log(f"📤 Опубликован номер: {plate} ({point})")


# -----------------------
# Запуск
# -----------------------

def start():
    log("🚀 ALPR модуль запущен")
    db.init_db()
    start_mqtt(on_message_cb=on_mqtt_message)
