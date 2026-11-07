from datetime import timedelta
import difflib
import math
import os
import re
import secrets
from urllib.parse import urlsplit

import google.generativeai as genai
from flask import Flask, jsonify, render_template, request, send_from_directory, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    static_folder=os.path.join(base_dir, "static"),
    template_folder=os.path.join(base_dir, "templates"),
)

is_production = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("FLASK_ENV") == "production")
secret_key = os.environ.get("SECRET_KEY")
if is_production and not secret_key:
    raise RuntimeError("Set SECRET_KEY in the deployment environment before starting the app.")
app.secret_key = secret_key or secrets.token_urlsafe(32)
app.config.update(
    MAX_CONTENT_LENGTH=16 * 1024,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true",
    SESSION_COOKIE_SAMESITE="Lax",
)

os.makedirs(os.path.join(base_dir, "instance"), exist_ok=True)
db_url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(base_dir, "instance", "database.db"))
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
    default_limits=[],
)

MODEL_VERSIONS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-flash-latest",
    "gemini-pro-latest",
]
API_KEYS = [key.strip() for key in os.environ.get("GEMINI_API_KEYS", "").split(",") if key.strip()]
model_idx = 0

CHATBOT_CONTEXT = ""
try:
    with open(os.path.join(base_dir, "chatbot.txt"), "r", encoding="utf-8", errors="ignore") as f:
        CHATBOT_CONTEXT = f.read()
except OSError:
    app.logger.warning("chatbot.txt is missing; using the built-in university context.")

if not CHATBOT_CONTEXT.strip():
    CHATBOT_CONTEXT = "University Information: Sphinx University uses a credit hour system."

UNIVERSITY_RULES = """
Sphinx University Graduation Requirements:
- Total credit hours required: 138
- Minimum GPA: 2.0 (on a 4.0 scale)
- Minimum attendance rate: 75%
- Maximum study duration: 8 years (16 semesters)
- Students must pass all core/mandatory courses
- Students on academic probation must achieve GPA >= 2.0 next semester
- A student fails a course if attendance drops below 75%
- Failed courses can be retaken (counted toward max duration)
"""

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    chats = db.relationship("Chat", backref="user", lazy=True, cascade="all, delete-orphan")

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    session_id = db.Column(db.String(100), default="default", nullable=False, index=True)
    user_message = db.Column(db.Text, nullable=False)
    bot_reply = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp(), index=True)

class AdminData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(300), nullable=False)
    value = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())

    def to_dict(self):
        return {"id": self.id, "key": self.key, "value": self.value, "created_at": str(self.created_at)}

def get_system_instruction():
    rows = AdminData.query.order_by(AdminData.created_at.asc()).all()
    admin_text = "".join("- " + row.key + ": " + row.value + "\n" for row in rows)
    return f"""You are a friendly academic advisor for Sphinx University.
Use the following university knowledge and rules when answering.
=== UNIVERSITY KNOWLEDGE BASE ===
{CHATBOT_CONTEXT}
=== ADMIN UPDATED INFORMATION ===
{admin_text}
=== GRADUATION RULES ===
{UNIVERSITY_RULES}
If the answer relies on university information, begin with "📚 (من اللائحة): ".
Otherwise begin with "🤖 (AI): ".
If the student shares academic data, calculate eligibility and begin with "📊 (تحليل البيانات): ".
Reply in the student's language and do not claim official access to student records."""

def request_data():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None

def bounded_text(value, field, maximum, required=True):
    if not isinstance(value, str):
        raise ValueError(field + " must be text")
    value = value.strip()
    if required and not value:
        raise ValueError(field + " is required")
    if len(value) > maximum:
        raise ValueError(field + " is too long")
    return value

def require_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)

def admin_configured():
    return bool(os.environ.get("ADMIN_USERNAME") and os.environ.get("ADMIN_PASSWORD"))

@app.before_request
def protect_unsafe_origins():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    origin = request.headers.get("Origin")
    if origin:
        expected = urlsplit(request.host_url)
        supplied = urlsplit(origin)
        if (supplied.scheme, supplied.netloc) != (expected.scheme, expected.netloc):
            return jsonify({"error": "الطلب مرفوض"}), 403
    return None

@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'",
    )
    return response

def find_local_match(user_query):
    lines = [line.strip() for line in CHATBOT_CONTEXT.splitlines() if line.strip()]
    matches = difflib.get_close_matches(user_query, lines, n=1, cutoff=0.3)
    return "📚 (من اللائحة): " + matches[0] if matches else None

def generate_reply(user_id, session_id, user_message):
    global model_idx
    history = (
        Chat.query.filter_by(user_id=user_id, session_id=session_id)
        .order_by(Chat.timestamp.desc(), Chat.id.desc())
        .limit(5)
        .all()
    )
    history.reverse()
    gemini_history = []
    for turn in history:
        gemini_history.append({"role": "user", "parts": [turn.user_message]})
        gemini_history.append({"role": "model", "parts": [turn.bot_reply]})

    if not API_KEYS:
        raise RuntimeError("AI service is not configured")
    attempts = len(API_KEYS) * len(MODEL_VERSIONS)
    last_error = None
    for offset in range(attempts):
        index = model_idx + offset
        genai.configure(api_key=API_KEYS[(index // len(MODEL_VERSIONS)) % len(API_KEYS)])
        model_name = MODEL_VERSIONS[index % len(MODEL_VERSIONS)]
        try:
            model = genai.GenerativeModel(model_name, system_instruction=get_system_instruction())
            response = model.start_chat(history=gemini_history).send_message(user_message)
            reply = (response.text or "").strip()
            if not reply:
                raise RuntimeError("Empty AI response")
            if not reply.startswith(("🤖", "📚", "📊")):
                reply = "🤖 (AI): " + reply
            model_idx = index + 1
            return reply
        except Exception as exc:
            last_error = exc
            error_text = str(exc).lower()
            if not any(term in error_text for term in ("429", "quota", "404", "resource_exhausted")):
                raise
    model_idx += attempts
    raise RuntimeError("AI providers are temporarily unavailable") from last_error

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/register", methods=["POST"])
@limiter.limit("5 per minute")
def register():
    data = request_data()
    if data is None:
        return jsonify({"error": "بيانات الطلب غير صالحة"}), 400
    try:
        username = bounded_text(data.get("username"), "username", 80)
        password = data.get("password")
        if not isinstance(password, str) or not password.strip() or len(password) > 256:
            raise ValueError("كلمة المرور غير صالحة")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if len(username) < 3 or not re.fullmatch(r"[\w.@+-]+", username, flags=re.UNICODE):
        return jsonify({"error": "اسم المستخدم غير صالح"}), 400
    if len(password) < 10:
        return jsonify({"error": "كلمة المرور يجب أن تكون 10 أحرف على الأقل"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "اسم المستخدم موجود مسبقاً"}), 409
    user = User(username=username, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    session["username"] = user.username
    return jsonify({"success": True, "message": "تم التسجيل بنجاح", "username": user.username})

@app.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
def login():
    data = request_data()
    if data is None:
        return jsonify({"error": "بيانات الطلب غير صالحة"}), 400
    try:
        username = bounded_text(data.get("username"), "username", 80)
        password = bounded_text(data.get("password"), "password", 256)
    except ValueError:
        return jsonify({"error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401
    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401
    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    session["username"] = user.username
    return jsonify({"success": True, "message": "تم تسجيل الدخول بنجاح", "username": user.username})

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/check_auth")
def check_auth():
    user = require_user()
    if user:
        return jsonify({"logged_in": True, "username": user.username})
    return jsonify({"logged_in": False})

@app.route("/get_chats")
def get_chats():
    user = require_user()
    if not user:
        return jsonify({"error": "غير مصرح لك"}), 401
    chats = Chat.query.filter_by(user_id=user.id).order_by(Chat.timestamp.asc(), Chat.id.asc()).all()
    sessions_dict = {}
    for chat in chats:
        sid = chat.session_id
        if sid not in sessions_dict:
            title = chat.user_message[:30] + ("..." if len(chat.user_message) > 30 else "")
            sessions_dict[sid] = {"session_id": sid, "title": title, "messages": []}
        sessions_dict[sid]["messages"].extend([
            {"sender": "user", "text": chat.user_message},
            {"sender": "bot", "text": chat.bot_reply},
        ])
    sessions_list = list(sessions_dict.values())
    sessions_list.reverse()
    return jsonify({"success": True, "sessions": sessions_list, "username": user.username})

@app.route("/chat", methods=["POST"])
@limiter.limit("10 per minute")
def chat():
    user = require_user()
    if not user:
        return jsonify({"error": "يجب تسجيل الدخول أولاً"}), 401
    data = request_data()
    if data is None:
        return jsonify({"error": "بيانات الطلب غير صالحة"}), 400
    try:
        user_message = bounded_text(data.get("message"), "message", 2000)
        session_id = bounded_text(data.get("session_id", "default"), "session_id", 64)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not re.fullmatch(r"[A-Za-z0-9_-]+", session_id):
        return jsonify({"error": "معرّف المحادثة غير صالح"}), 400

    reply = find_local_match(user_message)
    if reply is None:
        try:
            reply = generate_reply(user.id, session_id, user_message)
        except Exception:
            app.logger.exception("Chat generation failed")
            return jsonify({"error": "تعذر إنشاء الرد الآن. حاول مرة أخرى لاحقاً."}), 502
    db.session.add(Chat(user_id=user.id, session_id=session_id, user_message=user_message, bot_reply=reply))
    db.session.commit()
    return jsonify({"reply": reply, "session_id": session_id})

@app.route("/check-requirements", methods=["POST"])
@limiter.limit("5 per minute")
def check_requirements():
    data = request_data()
    if data is None:
        return jsonify({"error": "بيانات الطلب غير صالحة"}), 400
    try:
        def number(field, minimum, maximum):
            value = data.get(field)
            if isinstance(value, bool):
                raise ValueError
            value = float(value)
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError
            return value
        credit_hours = number("credit_hours", 0, 250)
        gpa = number("gpa", 0, 4)
        attendance = number("attendance", 0, 100)
        years = number("years", 0, 100)
    except (TypeError, ValueError):
        return jsonify({"error": "راجع الساعات وGPA والحضور وعدد السنوات"}), 400

    prompt = f"""Evaluate these academic values against the stated rules.
{UNIVERSITY_RULES}
Credit hours: {credit_hours}/138
GPA: {gpa}/4.0
Attendance: {attendance}%
Years studied: {years}/8
Give concise advice in Arabic and English. Do not request or infer identity."""
    try:
        if not API_KEYS:
            return jsonify({"error": "خدمة الذكاء الاصطناعي غير مهيأة"}), 503
        genai.configure(api_key=API_KEYS[model_idx % len(API_KEYS)])
        model = genai.GenerativeModel(MODEL_VERSIONS[model_idx % len(MODEL_VERSIONS)], system_instruction=get_system_instruction())
        result = model.generate_content(prompt).text.strip()
    except Exception:
        app.logger.exception("Requirements analysis failed")
        return jsonify({"error": "تعذر تحليل البيانات الآن. حاول مرة أخرى لاحقاً."}), 502

    eligible = credit_hours >= 138 and gpa >= 2.0 and attendance >= 75 and years <= 8
    return jsonify({"analysis": result, "can_graduate": eligible})

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not admin_configured() or not session.get("is_admin"):
            return jsonify({"error": "غير مصرح لك"}), 401
        return f(*args, **kwargs)
    return decorated

@app.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def admin_login():
    if request.method == "GET":
        return render_template("admin_login.html")
    data = request_data()
    if data is None:
        return jsonify({"error": "بيانات الطلب غير صالحة"}), 400
    username = data.get("username")
    password = data.get("password")
    if not admin_configured():
        return jsonify({"error": "تسجيل دخول المسؤول غير مهيأ"}), 503
    if not isinstance(username, str) or not isinstance(password, str) or not (
        secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD)
    ):
        return jsonify({"error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401
    session.clear()
    session.permanent = True
    session["is_admin"] = True
    return jsonify({"success": True})

@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/admin/dashboard")
def admin_dashboard():
    if not admin_configured() or not session.get("is_admin"):
        return render_template("admin_login.html")
    return render_template("admin_dashboard.html")

@app.route("/admin/api/data", methods=["GET"])
@admin_required
def admin_get_data():
    rows = AdminData.query.order_by(AdminData.created_at.desc()).all()
    return jsonify({"success": True, "data": [row.to_dict() for row in rows]})

@app.route("/admin/api/data", methods=["POST"])
@limiter.limit("20 per hour")
@admin_required
def admin_add_data():
    data = request_data()
    if data is None:
        return jsonify({"error": "بيانات الطلب غير صالحة"}), 400
    try:
        key = bounded_text(data.get("key"), "key", 300)
        value = bounded_text(data.get("value"), "value", 5000)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    existing = AdminData.query.filter_by(key=key).first()
    if existing:
        existing.value = value
    else:
        db.session.add(AdminData(key=key, value=value))
    db.session.commit()
    return jsonify({"success": True})

@app.route("/admin/api/data/<int:row_id>", methods=["DELETE"])
@limiter.limit("30 per hour")
@admin_required
def admin_delete_data(row_id):
    row = db.session.get(AdminData, row_id)
    if not row:
        return jsonify({"error": "المعلومة غير موجودة"}), 404
    db.session.delete(row)
    db.session.commit()
    return jsonify({"success": True})

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5000)
