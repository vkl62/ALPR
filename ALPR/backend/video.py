import cv2
import threading
import time
import os

# -----------------------
# FrameBuffer для потоковой обработки
# -----------------------
class FrameBuffer:
    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None
        self._ts = 0.0

    def set(self, frame):
        with self._lock:
            self._frame = frame
            self._ts = time.time()

    def get(self):
        with self._lock:
            return self._frame, self._ts

# -----------------------
# Цикл чтения кадров в отдельном потоке
# -----------------------
def reader_loop(rtsp_url: str, name: str, direction: str, fb: FrameBuffer, stop_evt: threading.Event):
    cap = None
    last_log = 0.0
    while not stop_evt.is_set():
        try:
            if cap is None or not cap.isOpened():
                if cap:
                    try:
                        cap.release()
                    except Exception:
                        pass
                cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass
                if not cap.isOpened():
                    now = time.time()
                    if now - last_log > 2.0:
                        print(f"❌ Не удалось открыть RTSP {name}/{direction}")
                        last_log = now
                    time.sleep(1.0)
                    continue
                else:
                    print(f"✅ RTSP поток {name}/{direction} открыт")
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue
            fb.set(frame)
        except Exception as e:
            print(f"⚠️ reader_loop exception {name}/{direction}: {e}")
            try:
                if cap:
                    cap.release()
            except Exception:
                pass
            cap = None
            time.sleep(0.5)
    # cleanup
    try:
        if cap:
            cap.release()
    except Exception:
        pass

# -----------------------
# Открытие RTSP-потока (совместимо с processing.py)
# -----------------------
def open_capture(rtsp_url: str, name: str, direction: str, fb: FrameBuffer, stop_evt: threading.Event):
    """Запускает reader_loop в отдельном потоке."""
    threading.Thread(target=reader_loop, args=(rtsp_url, name, direction, fb, stop_evt), daemon=True).start()

# -----------------------
# JPEG кодирование / сохранение миниатюр
# -----------------------
def to_jpeg_bytes(frame_bgr):
    try:
        ok, enc = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if not ok:
            return None
        return enc.tobytes()
    except Exception as e:
        print(f"JPEG encoding error: {e}")
        return None

def save_snapshot(name: str, direction: str, img_bytes: bytes):
    try:
        snapshot_dir = os.path.join("static", "snapshots")
        os.makedirs(snapshot_dir, exist_ok=True)
        fname = f"{name}_{direction}_{int(time.time())}.jpg"
        path = os.path.join(snapshot_dir, fname)
        with open(path, "wb") as f:
            f.write(img_bytes)
        return path
    except Exception as e:
        print(f"Ошибка сохранения миниатюры {name}/{direction}: {e}")
        return None
