from backend.cpai import handle_cpai_result
from backend.state import seen_plates as _seen_plates, _gate_state
import paho.mqtt.client as mqtt

# MQTT клиент для теста (можно локально)
client = mqtt.Client()
client.connect("192.168.12.2", 1883, 60)
client.loop_start()

print("Тест CPAI. Вводите номер или 'exit' для выхода.")

while True:
    plate = input("Введите номер: ").strip()
    if plate.lower() in ("exit", "quit"):
        break
    if not plate:
        continue

    # Псевдоответ CPAI
    res = {"ok": True, "plate": plate, "err": None}

    # Обработка результата
    handle_cpai_result(res, "Ворота", "IN", client)

    # Печатаем текущее состояние ворот и виденные номера
    print("Состояние ворот:", _gate_state)
    print("Виденные номера:", _seen_plates)
    print("-" * 40)
