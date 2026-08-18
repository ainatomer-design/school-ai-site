"""
אתר בית ספר עם עוזר AI — פרויקט הגשה.
Flask + Gemini + Supabase. רץ מקומית או ב-Railway.
"""

import os
import json
import time
from pathlib import Path

import ssl
import requests
import httpx
import urllib3
from dotenv import load_dotenv

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
from flask import Flask, jsonify, request, send_from_directory, session, redirect
from flask_cors import CORS
from google import genai
from google.genai import types

try:
    import anthropic as _anthropic
    _ANTHROPIC_OK = True
except ImportError:
    _ANTHROPIC_OK = False

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")
STATIC = ROOT / "static"
SCHOOL_ID = "default"
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
APP_VERSION = "2.1-multi-provider"

app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
app.secret_key = os.getenv("SECRET_KEY", "koors-school-secret-2025")
CORS(app)

DEFAULT_STATE = {
    "school": {
        "name": "בית ספר הדגמה",
        "year": 'תשפ"ו',
        "motto": "לומדים חכם — עם עוזר AI",
        "email": "school@example.org.il",
    },
    "colors": {
        "primary": "#1a73e8",
        "secondary": "#fbbc04",
        "accent": "#34a853",
        "bg": "#f0f4f8",
    },
    "classes": [
        {
            "id": "c1",
            "name": "כיתה ד'1",
            "teacher": "רותי כהן",
            "room": "12",
            "subjects": ["עברית", "מתמטיקה", "מדעים"],
        },
        {
            "id": "c2",
            "name": "כיתה ה'2",
            "teacher": "יוסי לוי",
            "room": "8",
            "subjects": ["תורה", "אנגלית"],
        },
    ],
    "staff": [
        {"id": "t1", "name": "רותי כהן", "role": "מחנכת ד'1", "phone": ""},
        {"id": "t2", "name": "יוסי לוי", "role": "מחנך ה'2", "phone": ""},
    ],
    "links": [
        {"id": "l1", "icon": "📅", "text": "מערכת שעות", "url": "#", "color": "#1a73e8"},
        {"id": "l2", "icon": "📚", "text": "חומרי למידה", "url": "#", "color": "#34a853"},
        {"id": "l3", "icon": "📧", "text": "יצירת קשר", "url": "#", "color": "#ea4335"},
        {"id": "l4", "icon": "🎮", "text": "משחקים", "url": "#", "color": "#9c27b0"},
    ],
    "announcement": {
        "active": True,
        "text": "ברוכים הבאים לאתר בית הספר — התוכן מנוהל עם עוזר AI ונשמר ב-Supabase.",
        "type": "info",
    },
}


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def supabase_config():
    url = _env("SUPABASE_URL").rstrip("/")
    key = _env("SUPABASE_SERVICE_ROLE_KEY") or _env("SUPABASE_KEY")
    return url, key


def sb_headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def sb_request(method: str, path: str, **kwargs):
    url, key = supabase_config()
    if not url or not key:
        raise RuntimeError("חסרים מפתחות Supabase. הגדירו SUPABASE_URL ו-SUPABASE_SERVICE_ROLE_KEY.")
    res = requests.request(
        method,
        f"{url}/rest/v1/{path}",
        headers=sb_headers(key),
        timeout=20,
        verify=False,
        **kwargs,
    )
    if res.status_code >= 400:
        raise RuntimeError(f"Supabase {res.status_code}: {res.text[:400]}")
    if not res.content:
        return None
    return res.json()


def load_state() -> dict:
    rows = sb_request("GET", f"school_state?id=eq.{SCHOOL_ID}&select=payload")
    if rows:
        payload = rows[0].get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload
    sb_request(
        "POST",
        "school_state",
        json={"id": SCHOOL_ID, "payload": DEFAULT_STATE},
    )
    return json.loads(json.dumps(DEFAULT_STATE))


def save_state(payload: dict) -> dict:
    rows = sb_request("GET", f"school_state?id=eq.{SCHOOL_ID}&select=id")
    if rows:
        result = sb_request("PATCH", f"school_state?id=eq.{SCHOOL_ID}", json={"payload": payload})
        if result is not None and len(result) == 0:
            raise RuntimeError("PATCH התאים 0 שורות — ייתכן שהרשאות RLS חוסמות כתיבה")
    else:
        sb_request(
            "POST",
            "school_state",
            json={"id": SCHOOL_ID, "payload": payload},
        )
    return payload


def log_ai(user_message: str, assistant_message: str, change_type: str, applied: bool):
    try:
        sb_request(
            "POST",
            "ai_logs",
            json={
                "school_id": SCHOOL_ID,
                "user_message": user_message[:2000],
                "assistant_message": (assistant_message or "")[:8000],
                "change_type": change_type,
                "applied": applied,
            },
        )
    except Exception:
        pass


def gemini_key_from_request(data: dict) -> str:
    header_key = (request.headers.get("X-Gemini-Key") or "").strip()
    body_key = (data.get("gemini_key") or "").strip()
    return body_key or header_key or _env("GEMINI_API_KEY")


def _detect_provider(model: str) -> str:
    return "claude" if (model or "").startswith("claude") else "gemini"


def _get_api_key(data: dict, provider: str) -> str:
    if provider == "claude":
        header = (request.headers.get("X-Anthropic-Key") or "").strip()
        body = (data.get("anthropic_key") or "").strip()
        return body or header or _env("ANTHROPIC_API_KEY")
    return gemini_key_from_request(data)


def _gemini_role(role: str) -> str:
    return "model" if role == "assistant" else "user"


def _build_contents(messages: list) -> list:
    contents = []
    for msg in messages:
        text = (msg.get("content") or "").strip()
        if not text:
            continue
        contents.append(
            types.Content(role=_gemini_role(msg.get("role", "user")), parts=[types.Part(text=text)])
        )
    return contents


def _call_ai(messages: list, system: str, model: str, api_key: str, max_tokens: int = 1024) -> str:
    provider = _detect_provider(model)
    if provider == "claude":
        if not _ANTHROPIC_OK:
            raise RuntimeError("חבילת anthropic לא מותקנת בשרת — הוסף 'anthropic' ל-requirements.txt")
        client = _anthropic.Anthropic(api_key=api_key)
        msgs = [
            {
                "role": "assistant" if m.get("role") == "assistant" else "user",
                "content": (m.get("content") or "").strip(),
            }
            for m in messages
            if (m.get("content") or "").strip()
        ]
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system or "",
            messages=msgs,
        )
        return resp.content[0].text if resp.content else ""
    else:
        client = genai.Client(api_key=api_key)
        cfg = types.GenerateContentConfig(max_output_tokens=max_tokens)
        if system:
            cfg.system_instruction = system
        resp = client.models.generate_content(
            model=model,
            contents=_build_contents(messages),
            config=cfg,
        )
        return resp.text or ""


_SITE_PROTECT_PAGE = """<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>כניסה לאתר</title>
  <link href="https://fonts.googleapis.com/css2?family=Heebo:wght@400;700;900&display=swap" rel="stylesheet">
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:Heebo,sans-serif;background:#f0f4f8;display:flex;align-items:center;justify-content:center;min-height:100vh}}
    .card{{background:#fff;border-radius:20px;padding:40px 36px;width:100%;max-width:380px;box-shadow:0 8px 40px rgba(0,0,0,.1);text-align:center}}
    .logo{{font-size:3rem;margin-bottom:12px}}
    h1{{font-size:1.4rem;font-weight:900;margin-bottom:4px}}
    .sub{{color:#5f6368;font-size:.85rem;margin-bottom:24px}}
    input{{width:100%;padding:12px 14px;border:1.5px solid #e8ecf0;border-radius:12px;font-family:inherit;font-size:1rem;margin-bottom:12px;text-align:center;letter-spacing:.1em}}
    input:focus{{outline:none;border-color:#1a73e8}}
    button{{width:100%;padding:13px;background:#1a73e8;color:#fff;border:0;border-radius:12px;font-family:inherit;font-size:1rem;font-weight:700;cursor:pointer}}
    .error{{background:#fee2e2;color:#991b1b;border-radius:10px;padding:10px;font-size:.85rem;margin-bottom:12px}}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">🏫</div>
    <h1>{school_name}</h1>
    <p class="sub">האתר מוגן. הזן קוד גישה להמשך.</p>
    {error_block}
    <form method="POST" action="/site-login">
      <input type="text" name="code" placeholder="קוד גישה" autofocus>
      <button type="submit">כניסה &rarr;</button>
    </form>
  </div>
</body>
</html>"""

_site_cache = {"data": None, "ts": 0}

def _get_site_settings():
    now = time.time()
    if now - _site_cache["ts"] < 60 and _site_cache["data"] is not None:
        return _site_cache["data"]
    try:
        rows = sb_request("GET", "access_settings?school_id=eq.default")
        data = rows[0] if rows else {}
    except Exception:
        data = {}
    _site_cache["data"] = data
    _site_cache["ts"] = now
    return data

def _invalidate_site_cache():
    _site_cache["ts"] = 0

_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>כניסת מנהל</title>
  <link href="https://fonts.googleapis.com/css2?family=Heebo:wght@400;700;900&display=swap" rel="stylesheet">
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:Heebo,sans-serif;background:#f0f4f8;display:flex;align-items:center;justify-content:center;min-height:100vh}}
    .card{{background:#fff;border-radius:20px;padding:40px 36px;width:100%;max-width:380px;box-shadow:0 8px 40px rgba(0,0,0,.1);text-align:center}}
    .logo{{width:64px;height:64px;border-radius:18px;background:linear-gradient(135deg,#3b82f6,#34a853);display:flex;align-items:center;justify-content:center;font-size:2rem;margin:0 auto 16px}}
    h1{{font-size:1.4rem;font-weight:900;margin-bottom:4px}}
    .sub{{color:#5f6368;font-size:.85rem;margin-bottom:24px}}
    input{{width:100%;padding:12px 14px;border:1.5px solid #e8ecf0;border-radius:12px;font-family:inherit;font-size:1rem;margin-bottom:12px;text-align:center}}
    input:focus{{outline:none;border-color:#1a73e8}}
    button{{width:100%;padding:13px;background:#1a73e8;color:#fff;border:0;border-radius:12px;font-family:inherit;font-size:1rem;font-weight:700;cursor:pointer}}
    button:hover{{background:#1557b0}}
    .error{{background:#fee2e2;color:#991b1b;border-radius:10px;padding:10px;font-size:.85rem;margin-bottom:12px}}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">🏫</div>
    <h1>כניסת מנהל</h1>
    <p class="sub">הזן סיסמה כדי להיכנס ללוח הניהול</p>
    {error_block}
    <form method="POST">
      <input type="password" name="password" placeholder="סיסמה" autofocus>
      <button type="submit">כניסה &rarr;</button>
    </form>
  </div>
</body>
</html>"""


@app.route("/")
def public_site():
    settings = _get_site_settings()
    if settings.get("site_protected") and not session.get("site_access"):
        try:
            state_rows = sb_request("GET", "school_state?id=eq.default&select=payload")
            school_name = (state_rows[0].get("payload", {}) if state_rows else {}).get("school", {}).get("name", "בית הספר") if state_rows else "בית הספר"
        except Exception:
            school_name = "בית הספר"
        return _SITE_PROTECT_PAGE.format(school_name=school_name, error_block="")
    return send_from_directory(STATIC, "index.html")


@app.route("/site-login", methods=["POST"])
def site_login():
    code = (request.form.get("code") or "").strip()
    settings = _get_site_settings()
    if code == settings.get("site_code", ""):
        session["site_access"] = True
        return redirect("/")
    try:
        state_rows = sb_request("GET", "school_state?id=eq.default&select=payload")
        school_name = (state_rows[0].get("payload", {}) if state_rows else {}).get("school", {}).get("name", "בית הספר") if state_rows else "בית הספר"
    except Exception:
        school_name = "בית הספר"
    return _SITE_PROTECT_PAGE.format(school_name=school_name, error_block='<div class="error">קוד שגוי — נסה שנית</div>')


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error_block = ""
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == os.getenv("ADMIN_PASSWORD", "admin123"):
            session["admin"] = True
            return redirect("/admin")
        error_block = '<div class="error">סיסמה שגויה — נסה שנית</div>'
    return _LOGIN_PAGE.format(error_block=error_block)


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin/login")


@app.route("/admin")
def admin_site():
    if not session.get("admin"):
        return redirect("/admin/login")
    return send_from_directory(STATIC, "admin.html")


@app.route("/api/version")
def version():
    return jsonify({"version": APP_VERSION, "model": DEFAULT_MODEL})

@app.route("/api/db-check")
def db_check():
    url, key = supabase_config()
    result = {"url_set": bool(url), "key_set": bool(key), "key_type": "unknown"}
    if key:
        result["key_prefix"] = key[:12] + "..."
        result["key_type"] = "service_role (likely)" if len(key) > 100 else "anon (likely — too short!)"
    try:
        rows = sb_request("GET", f"school_state?id=eq.{SCHOOL_ID}&select=id")
        result["can_read"] = True
        result["row_exists"] = bool(rows)
    except Exception as e:
        result["can_read"] = False
        result["read_error"] = str(e)
    try:
        sb_request("PATCH", f"school_state?id=eq.{SCHOOL_ID}", json={"payload": {"_ping": True}})
        result["can_write"] = True
    except Exception as e:
        result["can_write"] = False
        result["write_error"] = str(e)
    return jsonify(result)

@app.route("/api/health")
def health():
    url, key = supabase_config()
    supabase_ok = False
    supabase_error = ""
    if url and key:
        try:
            load_state()
            supabase_ok = True
        except Exception as exc:
            supabase_error = str(exc)
    else:
        supabase_error = "חסרים SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY"
    return jsonify(
        {
            "status": "ok" if supabase_ok else "setup",
            "supabase": supabase_ok,
            "supabase_error": supabase_error,
            "gemini_env": bool(_env("GEMINI_API_KEY")),
        }
    )


@app.route("/api/state", methods=["GET"])
def get_state():
    try:
        return jsonify({"state": load_state()})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}, "state": DEFAULT_STATE}), 503


@app.route("/api/state", methods=["PUT"])
def put_state():
    data = request.get_json(silent=True) or {}
    payload = data.get("state")
    if not isinstance(payload, dict):
        return jsonify({"error": {"message": "state object is required"}}), 400
    try:
        saved = save_state(payload)
        return jsonify({"ok": True, "state": saved})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/logs")
def get_logs():
    try:
        rows = sb_request(
            "GET",
            "ai_logs?school_id=eq.default&select=id,user_message,assistant_message,change_type,applied,created_at&order=created_at.desc&limit=40",
        )
        return jsonify({"logs": rows or []})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}, "logs": []}), 503


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    messages = data.get("messages") or []
    if not messages:
        return jsonify({"error": {"message": "messages are required"}}), 400

    model = (data.get("model") or "").strip() or DEFAULT_MODEL
    provider = _detect_provider(model)
    api_key = _get_api_key(data, provider)
    if not api_key:
        pname = "Anthropic" if provider == "claude" else "Gemini"
        return jsonify({"error": {"message": f"חסר מפתח {pname}. הזן אותו בלשונית מפתחות."}}), 400

    system = data.get("system") or ""
    max_tokens = int(data.get("max_tokens") or 1024)
    user_text = next((m.get("content") for m in reversed(messages) if m.get("role") == "user"), "")

    try:
        text = _call_ai(messages, system, model, api_key, max_tokens)
        change_type = "text"
        if '"type": "state"' in text or '"type":"state"' in text:
            change_type = "state"
        elif '"type": "code"' in text or '"type":"code"' in text:
            change_type = "code"
        log_ai(user_text, text, change_type, False)
        return jsonify({"content": [{"text": text}]})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/logs/applied", methods=["POST"])
def mark_applied():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("user_message") or "")[:2000]
    assistant_message = (data.get("assistant_message") or "")[:8000]
    log_ai(user_message, assistant_message, "state", True)
    return jsonify({"ok": True})


# ===== ניהול משתמשים =====

def _require_admin():
    if not session.get("admin"):
        return jsonify({"error": {"message": "נדרשת הרשאת מנהל"}}), 403
    return None


def _generate_code(length=8):
    import random, string
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


@app.route("/api/users", methods=["GET"])
def list_users():
    err = _require_admin()
    if err: return err
    try:
        rows = sb_request("GET", "users?school_id=eq.default&order=created_at.desc&select=id,name,role,class_id,access_code,created_at")
        return jsonify({"users": rows or []})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/users", methods=["POST"])
def create_user():
    err = _require_admin()
    if err: return err
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    role = (data.get("role") or "").strip()
    class_id = (data.get("class_id") or "").strip() or None
    if not name or role not in ("teacher", "staff", "student"):
        return jsonify({"error": {"message": "שם ותפקיד חובה"}}), 400
    code = _generate_code()
    try:
        rows = sb_request("POST", "users", json={"school_id": "default", "name": name, "role": role, "class_id": class_id, "access_code": code})
        return jsonify({"user": rows[0] if rows else {"access_code": code}})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/users/<uid>", methods=["DELETE"])
def delete_user(uid):
    err = _require_admin()
    if err: return err
    try:
        sb_request("DELETE", f"users?id=eq.{uid}")
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


# ===== אימות מחנכים/תלמידים =====

@app.route("/teacher")
def teacher_page():
    return send_from_directory(STATIC, "teacher.html")


@app.route("/teacher/class/<class_id>")
def teacher_class_page(class_id):
    return send_from_directory(STATIC, "teacher.html")


@app.route("/class/<code>")
def class_page(code):
    return send_from_directory(STATIC, "student.html")


@app.route("/api/auth/teacher", methods=["POST"])
def auth_teacher():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    if not code:
        return jsonify({"error": {"message": "קוד גישה חסר"}}), 400
    try:
        rows = sb_request("GET", f"users?access_code=eq.{code}&role=in.(teacher,staff)&select=id,name,role,class_id,access_code")
        if not rows:
            return jsonify({"error": {"message": "קוד גישה שגוי"}}), 401
        user = rows[0]
        session["teacher"] = user
        return jsonify({"user": user})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/auth/class", methods=["POST"])
def auth_class():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    if not code:
        return jsonify({"error": {"message": "קוד כיתה חסר"}}), 400
    try:
        rows = sb_request("GET", f"users?access_code=eq.{code}&role=eq.student&select=id,name,class_id")
        if rows:
            student = rows[0]
            return jsonify({"class_id": student.get("class_id"), "student_name": student.get("name")})
        rows_teacher = sb_request("GET", f"users?access_code=eq.{code}&role=in.(teacher,staff)&select=class_id")
        if rows_teacher:
            return jsonify({"class_id": rows_teacher[0].get("class_id")})
        return jsonify({"error": {"message": "קוד לא נמצא"}}), 401
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout_teacher():
    session.pop("teacher", None)
    return jsonify({"ok": True})


# ===== ניהול פיצ'רים =====

def _feature_system_prompt(class_name: str) -> str:
    return f"""אתה בונה פיצ'רים לאתר בית ספר עבור {class_name}.
קבל תיאור ממחנך והחזר JSON בלבד — ללא טקסט נוסף:
{{
  "title": "כותרת הפיצ'ר",
  "description": "תיאור קצר",
  "feature_type": "quiz|task_board|grade_tracker|announcement_card|link_set|custom_form",
  "config": {{...תוכן לפי הסוג...}}
}}

quiz — שאלות עם תשובות:
  config: {{"questions":[{{"text":"שאלה","options":["א","ב","ג"],"correct":0}}],"time_limit":20}}

task_board — לוח משימות:
  config: {{"tasks":[{{"text":"משימה","due":"2026-09-01","done":false}}]}}

grade_tracker — מעקב ציונים:
  config: {{"columns":["שם","ציון","הערה"],"rows":[]}}

announcement_card — הודעה:
  config: {{"text":"הודעה","icon":"📢","color":"#1a73e8"}}

link_set — קבוצת קישורים:
  config: {{"links":[{{"text":"כותרת","url":"https://...","icon":"🔗"}}]}}

custom_form — טופס:
  config: {{"fields":[{{"label":"שם","type":"text"}}]}}"""


@app.route("/api/features", methods=["POST"])
def create_feature():
    if not session.get("teacher") and not session.get("admin"):
        return jsonify({"error": {"message": "נדרשת התחברות"}}), 403
    data = request.get_json(silent=True) or {}
    description = (data.get("description") or "").strip()
    target_class = (data.get("target_class") or "").strip()
    if not description:
        return jsonify({"error": {"message": "תיאור הפיצ'ר חסר"}}), 400

    model = (data.get("model") or "").strip() or DEFAULT_MODEL
    provider = _detect_provider(model)
    api_key = _get_api_key(data, provider)
    if not api_key:
        pname = "Anthropic" if provider == "claude" else "Gemini"
        return jsonify({"error": {"message": f"חסר מפתח {pname}"}}), 400

    creator = session.get("teacher") or {"name": "מנהל"}
    class_name = target_class or "הכיתה"

    try:
        messages = [{"role": "user", "content": description}]
        raw = _call_ai(messages, _feature_system_prompt(class_name), model, api_key, 2048)
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return jsonify({"error": {"message": f"AI החזיר JSON לא תקין: {exc}"}}), 500
    except Exception as exc:
        return jsonify({"error": {"message": f"שגיאת AI: {exc}"}}), 500

    try:
        access_level = (data.get("access_level") or "public")
        feature_code = (data.get("feature_code") or "").strip()
        rows = sb_request("POST", "features", json={
            "school_id": "default",
            "creator_name": creator.get("name", ""),
            "title": parsed.get("title", "פיצ'ר חדש"),
            "description": parsed.get("description", description),
            "feature_type": parsed.get("feature_type", "announcement_card"),
            "config": parsed.get("config", {}),
            "target_class": target_class or None,
            "status": "pending",
            "access_level": access_level,
            "feature_code": feature_code if access_level == "protected" else "",
        })
        return jsonify({"feature": rows[0] if rows else parsed, "raw": parsed})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/features", methods=["GET"])
def list_features():
    status = request.args.get("status", "pending")
    target_class = request.args.get("class")
    is_admin = session.get("admin") or session.get("teacher")
    select = "id,school_id,creator_name,title,description,feature_type,config,target_class,status,created_at,approved_at,access_level"
    if is_admin:
        select += ",feature_code"
    query = f"features?school_id=eq.default&status=eq.{status}&order=created_at.desc&select={select}"
    if target_class:
        query += f"&target_class=eq.{target_class}"
    try:
        rows = sb_request("GET", query)
        return jsonify({"features": rows or []})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/features/<fid>/verify", methods=["POST"])
def verify_feature(fid):
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    try:
        rows = sb_request("GET", f"features?id=eq.{fid}&select=access_level,feature_code")
        if not rows:
            return jsonify({"error": {"message": "פיצ'ר לא נמצא"}}), 404
        feature = rows[0]
        if feature.get("access_level") != "protected":
            return jsonify({"ok": True})
        if code == (feature.get("feature_code") or ""):
            return jsonify({"ok": True})
        return jsonify({"error": {"message": "קוד שגוי"}}), 401
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/features/<fid>", methods=["PATCH"])
def update_feature(fid):
    err = _require_admin()
    if err: return err
    data = request.get_json(silent=True) or {}
    patch = {}
    if "status" in data:
        patch["status"] = data["status"]
        if data["status"] == "active":
            patch["approved_by"] = "מנהל"
    if "title" in data: patch["title"] = data["title"]
    if "config" in data: patch["config"] = data["config"]
    try:
        sb_request("PATCH", f"features?id=eq.{fid}", json=patch)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/features/<fid>", methods=["DELETE"])
def delete_feature(fid):
    err = _require_admin()
    if err: return err
    try:
        sb_request("DELETE", f"features?id=eq.{fid}")
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


# ===== הגדרות גישה =====

@app.route("/api/access-settings", methods=["GET"])
def get_access_settings():
    try:
        rows = sb_request("GET", "access_settings?school_id=eq.default")
        return jsonify({"settings": rows[0] if rows else {"mode": "code"}})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


@app.route("/api/access-settings", methods=["PUT"])
def put_access_settings():
    err = _require_admin()
    if err: return err
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "code")
    site_protected = bool(data.get("site_protected", False))
    site_code = (data.get("site_code") or "").strip()
    patch = {"mode": mode, "site_protected": site_protected, "site_code": site_code}
    try:
        rows = sb_request("GET", "access_settings?school_id=eq.default")
        if rows:
            sb_request("PATCH", "access_settings?school_id=eq.default", json=patch)
        else:
            sb_request("POST", "access_settings", json={"school_id": "default", **patch})
        _invalidate_site_cache()
        return jsonify({"ok": True, "mode": mode})
    except Exception as exc:
        return jsonify({"error": {"message": str(exc)}}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"School AI demo: http://localhost:{port}")
    print(f"Admin:          http://localhost:{port}/admin")
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
