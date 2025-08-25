# backend/mqtt_wrap.py
from __future__ import annotations

import threading
import paho.mqtt.client as mqtt

from backend.logger import log
from backend.config import MQTT_BROKER, MQTT_PORT, MQTT_USER, MQTT_PASS, TOPIC_PREFIX
import backend.state as state


class MQTTWrap:
    """
    Обёртка над paho-mqtt для совместимости со старым модулем ALPR_OLD.py.
    """

    def __init__(self, on_message_cb=None):
        self.client = mqtt.Client()
        self.on_message_cb = on_message_cb
        self._lock = threading.Lock()

        if MQTT_USER:
            self.client.username_pw_set(MQTT_USER, MQTT_PASS or "")

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    # -----------------------
    # Внутренние коллбеки
    # -----------------------

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            log(f"🔌 MQTT подключен ({MQTT_BROKER}:{MQTT_PORT})")
            state.set_mqtt_connected(True)
            try:
                topic = f"{TOPIC_PREFIX}/#"
                client.subscribe(topic)
                log(f"📡 Подписка на {topic}")
            except Exception as e:
                log(f⚠️ Ошибка подписки: {e}")
        else:
            log(f"❌ MQTT ошибка подключения: rc={rc}")
            state.set_mqtt_connected(False)

    def _on_disconnect(self, client, userdata, rc):
        state.set_mqtt_connected(False)
        log("🔌 MQTT отключен")

    def _on_message(self, client, userdata, msg):
        if self.on_message_cb:
            try:
                self.on_message_cb(client, userdata, msg)
            except Exception as e:
                log(f"⚠️ Ошибка обработки MQTT-сообщения: {e}", debug=True)

    # -----------------------
    # Публичные методы
    # -----------------------

    def start(self, loop_async: bool = True):
        """
        Запускает MQTT loop (по умолчанию в отдельном потоке).
        """
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=30)
        except Exception as e:
            log(f"❌ Ошибка подключения к MQTT: {e}")
            state.set_mqtt_connected(False)
            return

        if loop_async:
            self.client.loop_start()
        else:
            self.client.loop_forever()

    def publish(self, topic: str, payload: str, retain: bool = False) -> bool:
        """
        Публикация в MQTT. Возвращает True при успехе.
        """
        try:
            with self._lock:
                full_topic = f"{TOPIC_PREFIX}/{topic}"
                self.client.publish(full_topic, payload, retain=retain)
            log(f"➡️ MQTT {full_topic} = {payload}", debug=True)
            return True
        except Exception as e:
            log(f"⚠️ Ошибка публикации MQTT: {e}")
            return False

    def stop(self):
        """
        Останавливает MQTT loop.
        """
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass


# -----------------------
# Глобальные функции (совместимость)
# -----------------------

_mqtt_wrap: MQTTWrap | None = None


def start_mqtt(on_message_cb=None) -> MQTTWrap:
    global _mqtt_wrap
    if _mqtt_wrap is None:
        _mqtt_wrap = MQTTWrap(on_message_cb=on_message_cb)
        _mqtt_wrap.start()
    return _mqtt_wrap


def publish_message(topic: str, payload: str, retain: bool = False) -> bool:
    """
    Упрощённая публикация без явного доступа к объекту.
    """
    if _mqtt_wrap:
        return _mqtt_wrap.publish(topic, payload, retain)
    return False
