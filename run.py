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

from PyQt5 import QtWidgets, QtCore, QtWebEngineWidgets, QtGui

# -------------------------------------------------------------------
# GLOBAL HOTKEY VALUES
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

from flask_gui.server import app  # noqa: E402


# -------------------------------------------------------------------
# FLASK SERVER
# -------------------------------------------------------------------
def start_flask():
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


# -------------------------------------------------------------------
# AUDIO GLOBALS
# -------------------------------------------------------------------
is_recording = False
stream = None
buffer = []
samplerate = 16000
channels = 1

# Use secure temp directory instead of write-protected PyInstaller folder
temp_path = os.path.join(tempfile.gettempdir(), "gammawhisper_temp.wav")


def audio_callback(indata, frames, time_info, status):
    if status:
        print(status)
    buffer.append(indata.copy())


def enable_sigint_handler():
    """Ensure Python SIGINT (Ctrl+C) is processed while Qt event loop runs."""
    timer = QtCore.QTimer()
    timer.timeout.connect(lambda: None)  # dummy slot
    timer.start(100)  # every 100ms
    return timer


# -------------------------------------------------------------------
# MAIN TRANSPARENT WINDOW
# -------------------------------------------------------------------
class BubbleWindow(QtWidgets.QWidget):
    hotkey_trigger = QtCore.pyqtSignal()
    copy_to_clipboard = QtCore.pyqtSignal(str)  # NEW SIGNAL FOR SAFE CLIPBOARD ACCESS

    def __init__(self, width=220, height=140):
        super().__init__(None, QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool)

        # Window setup
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowStaysOnTopHint
        )
        self.resize(width, height)

        # Layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Web content
        self.view = QtWebEngineWidgets.QWebEngineView(self)
        self.view.setStyleSheet("background: transparent;")
        self.view.page().setBackgroundColor(QtCore.Qt.transparent)
        self.view.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        layout.addWidget(self.view)

        # Load bubble UI
        self.view.load(QtCore.QUrl("http://127.0.0.1:5000/bubble"))

        # Connect hotkey activation
        self.hotkey_trigger.connect(lambda: toggle_action(self))

        # Connect clipboard signal to GUI-safe handler
        self.copy_to_clipboard.connect(self._copy_text)

        # Position bubble at bottom center of screen
        screen = QtWidgets.QApplication.primaryScreen()
        rect = screen.availableGeometry()
        x = rect.center().x() - (self.width() // 2)
        y = rect.bottom() - 30  # adjust offset above taskbar
        self.move(x, y)

    def _copy_text(self, text):
        """Clipboard updates MUST run on the GUI thread (Qt signal)."""
        QtWidgets.QApplication.clipboard().setText(text)
        print("Clipboard updated:", text)


# -------------------------------------------------------------------
# RECORDING / JS INTERACTION
# -------------------------------------------------------------------
def start_recording(view):
    global stream, buffer
    buffer = []
    stream = sd.InputStream(
        samplerate=samplerate,
        channels=channels,
        callback=audio_callback,
    )
    stream.start()

    view.view.page().runJavaScript(
        'document.getElementById("bubble").classList.add("show");'
        'document.getElementById("status").textContent="Listening";'
        "startWaveform();"
    )


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
                    "http://127.0.0.1:5000/transcribe", files={"file": f}
                )
                data = res.json()
                text = data.get("text", "") if data else ""

                # COPY TO CLIPBOARD SAFELY (GUI THREAD)
                view.copy_to_clipboard.emit(text)

        view.view.page().runJavaScript('window.postMessage({type:"reset"}, "*");')

    except Exception as e:
        print("Transcription error:", e)
        view.view.page().runJavaScript(
            'document.getElementById("status").textContent="Error";'
        )
        view.view.page().runJavaScript('window.postMessage({type:"reset"}, "*");')

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def toggle_action(view):
    global is_recording
    if not is_recording:
        is_recording = True
        start_recording(view)
    else:
        is_recording = False
        threading.Thread(
            target=stop_recording_and_transcribe, args=(view,), daemon=True
        ).start()


# -------------------------------------------------------------------
# HOTKEY LISTENER THREAD
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
# HANDLE CTRL+C CLEANLY
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

    # Start hotkey listener thread
    threading.Thread(target=hotkey_listener, args=(bubble,), daemon=True).start()

    # Keep Python signals alive inside Qt loop
    sigint_timer = enable_sigint_handler()

    sys.exit(app_qt.exec_())
