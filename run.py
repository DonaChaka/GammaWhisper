import os
import sys
import subprocess
import time
import signal
import threading
import ctypes
import ctypes.wintypes as wintypes
import tempfile
import logging

import requests
import numpy as np
import sounddevice as sd
import soundfile as sf
from functools import partial
import psutil

from PyQt5 import QtWidgets, QtCore, QtWebEngineWidgets, QtGui
from PyQt5.QtGui import QIcon


# ===================================================================
# Path Helpers
# ===================================================================
def resource_path(relative):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.dirname(__file__), 'flask_gui', relative)


# ===================================================================
# Logging
# ===================================================================
LOG_DIR = resource_path('logs')
os.makedirs(LOG_DIR, exist_ok=True)

run_log_path = os.path.join(LOG_DIR, "run.log")

logger = logging.getLogger("run")
logger.setLevel(logging.INFO)

handler = logging.FileHandler(run_log_path, mode="w", encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

if logger.handlers:
    logger.handlers.clear()

logger.addHandler(handler)
logger.info("run.py started (log overwritten).")


# ===================================================================
# Global Hotkey + Flask Import
# ===================================================================
user32 = ctypes.windll.user32
HOTKEY_ID = 1
MOD_ALT = 0x0001
VK_S = 0x53
WM_HOTKEY = 0x0312
shutdown_event = threading.Event()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, "flask_gui")
sys.path.append(APP_DIR)

from flask_gui.server import app


# ===================================================================
# Flask + Ollama Startup
# ===================================================================
def start_flask():
    logger.info("Starting Flask backend...")
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


def start_ollama():
    for proc in psutil.process_iter(attrs=['pid', 'name']):
        if 'ollama' in proc.info['name'].lower():
            logger.info("Ollama is already running.")
            return True

    logger.info("Starting Ollama...")
    ollama_exe = r"C:\Users\Work.LAPTOP-JOMS87TS\AppData\Local\Programs\Ollama\ollama.exe"
    subprocess.Popen([ollama_exe, "run", "qwen2.5:1.5b-instruct"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return True


# ===================================================================
# Audio Capture
# ===================================================================
is_recording = False
stream = None
buffer = []
samplerate = 16000
channels = 1

temp_path = os.path.join(tempfile.gettempdir(), "gammawhisper_temp.wav")


def audio_callback(indata, frames, time_info, status):
    if status:
        logger.warning(f"Audio callback status: {status}")
    buffer.append(indata.copy())


def enable_sigint_handler():
    timer = QtCore.QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(100)
    return timer


# ===================================================================
# Bubble Window
# ===================================================================
class BubbleWindow(QtWidgets.QWidget):
    hotkey_trigger = QtCore.pyqtSignal()
    copy_to_clipboard = QtCore.pyqtSignal(str)

    def __init__(self, width=220, height=140):
        super().__init__(
            None,
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowStaysOnTopHint
        )

        start_ollama()
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.resize(width, height)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = QtWebEngineWidgets.QWebEngineView(self)
        self.view.setContextMenuPolicy(QtCore.Qt.NoContextMenu)
        self.view.page().setBackgroundColor(QtCore.Qt.transparent)
        layout.addWidget(self.view)

        self.view.load(QtCore.QUrl("http://127.0.0.1:5000/bubble"))

        self.hotkey_trigger.connect(lambda: toggle_action(self))
        self.copy_to_clipboard.connect(self._copy_text)

        screen = QtWidgets.QApplication.primaryScreen()
        rect = screen.availableGeometry()
        self.move(rect.center().x() - width // 2 + 100, rect.top() - 30)

        logger.info("BubbleWindow initialized.")

    def _copy_text(self, text):
        QtGui.QGuiApplication.clipboard().setText(text)
        logger.info("Clipboard updated.")

    def contextMenuEvent(self, event):
        menu = QtWidgets.QMenu(self)

        cfg = self.fetch_config()
        current_device = cfg.get("device", "cpu")
        current_model = cfg.get("model", "")
        models = cfg.get("models", [])
        current_format = cfg.get("format", "disable")
        available_formats = cfg.get("available_formats", [])

        # Device
        device_menu = menu.addMenu("Set Device")
        cpu_action = device_menu.addAction("CPU")
        cuda_action = device_menu.addAction("CUDA")

        cpu_action.setCheckable(True)
        cuda_action.setCheckable(True)
        cpu_action.setChecked(current_device == "cpu")
        cuda_action.setChecked(current_device == "cuda")

        # Core Models
        model_menu = menu.addMenu("Core Model")
        for m in models:
            action = model_menu.addAction(m)
            action.setCheckable(True)
            action.setChecked(m == current_model)
            action.triggered.connect(partial(self.change_model, m))

        # Post-Process
        format_menu = menu.addMenu("Post-Process")
        for fmt in available_formats:
            act = format_menu.addAction(fmt)
            act.setCheckable(True)
            act.setChecked(fmt == current_format)
            act.triggered.connect(lambda checked, name=fmt: self.set_format_request(name))

        format_config_action = format_menu.addAction("(edit config)")

        # Themes
        theme_menu = menu.addMenu("Theme")
        available_themes = cfg.get("themes", [])
        current_theme = cfg.get("theme", "style_black.css")

        for theme in available_themes:
            act = theme_menu.addAction(theme)
            act.setCheckable(True)
            act.setChecked(theme == current_theme)
            act.triggered.connect(lambda checked, name=theme: self.set_theme_request(name))

        restart_action = menu.addAction("Restart")
        exit_action = menu.addAction("Exit")

        selected = menu.exec_(self.mapToGlobal(event.pos()))

        if selected == restart_action:
            self.restart_app()
        elif selected == exit_action:
            logger.info("Exit requested.")
            shutdown_event.set()
            QtWidgets.QApplication.quit()
        elif selected == format_config_action:
            self.open_format_config()
        elif selected == cpu_action:
            self.set_device_request("cpu")
        elif selected == cuda_action:
            self.set_device_request("cuda")

    # ---------------- Server Communication ----------------

    def fetch_config(self):
        try:
            return requests.get("http://127.0.0.1:5000/get_config").json()
        except Exception as e:
            logger.error(f"Failed to fetch config: {e}", exc_info=True)
            return {"device": "cpu", "model": "", "models": [], "format": "disable"}

    def set_device_request(self, dev):
        try:
            requests.post("http://127.0.0.1:5000/set_device", json={"device": dev})
            logger.info(f"Device changed to {dev}")
        except Exception as e:
            logger.error(f"Failed to set device: {e}", exc_info=True)

    def change_model(self, model_name):
        try:
            requests.post("http://127.0.0.1:5000/set_model", json={"model": model_name})
            logger.info(f"Model changed to {model_name}")
        except Exception as e:
            logger.error(f"Failed to change model: {e}", exc_info=True)

    def set_format_request(self, value):
        try:
            requests.post("http://127.0.0.1:5000/set_format", json={"format": value})
            logger.info(f"Format mode changed to {value}")
        except Exception as e:
            logger.error(f"Failed to change format: {e}", exc_info=True)

    def set_theme_request(self, theme):
        try:
            requests.post("http://127.0.0.1:5000/set_theme", json={"theme": theme})
            logger.info(f"Theme set to: {theme}")
            self.view.reload()
        except Exception as e:
            logger.error(f"Failed to change theme: {e}", exc_info=True)

    def restart_app(self):
        logger.info("Restarting application...")
        if getattr(sys, 'frozen', False):
            subprocess.Popen([sys.executable])
        else:
            subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0])])

        shutdown_event.set()
        QtWidgets.QApplication.quit()

    def open_format_config(self):
        cfg_path = resource_path(os.path.join("config", "format_config.json"))
        try:
            os.startfile(cfg_path)
        except Exception as e:
            logger.error(f"Failed to open format_config.json: {e}", exc_info=True)


# ===================================================================
# Recording + Transcription
# ===================================================================
def start_recording(view):
    global stream, buffer

    buffer = []
    stream = sd.InputStream(samplerate=samplerate, channels=channels, callback=audio_callback)
    stream.start()
    logger.info("Recording started.")

    view.view.page().runJavaScript(
        'document.getElementById("bubble").classList.add("show");'
        'document.getElementById("status").textContent="Listening";'
        "startWaveform();"
    )


def paste_text():
    user32.keybd_event(0x11, 0, 0, 0)
    user32.keybd_event(0x56, 0, 0, 0)
    user32.keybd_event(0x56, 0, 2, 0)
    user32.keybd_event(0x11, 0, 2, 0)
    logger.info("Pasted text via Ctrl+V simulation.")


def stop_recording_and_transcribe(view):
    global stream, buffer

    if stream:
        stream.stop()
        stream.close()
        stream = None

    logger.info("Recording stopped.")

    if buffer:
        audio = np.concatenate(buffer, axis=0)
        sf.write(temp_path, audio, samplerate)
        logger.info("Temporary audio file written.")

    view.view.page().runJavaScript(
        'document.getElementById("status").textContent="Transcribing…";'
        "stopWaveform();"
    )

    try:
        if os.path.exists(temp_path):
            with open(temp_path, "rb") as f:
                res = requests.post("http://127.0.0.1:5000/transcribe", files={"file": f})
                text = (res.json() or {}).get("text", "")

                # Formatting
                try:
                    cfg = requests.get("http://127.0.0.1:5000/get_config").json()
                    mode = cfg.get("format", "disable")

                    if mode != "disable":
                        fmt = requests.post("http://127.0.0.1:5000/format_text", json={"text": text})
                        if fmt.ok:
                            text = fmt.json().get("text", text)

                except Exception as e:
                    logger.error(f"Formatting failed: {e}", exc_info=True)

                view.copy_to_clipboard.emit(text)
                threading.Thread(target=paste_text, daemon=True).start()

        view.view.page().runJavaScript('window.postMessage({type:"reset"}, "*");')

    except Exception as e:
        logger.error(f"Transcription error: {e}", exc_info=True)
        view.view.page().runJavaScript('document.getElementById("status").textContent="Error";')
        view.view.page().runJavaScript('window.postMessage({type:"reset"}, "*");')

    finally:
        try:
            os.remove(temp_path)
        except:
            pass


def toggle_action(view):
    global is_recording
    if not is_recording:
        is_recording = True
        start_recording(view)
    else:
        is_recording = False
        threading.Thread(target=stop_recording_and_transcribe, args=(view,), daemon=True).start()


# ===================================================================
# Hotkey Listener
# ===================================================================
def hotkey_listener(emitter: BubbleWindow):
    if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_ALT, VK_S):
        logger.error("Failed to register ALT+S hotkey")
        return

    msg = wintypes.MSG()
    logger.info("Hotkey listener active.")

    while not shutdown_event.is_set():
        if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                emitter.hotkey_trigger.emit()
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)

    user32.UnregisterHotKey(None, HOTKEY_ID)
    logger.info("Hotkey unregistered.")


# ===================================================================
# Clean Exit
# ===================================================================
def handle_sigint(signum, frame):
    logger.info("SIGINT received. Shutting down...")
    shutdown_event.set()
    QtWidgets.QApplication.quit()

signal.signal(signal.SIGINT, handle_sigint)


# ===================================================================
# Main
# ===================================================================
if __name__ == "__main__":
    threading.Thread(target=start_flask, daemon=True).start()
    time.sleep(1)

    app_qt = QtWidgets.QApplication(sys.argv)

    bubble = BubbleWindow()
    bubble.show()

    threading.Thread(target=hotkey_listener, args=(bubble,), daemon=True).start()
    enable_sigint_handler()

    logger.info("Qt app execution started.")
    sys.exit(app_qt.exec_())
