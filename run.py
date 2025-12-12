import os
import sys
import time
import signal
import threading
import ctypes
import ctypes.wintypes as wintypes
import tempfile

import requests
import numpy as np
import sounddevice as sd
import soundfile as sf
from functools import partial

from PyQt5 import QtWidgets, QtCore, QtWebEngineWidgets, QtGui

# -------------------------------------------------------------------
# GLOBAL HOTKEYS
# -------------------------------------------------------------------
user32 = ctypes.windll.user32
HOTKEY_ID = 1
MOD_ALT = 0x0001
VK_NUMPAD0 = 0x60
WM_HOTKEY = 0x0312

shutdown_event = threading.Event()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, "flask_gui")
sys.path.append(APP_DIR)

from flask_gui.server import app


# -------------------------------------------------------------------
# FLASK SERVER THREAD
# -------------------------------------------------------------------
def start_flask():
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


# -------------------------------------------------------------------
# AUDIO CAPTURE
# -------------------------------------------------------------------
is_recording = False
stream = None
buffer = []
samplerate = 16000
channels = 1

temp_path = os.path.join(tempfile.gettempdir(), "gammawhisper_temp.wav")


def audio_callback(indata, frames, time_info, status):
    if status:
        print(status)
    buffer.append(indata.copy())


def enable_sigint_handler():
    timer = QtCore.QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(100)
    return timer


# -------------------------------------------------------------------
# MAIN BUBBLE WINDOW
# -------------------------------------------------------------------
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

        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.resize(width, height)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = QtWebEngineWidgets.QWebEngineView(self)
        self.view.setContextMenuPolicy(QtCore.Qt.NoContextMenu)
        self.view.page().setBackgroundColor(QtCore.Qt.transparent)
        self.view.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        layout.addWidget(self.view)
        self.view.load(QtCore.QUrl("http://127.0.0.1:5000/bubble"))

        self.hotkey_trigger.connect(lambda: toggle_action(self))
        self.copy_to_clipboard.connect(self._copy_text)

        screen = QtWidgets.QApplication.primaryScreen()
        rect = screen.availableGeometry()
        self.move(rect.center().x() - width // 2 + 100, rect.top() - 30)

    def _copy_text(self, text):
        QtGui.QGuiApplication.clipboard().setText(text)
        print("Clipboard updated:", text)

    def contextMenuEvent(self, event):
        menu = QtWidgets.QMenu(self)

        cfg = self.fetch_config()
        current_device = cfg.get("device", "cpu")
        current_model = cfg.get("model", "")
        models = cfg.get("models", [])

        # Device submenu
        device_menu = menu.addMenu("Set Device")
        cpu_action = device_menu.addAction("CPU")
        cuda_action = device_menu.addAction("CUDA")

        cpu_action.setCheckable(True)
        cuda_action.setCheckable(True)
        cpu_action.setChecked(current_device == "cpu")
        cuda_action.setChecked(current_device == "cuda")

        # Model submenu
        model_menu = menu.addMenu("Set Model")
        for m in models:
            action = model_menu.addAction(m)
            action.setCheckable(True)
            action.setChecked(m == current_model)
            action.triggered.connect(partial(self.change_model, m))

        exit_action = menu.addAction("Exit")
        selected = menu.exec_(self.mapToGlobal(event.pos()))

        if selected == exit_action:
            shutdown_event.set()
            QtWidgets.QApplication.quit()
        elif selected == cpu_action:
            self.set_device_request("cpu")
        elif selected == cuda_action:
            self.set_device_request("cuda")

    # ----------------------
    # Server communication
    # ----------------------
    def fetch_config(self):
        try:
            return requests.get("http://127.0.0.1:5000/get_config").json()
        except:
            return {"device": "cpu", "model": "", "models": []}

    def set_device_request(self, dev):
        try:
            requests.post("http://127.0.0.1:5000/set_device", json={"device": dev})
            print(f"Device changed to: {dev}")
        except Exception as e:
            print("Failed to set device:", e)

    def change_model(self, model_name):
        try:
            requests.post("http://127.0.0.1:5000/set_model", json={"model": model_name})
            print(f"Model changed to: {model_name}")
        except Exception as e:
            print("Failed to change model:", e)


# -------------------------------------------------------------------
# RECORDING + TRANSCRIPTION PIPELINE
# -------------------------------------------------------------------
def start_recording(view):
    global stream, buffer
    buffer = []

    stream = sd.InputStream(
        samplerate=samplerate,
        channels=channels,
        callback=audio_callback
    )
    stream.start()

    view.view.page().runJavaScript(
        'document.getElementById("bubble").classList.add("show");'
        'document.getElementById("status").textContent="Listening";'
        "startWaveform();"
    )


# -------------------------------------------------------------------
# PASTE FUNCTION (Better than typing)
# -------------------------------------------------------------------
def paste_text():
    """Simulate Ctrl+V paste."""
    # CTRL down
    user32.keybd_event(0x11, 0, 0, 0)
    # V down/up
    user32.keybd_event(0x56, 0, 0, 0)
    user32.keybd_event(0x56, 0, 2, 0)
    # CTRL up
    user32.keybd_event(0x11, 0, 2, 0)


# -------------------------------------------------------------------
# TRANSCRIBE + AUTO-PASTE
# -------------------------------------------------------------------
def stop_recording_and_transcribe(view):
    global stream, buffer

    if stream:
        stream.stop()
        stream.close()
        stream = None

    if buffer:
        audio = np.concatenate(buffer, axis=0)
        sf.write(temp_path, audio, samplerate)

    view.view.page().runJavaScript(
        'document.getElementById("status").textContent="Transcribing…";'
        "stopWaveform();"
    )

    try:
        if os.path.exists(temp_path):
            with open(temp_path, "rb") as f:
                res = requests.post(
                    "http://127.0.0.1:5000/transcribe",
                    files={"file": f}
                )
                text = (res.json() or {}).get("text", "")

                view.copy_to_clipboard.emit(text)
                threading.Thread(target=paste_text, daemon=True).start()

        view.view.page().runJavaScript('window.postMessage({type:"reset"}, "*");')

    except Exception as e:
        print("Transcription error:", e)
        view.view.page().runJavaScript(
            'document.getElementById("status").textContent="Error";'
        )
        view.view.page().runJavaScript('window.postMessage({type:"reset"}, "*");')

    finally:
        try:
            if os.path.exists(temp_path):
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
        threading.Thread(
            target=stop_recording_and_transcribe,
            args=(view,),
            daemon=True
        ).start()


# -------------------------------------------------------------------
# HOTKEY LISTENER
# -------------------------------------------------------------------
def hotkey_listener(emitter: BubbleWindow):
    if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_ALT, VK_NUMPAD0):
        print("Failed to register hotkey ALT+NUMPAD0")
        return

    msg = wintypes.MSG()

    while not shutdown_event.is_set():
        if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                emitter.hotkey_trigger.emit()

            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        time.sleep(0.01)

    user32.UnregisterHotKey(None, HOTKEY_ID)


# -------------------------------------------------------------------
# CLEAN EXIT
# -------------------------------------------------------------------
def handle_sigint(signum, frame):
    print("Shutting down...")
    shutdown_event.set()
    QtWidgets.QApplication.quit()


signal.signal(signal.SIGINT, handle_sigint)


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------
if __name__ == "__main__":
    threading.Thread(target=start_flask, daemon=True).start()
    time.sleep(1)

    app_qt = QtWidgets.QApplication(sys.argv)

    bubble = BubbleWindow()
    bubble.show()

    threading.Thread(target=hotkey_listener, args=(bubble,), daemon=True).start()
    enable_sigint_handler()

    sys.exit(app_qt.exec_())
