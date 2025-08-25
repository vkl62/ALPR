# backend/config.py
from __future__ import annotations
import os
import json
from pathlib import Path
from urllib.parse import urlparse
import torch

# -----------------------
# Корневой каталог
# -----------------------
ROOT_DIR = Path(__file__).resolve().parent.parent

SETTINGS_FILE = str(ROOT_DIR / "settings.json")
LOG_FILE = str(ROOT_DIR / "alpr.log")

DB_HISTORY_PATH = str(ROOT_DIR / "history.db")
DB_PEOPLE_PATH = str(ROOT_DIR / "people.db")

SNAPSHOT_DIR_DEFAULT = str(ROOT_DIR / "static" / "snapshots")

# -----------------------
# Загрузка настроек
# -----------------------

def _load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
            return s if isinstance(s, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

SETTINGS = _load_settings()

# -----------------------
# Флаги и параметры
# -----------------------
DEBUG_MODE = bool(SETTINGS.get("debug", False))

CAPTURE_INTERVAL = float(SETTINGS.get("capture_interval", 2.0))
CPAI_MIN_INTERVAL = float(SETTINGS.get("cpai_min_interval", 3.0))

# -----------------------
# MQTT
# -----------------------
MQTT_BROKER = SETTINGS.get("mqtt", {}).get("host", "192.168.12.2")
MQTT_PORT = int(SETTINGS.get("mqtt", {}).get("port", 1883))
MQTT_USER = SETTINGS.get("mqtt", {}).get("user") or None
MQTT_PASS = SETTINGS.get("mqtt", {}).get("password") or None
TOPIC_PREFIX = SETTINGS.get("mqtt", {}).get("base_topic", "ALPR")

# -----------------------
# Пути к данным
# -----------------------

def _resolve_path(value: str | None, default_path: str) -> str:
    if not value:
        return default_path
    p = Path(value)
    return str(p if p.is_absolute() else (ROOT_DIR / p))

SNAPSHOT_DIR = _resolve_path(
    SETTINGS.get("paths", {}).get("snapshots") if SETTINGS.get("paths") else None,
    SNAPSHOT_DIR_DEFAULT,
)

# -----------------------
# CPAI URL
# -----------------------

def _cpai_url_from_settings(s: dict, fallback: str = "http://192.168.12.11:32168/v1/vision/alpr") -> str:
    cp = (s or {}).get("cpai", {}) if isinstance(s, dict) else {}
    host = cp.get("host")
    port = cp.get("port")
    if (not host or not port) and cp.get("url"):
        try:
            parsed = urlparse(cp["url"])
            if parsed.hostname and not host:
                host = parsed.hostname
            if parsed.port and not port:
                port = parsed.port
        except Exception:
            pass
    host = host or "192.168.12.11"
    try:
        port = int(port) if port is not None else 32168
    except Exception:
        port = 32168
    return f"http://{host}:{port}/v1/vision/alpr"

CPAI_URL = _cpai_url_from_settings(SETTINGS)

# -----------------------
# Torch / GPU
# -----------------------
USE_TORCH_GPU_PREP = bool(SETTINGS.get("use_torch_gpu_prep", False))
TORCH_AVAILABLE = torch.cuda.is_available()
DEVICE = torch.device("cuda" if TORCH_AVAILABLE else "cpu")
