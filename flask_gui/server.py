import os
import sys
import time
from flask import Flask, request, jsonify, render_template
import whisper

# -------------------------------------------------------------------
# HIDE FFMPEG CONSOLE WINDOW WITHOUT BREAKING WHISPER
# -------------------------------------------------------------------
import subprocess

if sys.platform == "win32":
    CREATE_NO_WINDOW = 0x08000000
    original_popen = subprocess.Popen

    def silent_popen(*args, **kwargs):
        if isinstance(args[0], (list, tuple)) and "ffmpeg" in args[0][0].lower():
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
        return original_popen(*args, **kwargs)

    subprocess.Popen = silent_popen


# -------------------------------------------------------------------
# Resource Path Helper (for PyInstaller)
# -------------------------------------------------------------------
def resource_path(relative):
    if hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(__file__)
    return os.path.join(base, relative)


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
# Whisper State (LAZY LOADED)
# -------------------------------------------------------------------
device = "cpu"
model_name = "tiny.en.pt"  # default
model_path = resource_path(os.path.join("models", model_name))

USE_FP16 = False  # CPU default
model = None      # <-- IMPORTANT: not loaded yet!


def load_model_if_needed():
    """Load the Whisper model only when first needed."""
    global model, model_path, USE_FP16

    if model is not None:
        return model

    print(f"[Whisper] Lazy loading model: {model_path} (device={device})")
    model = whisper.load_model(model_path, device=device)
    return model


def load_whisper_model(new_model_name, new_device):
    """Force model reload when user switches model or device."""
    global model, device, USE_FP16, model_name, model_path

    device = new_device
    USE_FP16 = device == "cuda"

    model_name = new_model_name
    model_path = resource_path(os.path.join("models", model_name))

    print(f"[Whisper] Reloading model: {model_path} on {device}")

    # drop current model from memory
    model = None

    # do NOT load here — lazy load will handle it


# -------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/bubble")
def bubble():
    return render_template("bubble.html")


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "device": device,
        "fp16": USE_FP16,
        "model": model_name,
        "loaded": model is not None,
    })


@app.route("/get_config")
def get_config():
    models_dir = resource_path("models")
    models = [m for m in os.listdir(models_dir) if m.endswith(".pt")]

    return jsonify({
        "device": device,
        "model": model_name,
        "models": models,
        "loaded": model is not None,
    })


@app.route("/set_device", methods=["POST"])
def set_device():
    data = request.json
    new_device = data.get("device")

    if new_device not in ["cpu", "cuda"]:
        return jsonify({"error": "Invalid device"}), 400

    try:
        load_whisper_model(model_name, new_device)
        return jsonify({"status": "ok", "device": device})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/set_model", methods=["POST"])
def set_model():
    data = request.json
    new_model = data.get("model")

    if not new_model:
        return jsonify({"error": "Missing model"}), 400

    try:
        load_whisper_model(new_model, device)
        return jsonify({"status": "ok", "model": new_model})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "file" not in request.files:
        return jsonify({"error": "Missing 'file'"}), 400

    # LAZY LOAD HAPPENS HERE
    whisper_model = load_model_if_needed()

    audio_file = request.files["file"]
    ts = time.strftime("%Y%m%d_%H%M%S")
    temp_path = os.path.join(TRANSCRIPTS_DIR, f"temp_{ts}.wav")
    audio_file.save(temp_path)

    try:
        result = whisper_model.transcribe(
            temp_path,
            fp16=USE_FP16,
            language="en",
            task="transcribe",
        )
        text = (result.get("text") or "").strip()

        out_path = os.path.join(TRANSCRIPTS_DIR, f"transcript_{ts}.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")

        return jsonify({"text": text, "saved": out_path})

    except Exception as e:
        print("Transcription failed:", e)
        return jsonify({"error": str(e)}), 500

    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except:
            pass


# -------------------------------------------------------------------
# Debug Runner
# -------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
