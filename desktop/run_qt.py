import threading
import time
import requests
import keyboard
import os
import os
import platform
if platform.system() == "Windows":
    import ctypes
    from importlib.util import find_spec
    try:
        if (spec := find_spec("torch")) and spec.origin and os.path.exists(
            dll_path := os.path.join(os.path.dirname(spec.origin), "lib", "c10.dll")
        ):
            ctypes.CDLL(os.path.normpath(dll_path))
    except Exception:
        pass
import sys
import sounddevice as sd
import soundfile as sf
import numpy as np
import pyperclip

from PyQt5 import QtWidgets, QtCore, QtWebEngineWidgets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, "..", "app")
sys.path.append(APP_DIR)

from server import app

def start_flask():
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)

# Globals
is_recording = False
stream = None
buffer = []
samplerate = 16000
channels = 1
temp_path = os.path.join(APP_DIR, "temp.wav")

def audio_callback(indata, frames, time_info, status):
    if status:
        print(status)
    buffer.append(indata.copy())

def start_recording(view):
    global stream, buffer
    buffer = []
    stream = sd.InputStream(samplerate=samplerate, channels=channels, callback=audio_callback)
    stream.start()
    # Show bubble + waveform animation
    view.page().runJavaScript(
        'document.getElementById("bubble").classList.add("show");'
        'document.getElementById("status").textContent="Listening…";'
        'startWaveform();'
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

    # Update bubble to transcribing
    view.page().runJavaScript(
        'document.getElementById("status").textContent="Transcribing…";'
        'stopWaveform();'
    )

    try:
        if os.path.exists(temp_path):
            with open(temp_path, "rb") as f:
                res = requests.post("http://127.0.0.1:5000/transcribe", files={"file": f})
                text = res.json().get("text", "")
                pyperclip.copy(text)

        # Reset bubble
        view.page().runJavaScript('window.postMessage({type:"reset"}, "*");')
    except Exception as e:
        view.page().runJavaScript(
            f'document.getElementById("status").textContent="Error";'
        )
        view.page().runJavaScript('window.postMessage({type:"reset"}, "*");')
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
        threading.Thread(target=stop_recording_and_transcribe, args=(view,), daemon=True).start()

if __name__ == "__main__":
    # Start Flask in background
    threading.Thread(target=start_flask, daemon=True).start()
    time.sleep(1)

    app_qt = QtWidgets.QApplication(sys.argv)

    # Create transparent frameless window
    view = QtWebEngineWidgets.QWebEngineView()
    view.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
    view.setStyleSheet("background: transparent;")
    view.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool)
    view.setFixedSize(200, 120)

    view.load(QtCore.QUrl("http://127.0.0.1:5000/bubble"))
    view.show()

    # Register global hotkey
    keyboard.add_hotkey("alt+num 0", lambda: toggle_action(view))

    sys.exit(app_qt.exec_())