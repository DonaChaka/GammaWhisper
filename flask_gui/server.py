import os
import sys
import time
import json
import logging
import threading
import gc
import torch
from flask import Flask, request, jsonify, render_template
import whisper
import requests as http_client
import subprocess

# -------------------------------------------------------------------
# Path Helpers for PyInstaller build
# -------------------------------------------------------------------
def resource_path(relative):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.dirname(__file__), relative)

# -------------------------------------------------------------------
# LOGGING SETUP
# -------------------------------------------------------------------
LOG_DIR = resource_path("logs")
os.makedirs(LOG_DIR, exist_ok=True)

server_log_path = os.path.join(LOG_DIR, "server.log")

logger = logging.getLogger("server")
logger.setLevel(logging.INFO)

handler = logging.FileHandler(server_log_path, mode="w", encoding="utf-8")
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
handler.setFormatter(formatter)

if logger.handlers:
    logger.handlers.clear()

logger.addHandler(handler)
logger.info("Server started fresh (log overwritten).")

# -------------------------------------------------------------------
# HIDE FFMPEG CONSOLE WINDOW
# -------------------------------------------------------------------
if sys.platform == "win32":
    CREATE_NO_WINDOW = 0x08000000
    original_popen = subprocess.Popen

    def silent_popen(*args, **kwargs):
        if isinstance(args[0], (list, tuple)) and "ffmpeg" in args[0][0].lower():
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
        return original_popen(*args, **kwargs)

    subprocess.Popen = silent_popen

# -------------------------------------------------------------------
# Flask Setup
# -------------------------------------------------------------------
app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static"),
)

TRANSCRIPTS_DIR = resource_path("transcripts")
os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

# -------------------------------------------------------------------
# Whisper Model State
# -------------------------------------------------------------------
device = "cpu"
model_name = "tiny.en.pt"
model_path = resource_path(os.path.join("models", model_name))
USE_FP16 = False
model = None

# Idle unload system
IDLE_TIMEOUT = 300        # 5 minutes
last_model_use = time.time()

def update_idle_timer():
    global last_model_use
    last_model_use = time.time()

# -------------------------------------------------------------------
# Formatting Profiles
# -------------------------------------------------------------------
FORMAT_CONFIG_PATH = resource_path(os.path.join("config", "format_config.json"))

def load_format_config():
    try:
        with open(FORMAT_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            logger.info("Loaded format_config.json successfully.")
            return cfg
    except Exception as e:
        logger.error(f"Failed to load format_config.json: {e}", exc_info=True)
        return {"formats": {"disable": {"enabled": False}}}

format_config = load_format_config()
format_mode = "disable"

# -------------------------------------------------------------------
# Whisper Lazy Loader
# -------------------------------------------------------------------
def load_model_if_needed():
    global model

    if model is not None:
        return model

    logger.info(f"Lazy-loading Whisper model: {model_path} (device={device})")

    try:
        model = whisper.load_model(model_path, device=device)
    except Exception as e:
        logger.error(f"Failed to load Whisper model: {e}", exc_info=True)
        model = None
        raise

    return model

def load_whisper_model(new_name, new_device):
    global model, model_name, model_path, device, USE_FP16

    device = new_device
    USE_FP16 = (device == "cuda")

    model_name = new_name
    model_path = resource_path(os.path.join("models", new_name))

    # Mark model for reload next time
    model = None
    logger.info(f"Whisper model selected: {model_path} (device={device}) — will reload on next use")

# -------------------------------------------------------------------
# Memory Watchdog: unload Whisper when idle
# -------------------------------------------------------------------
def memory_watchdog():
    global model, last_model_use

    while True:
        time.sleep(30)

        if model is None:
            continue

        idle = time.time() - last_model_use

        if idle > IDLE_TIMEOUT:
            logger.info(f"Idle timeout reached ({int(idle)}s). Unloading Whisper model...")

            try:
                del model
                model = None

                gc.collect()

                if device == "cuda":
                    torch.cuda.empty_cache()
                    try:
                        torch.cuda.ipc_collect()
                    except:
                        pass

                logger.info("Whisper successfully unloaded from memory.")

            except Exception as e:
                logger.error(f"Error during Whisper unload: {e}", exc_info=True)

threading.Thread(target=memory_watchdog, daemon=True).start()

# -------------------------------------------------------------------
# MORE THEMES!
# -------------------------------------------------------------------
theme_mode = "style_black.css"

def get_available_themes():
    static_dir = resource_path("static")
    return [f for f in os.listdir(static_dir) if f.startswith("style") and f.endswith(".css")]

# -------------------------------------------------------------------
# ROUTES
# -------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/bubble")
def bubble():
    return render_template("bubble.html", theme=theme_mode, timestamp=time.time())

@app.route("/get_config")
def get_config():
    try:
        models = [
            m for m in os.listdir(resource_path("models"))
            if m.endswith(".pt")
        ]
    except Exception as e:
        logger.error(f"Error listing models: {e}", exc_info=True)
        models = []

    return jsonify({
        "device": device,
        "model": model_name,
        "models": models,
        "loaded": model is not None,
        "format": format_mode,
        "available_formats": list(format_config.get("formats", {}).keys()),
        "themes": get_available_themes(),
        "theme": theme_mode
    })

@app.route("/set_device", methods=["POST"])
def set_device():
    data = request.json
    new_device = data.get("device")

    if new_device not in ["cpu", "cuda"]:
        logger.warning(f"Invalid device requested: {new_device}")
        return jsonify({"error": "Invalid device"}), 400

    load_whisper_model(model_name, new_device)
    logger.info(f"Device changed to {new_device}")
    return jsonify({"status": "ok"})

@app.route("/set_model", methods=["POST"])
def set_model():
    data = request.json
    new_model = data.get("model")

    if not new_model:
        logger.warning("Missing model in set_model request")
        return jsonify({"error": "Missing model"}), 400

    load_whisper_model(new_model, device)
    logger.info(f"Model changed to {new_model}")
    return jsonify({"status": "ok"})

@app.route("/set_format", methods=["POST"])
def set_format():
    global format_mode
    data = request.json
    mode = data.get("format")

    if mode not in format_config.get("formats", {}):
        logger.warning(f"Unknown format profile: {mode}")
        return jsonify({"error": "Unknown format profile"}), 400

    format_mode = mode
    logger.info(f"Formatting mode set to {format_mode}")
    return jsonify({"status": "ok"})

@app.route("/set_theme", methods=["POST"])
def set_theme():
    global theme_mode
    data = request.json
    theme = data.get("theme")

    if theme not in get_available_themes():
        logger.warning(f"Invalid theme: {theme}")
        return jsonify({"error": "Invalid theme"}), 400

    theme_mode = theme
    logger.info(f"Theme changed to {theme_mode}")
    return jsonify({"status": "ok", "theme": theme_mode})

# -------------------------------------------------------------------
# APPLY LLM FORMATTING
# -------------------------------------------------------------------
@app.route("/format_text", methods=["POST"])
def format_text():
    global format_mode, format_config
    update_idle_timer()

    data = request.json
    text = data.get("text", "")

    if not text:
        logger.warning("Formatting request missing text.")
        return jsonify({"error": "missing text"}), 400

    profile = format_config.get("formats", {}).get(format_mode, {})

    if not profile.get("enabled", False):
        return jsonify({"text": text})

    model_name = profile.get("model")
    system_prompt = profile.get("system_prompt", "")
    options = profile.get("options", {})

    payload = {
        "model": model_name,
        "stream": False,
        "options": options,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]
    }

    try:
        logger.info(f"Sending format request (profile={format_mode})")
        r = http_client.post("http://localhost:11434/api/chat", json=payload)
        r_json = r.json()
        formatted = r_json.get("message", {}).get("content", text)
        return jsonify({"text": formatted})

    except Exception as e:
        logger.error(f"Formatting failed: {e}", exc_info=True)
        return jsonify({"text": text})

# -------------------------------------------------------------------
# TRANSCRIBE
# -------------------------------------------------------------------
@app.route("/transcribe", methods=["POST"])
def transcribe():
    update_idle_timer()

    if "file" not in request.files:
        logger.warning("Missing audio file in request.")
        return jsonify({"error": "Missing 'file'"}), 400

    whisper_model = load_model_if_needed()

    audio_file = request.files["file"]
    ts = time.strftime("%Y%m%d_%H%M%S")
    temp_path = os.path.join(TRANSCRIPTS_DIR, f"temp_{ts}.wav")
    audio_file.save(temp_path)

    try:
        logger.info("Starting transcription...")
        result = whisper_model.transcribe(
            temp_path, fp16=USE_FP16, language="en", task="transcribe"
        )
        text = (result.get("text") or "").strip()
        logger.info("Transcription successful.")
        return jsonify({"text": text})

    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

    finally:
        try:
            os.remove(temp_path)
        except:
            pass

# -------------------------------------------------------------------
# DEBUG RUN
# -------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Server running in debug mode.")
    app.run(host="127.0.0.1", port=5000, debug=True)
