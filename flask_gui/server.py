import os
import sys
import time
from flask import Flask, request, jsonify, render_template
import torch
import whisper

# -------------------------------------------------------------------
# Helper for PyInstaller (access files inside _MEIPASS)
# -------------------------------------------------------------------
def resource_path(relative):
    """Return absolute path to resource, works in dev & PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(__file__)
    return os.path.join(base, relative)


# -------------------------------------------------------------------
# Flask App Setup
# -------------------------------------------------------------------
app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static")
)

# Prepare transcripts directory
TRANSCRIPTS_DIR = resource_path("transcripts")
os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)


# -------------------------------------------------------------------
# Whisper Initialization
# -------------------------------------------------------------------
device = "cuda" if torch.cuda.is_available() else "cpu"
model = whisper.load_model("small.en", device=device)
USE_FP16 = device == "cuda"


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
        "fp16": USE_FP16
    })


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if "file" not in request.files:
        return jsonify({"error": "Missing 'file'"}), 400

    audio_file = request.files["file"]

    # Temporary save location
    ts = time.strftime("%Y%m%d_%H%M%S")
    temp_path = os.path.join(TRANSCRIPTS_DIR, f"temp_{ts}.wav")
    audio_file.save(temp_path)

    try:
        result = model.transcribe(
            temp_path,
            fp16=USE_FP16,
            language="en",
            task="transcribe"
        )
        text = (result.get("text") or "").strip()

        # Save transcript automatically
        out_path = os.path.join(TRANSCRIPTS_DIR, f"transcript_{ts}.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")

        return jsonify({"text": text, "saved": out_path})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        # Clean temp file
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except:
            pass


# -------------------------------------------------------------------
# Debug runner
# -------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
