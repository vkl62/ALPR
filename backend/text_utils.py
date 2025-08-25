# backend/text_utils.py
from __future__ import annotations
import re

# -----------------------
# Словари замен латиницы → кириллица
# -----------------------
LATIN_TO_CYR = {
    "A": "А",
    "B": "В",
    "C": "С",
    "E": "Е",
    "H": "Н",
    "K": "К",
    "M": "М",
    "O": "О",
    "P": "Р",
    "T": "Т",
    "X": "Х",
    "Y": "У",
}

# Разрешённые буквы ГОСТ Р 50577–2018 (русские госномера)
ALLOWED_LETTERS = "АВЕКМНОРСТУХ"

# -----------------------
# Регулярные выражения для номеров
# -----------------------

# Стандартный формат: А123ВС77 или А123ВС777
RX_STANDARD = re.compile(
    rf"^([{ALLOWED_LETTERS}]\d{{3}}[{ALLOWED_LETTERS}]{{2}})(\d{{2,3}})?$"
)

# Перевёрнутый формат (иногда распознавалка путает):
# 77А123ВС → парсим как (А123ВС, 77)
RX_REVERSED = re.compile(
    rf"^(\d{{2,3}})([{ALLOWED_LETTERS}]\d{{3}}[{ALLOWED_LETTERS}]{{2}})$"
)


# -----------------------
# Основные функции
# -----------------------

def normalize_text(text: str) -> str:
    """
    Унифицирует распознанный номер:
      - переводит в верхний регистр,
      - удаляет все лишние символы,
      - заменяет латиницу на кириллицу.
    """
    if not text:
        return ""
    t = text.upper()
    # Оставляем только буквы/цифры
    t = re.sub(r"[^A-ZА-Я0-9]", "", t)
    # Замена латиницы на кириллицу
    t = "".join(LATIN_TO_CYR.get(ch, ch) for ch in t)
    return t


def parse_plate_parts(text: str) -> tuple[str | None, str | None]:
    """
    Разбивает строку на (основа, регион).
    Примеры:
      "А123ВС77"   -> ("А123ВС", "77")
      "А123ВС777"  -> ("А123ВС", "777")
      "77А123ВС"   -> ("А123ВС", "77")
      "В368РМ"     -> ("В368РМ", None)
    """
    if not text:
        return None, None
    m = RX_STANDARD.match(text)
    if m:
        return m.group(1), m.group(2)
    m = RX_REVERSED.match(text)
    if m:
        return m.group(2), m.group(1)
    return None, None


def safe_name(name: str) -> str:
    """
    Делает строку безопасной для имени файла.
    """
    if not name:
        return ""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", name.strip())
