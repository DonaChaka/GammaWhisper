import threading
import webview
import time
import requests
import keyboard
import os
import sys
import sounddevice as sd
import soundfile as sf
import numpy as np
import pyperclip

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

def start_recording():
    global stream, buffer
    buffer = []
    stream = sd.InputStream(samplerate=samplerate, channels=channels, callback=audio_callback)
    stream.start()
    # Show bubble + waveform animation
    webview.windows[0].evaluate_js(
        'document.getElementById("bubble").classList.add("show");'
        'document.getElementById("status").textContent="Listening…";'
        'startWaveform();'
    )

def stop_recording_and_transcribe():
    global stream, buffer
    if stream:
        stream.stop()
        stream.close()
        stream = None

    # Save audio if we have samples
    if buffer:
        audio = np.concatenate(buffer, axis=0)
        sf.write(temp_path, audio, samplerate)

    # Update bubble to transcribing
    webview.windows[0].evaluate_js(
        'document.getElementById("status").textContent="Transcribing…";'
        'stopWaveform();'
    )

    # Send audio to backend
    try:
        if os.path.exists(temp_path):
            with open(temp_path, "rb") as f:
                res = requests.post("http://127.0.0.1:5000/transcribe", files={"file": f})
                text = res.json().get("text", "")
                pyperclip.copy(text)

        # Reset bubble to initial empty/hidden state
        webview.windows[0].evaluate_js('window.postMessage({type:"reset"}, "*");')
    except Exception as e:
        # Show error briefly, then reset
        webview.windows[0].evaluate_js(
            f'document.getElementById("status").textContent="Error";'
        )
        webview.windows[0].evaluate_js('window.postMessage({type:"reset"}, "*");')
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def toggle_action():
    global is_recording
    if not is_recording:
        is_recording = True
        start_recording()
    else:
        is_recording = False
        threading.Thread(target=stop_recording_and_transcribe, daemon=True).start()

if __name__ == "__main__":
    # Start Flask in background
    threading.Thread(target=start_flask, daemon=True).start()
    time.sleep(1)  # wait for Flask to boot

    # Register global hotkey
    keyboard.add_hotkey("alt+num 0", toggle_action)

    # Create bubble window (frameless capsule)
    window = webview.create_window(
        title="Superwhisper",
        url="http://127.0.0.1:5000/bubble",
        width=200,
        height=120,
        frameless=True,
        transparent=True,
        resizable=False,
        easy_drag=True
    )

    # Start webview loop on main thread
    webview.start(
        gui="edgechromium"
        )

    