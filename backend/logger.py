from __future__ import annotations
import time
from backend.config import LOG_FILE, DEBUG_MODE


def log(msg: str, debug: bool = False):
    if debug and not DEBUG_MODE:
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass