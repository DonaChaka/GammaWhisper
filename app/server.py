import os
import time
from flask import Flask, request, jsonify, render_template
import torch
import whisper

app = Flask(__name__, template_folder="templates", static_folder="static")

# Prepare transcripts folder
TRANSCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "transcripts")
os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

# Load Whisper with GPU preference
device = "cuda" if torch.cuda.is_available() else "cpu"
model = whisper.load_model("small.en", device=device)
USE_FP16 = device == "cuda"

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
    """
    Expects a multipart/form-data with key 'file' containing audio blob.
    Accepts WAV, MP3, M4A, FLAC.
    """
    if "file" not in request.files:
        return jsonify({"error": "Missing 'file'"}), 400

    audio_file = request.files["file"]
    # Save to temp
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

        # Autosave transcript
        out_path = os.path.join(TRANSCRIPTS_DIR, f"transcript_{ts}.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")

        # Clipboard copy (best-effort: only works inside desktop wrapper)
        # In webview, we’ll copy via JS; backend returns text.
        return jsonify({"text": text, "saved": out_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        # Clean temp
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except:
            pass

if __name__ == "__main__":
    # For dev runs; desktop wrapper will import and run the app in a thread
    app.run(host="127.0.0.1", port=5000, debug=True)