"""
Gemini API proxy server for the school project.
Loads GEMINI_API_KEY from .env and exposes endpoints for the HTML frontends.
"""

import base64
import os
import ssl
from pathlib import Path

import httpx
import urllib3

# Bypass SSL verification for filtered networks (e.g. Rimon) that inject self-signed certs
ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_orig_httpx_init = httpx.Client.__init__
def _httpx_no_verify(self, *args, **kwargs):
    kwargs.setdefault("verify", False)
    _orig_httpx_init(self, *args, **kwargs)
httpx.Client.__init__ = _httpx_no_verify

_orig_httpx_async_init = httpx.AsyncClient.__init__
def _httpx_async_no_verify(self, *args, **kwargs):
    kwargs.setdefault("verify", False)
    _orig_httpx_async_init(self, *args, **kwargs)
httpx.AsyncClient.__init__ = _httpx_async_no_verify

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from google import genai
from google.genai import types

load_dotenv()

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = "gemini-3.6-flash"

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("GEMINI_API_KEY is not set. Add it to a .env file in the project root.")

client = genai.Client(api_key=api_key)

app = Flask(__name__, static_folder=str(ROOT), static_url_path="")
CORS(app)


def _gemini_role(role: str) -> str:
    return "model" if role == "assistant" else "user"


def _build_contents(messages: list) -> list:
    contents = []
    for msg in messages:
        role = _gemini_role(msg.get("role", "user"))
        text = msg.get("content", "")
        if not text:
            continue
        contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
    return contents


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "provider": "gemini"})


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": {"message": "prompt is required"}}), 400

    model = data.get("model") or DEFAULT_MODEL
    max_tokens = int(data.get("max_tokens") or 256)

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=max_tokens),
        )
        text = (response.text or "").strip()
        return jsonify({"text": text})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    messages = data.get("messages") or []
    if not messages:
        return jsonify({"error": {"message": "messages are required"}}), 400

    model = data.get("model") or DEFAULT_MODEL
    system = data.get("system") or ""
    max_tokens = int(data.get("max_tokens") or 1024)

    try:
        config = types.GenerateContentConfig(max_output_tokens=max_tokens)
        if system:
            config.system_instruction = system

        response = client.models.generate_content(
            model=model,
            contents=_build_contents(messages),
            config=config,
        )
        text = response.text or ""
        return jsonify({"content": [{"text": text}]})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/vision", methods=["POST"])
def vision():
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    image_b64 = data.get("image_b64") or ""
    mime_type = data.get("mime_type") or "image/jpeg"

    if not prompt or not image_b64:
        return jsonify({"error": {"message": "prompt and image_b64 are required"}}), 400

    model = data.get("model") or DEFAULT_MODEL
    max_tokens = int(data.get("max_tokens") or 4096)

    try:
        image_bytes = base64.b64decode(image_b64)
        response = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ],
            config=types.GenerateContentConfig(max_output_tokens=max_tokens),
        )
        text = response.text or ""
        return jsonify({"text": text})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/")
def index():
    return send_from_directory(ROOT, "teacher-engine/interactive-teacher.html")


@app.route("/<path:filepath>")
def static_files(filepath: str):
    full_path = ROOT / filepath
    if full_path.is_file():
        return send_from_directory(ROOT, filepath)
    return jsonify({"error": {"message": "Not found"}}), 404


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"Gemini API server running at http://localhost:{port}")
    print("Open teacher-engine/interactive-teacher.html via the server URL above.")
    app.run(host="0.0.0.0", port=port, debug=True)
