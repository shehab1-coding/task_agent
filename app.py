from flask import Flask, request, jsonify, send_from_directory, render_template, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import google.generativeai as genai
import os
import difflib
from datetime import timedelta

# ─── App Setup ────────────────────────────────────────────────────────────────
base_dir = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__,
            static_folder=os.path.join(base_dir, "static"),
            template_folder=os.path.join(base_dir, "templates"))

app.secret_key = os.environ.get('SECRET_KEY', 'sphinx_university_super_secret_key')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

db_url = os.environ.get('DATABASE_URL', f'sqlite:///{os.path.join(base_dir, "instance", "database.db")}')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

CORS(app, supports_credentials=True)
db = SQLAlchemy(app)

# ─── Models ───────────────────────────────────────────────────────────────────

class User(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    chats         = db.relationship('Chat', backref='user', lazy=True)

class Chat(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    session_id   = db.Column(db.String(100), default="default", nullable=False)
    user_message = db.Column(db.Text, nullable=False)
    bot_reply    = db.Column(db.Text, nullable=False)
    timestamp    = db.Column(db.DateTime, default=db.func.current_timestamp())

class AdminData(db.Model):
    """جدول البيانات اللي يضيفها الأدمن — كل صف key/value"""
    id         = db.Column(db.Integer, primary_key=True)
    key        = db.Column(db.String(300), nullable=False)
    value      = db.Column(db.Text,       nullable=False)
    created_at = db.Column(db.DateTime,   default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime,   default=db.func.current_timestamp(),
                           onupdate=db.func.current_timestamp())

    def to_dict(self):
        return {
            "id":         self.id,
            "key":        self.key,
            "value":      self.value,
            "created_at": str(self.created_at),
        }

# ─── Gemini Setup ─────────────────────────────────────────────────────────────
ENV_KEYS    = os.environ.get("GEMINI_API_KEYS", "").split(",")
API_KEYS    = [k.strip() for k in ENV_KEYS if k.strip()]
MODEL_VERSIONS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-flash-latest",
    "gemini-pro-latest",
]
model_idx = 0

# ─── Static Knowledge Base ────────────────────────────────────────────────────
CHATBOT_CONTEXT = ""
try:
    with open(os.path.join(base_dir, "chatbot.txt"), "r", encoding="utf-8", errors="ignore") as f:
        CHATBOT_CONTEXT = f.read()
except Exception as e:
    print(f"Warning: Could not read chatbot.txt: {e}")

if not CHATBOT_CONTEXT.strip():
    CHATBOT_CONTEXT = "University Information: Sphinx University uses a credit hour system."

# ─── University Rules ─────────────────────────────────────────────────────────
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

# ─── System Prompt (يشمل بيانات الأدمن من الـ DB) ────────────────────────────
def get_system_instruction():
    admin_text = ""
    try:
        rows = AdminData.query.order_by(AdminData.created_at.asc()).all()
        if rows:
            admin_text = "\n=== ADMIN UPDATED INFORMATION (PRIORITIZE THIS) ===\n"
            for row in rows:
                admin_text += f"- {row.key}: {row.value}\n"
    except Exception:
        pass

    return f"""You are a friendly human academic advisor for Sphinx University.
You have access to the following university knowledge base and rules.
=== UNIVERSITY KNOWLEDGE BASE ===
{CHATBOT_CONTEXT}
{admin_text}
=== GRADUATION RULES ===
{UNIVERSITY_RULES}
=== YOUR BEHAVIOR ===
1. You must first ALWAYS check if the answer exists in the UNIVERSITY KNOWLEDGE BASE or GRADUATION RULES.
2. IF the answer depends on the provided university rules or context, you MUST start your reply exactly with "📚 (من اللائحة): " and provide the rule directly in conversational human text.
3. IF the answer is NOT in the rules/context, you MUST start your reply exactly with "🤖 (AI): " and answer from your general knowledge.
4. DO NOT use any markdown formatting (no asterisks **, no hash #). DO NOT use bullet points or numbered lists.
5. DO NOT output any code or JSON. Speak exactly like a normal person chatting on WhatsApp.
6. If the student shares their academic data (credit hours, GPA, attendance), calculate their eligibility naturally in conversation and prefix with "📊 (تحليل البيانات): ".
7. Respond in the same language the student uses (Arabic or English), and be extremely empathetic and warm."""

# ─── Gemini Model ─────────────────────────────────────────────────────────────
def get_next_model():
    global model_idx
    if not API_KEYS:
        raise ValueError("No API keys configured.")
    k_idx      = (model_idx // len(MODEL_VERSIONS)) % len(API_KEYS)
    m_idx      = model_idx % len(MODEL_VERSIONS)
    genai.configure(api_key=API_KEYS[k_idx])
    return genai.GenerativeModel(MODEL_VERSIONS[m_idx],
                                 system_instruction=get_system_instruction())

try:
    model = get_next_model()
except Exception as e:
    print(f"Warning: Could not initialize Gemini model: {e}")
    class MockModel:
        def generate_content(self, *a, **k):
            return type('r', (), {'text': 'AI Error: No API keys configured.'})()
        def start_chat(self, *a, **k):
            return type('c', (), {'send_message': lambda m: type('r', (), {'text': 'AI Error: No API keys.'})()})()
    model = MockModel()

response_cache = {}
chat_sessions  = {}

def find_local_match(user_query):
    if not CHATBOT_CONTEXT:
        return None
    lines   = [l.strip() for l in CHATBOT_CONTEXT.split("\n") if l.strip()]
    matches = difflib.get_close_matches(user_query, lines, n=1, cutoff=0.3)
    if matches:
        return "📚 (من اللائحة): " + matches[0]
    return None

# ─── Health ───────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok"})

# ─── User Auth ────────────────────────────────────────────────────────────────
@app.route("/register", methods=["POST"])
def register():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "اسم المستخدم وكلمة المرور مطلوبان"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "اسم المستخدم موجود مسبقاً"}), 400

    new_user = User(username=username,
                    password_hash=generate_password_hash(password))
    db.session.add(new_user)
    db.session.commit()

    session.permanent       = True
    session["user_id"]      = new_user.id
    session["username"]     = new_user.username
    return jsonify({"success": True, "message": "تم التسجيل بنجاح",
                    "username": new_user.username})

@app.route("/login", methods=["POST"])
def login():
    data     = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "اسم المستخدم وكلمة المرور مطلوبان"}), 400

    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        session.permanent   = True
        session["user_id"]  = user.id
        session["username"] = user.username
        return jsonify({"success": True, "message": "تم تسجيل الدخول بنجاح",
                        "username": user.username})
    return jsonify({"error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/check_auth")
def check_auth():
    if "user_id" in session:
        return jsonify({"logged_in": True, "username": session["username"]})
    return jsonify({"logged_in": False})

# ─── Chat ─────────────────────────────────────────────────────────────────────
@app.route("/get_chats")
def get_chats():
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح لك"}), 401

    chats = Chat.query.filter_by(user_id=session["user_id"])\
                      .order_by(Chat.timestamp.asc()).all()
    sessions_dict = {}
    for chat in chats:
        sid = chat.session_id
        if sid not in sessions_dict:
            title = chat.user_message[:30] + "..." if len(chat.user_message) > 30 else chat.user_message
            sessions_dict[sid] = {"session_id": sid, "title": title, "messages": []}
        sessions_dict[sid]["messages"].append({"sender": "user", "text": chat.user_message})
        sessions_dict[sid]["messages"].append({"sender": "bot",  "text": chat.bot_reply})

    sessions_list = list(sessions_dict.values())
    sessions_list.reverse()
    return jsonify({"success": True, "sessions": sessions_list,
                    "username": session["username"]})

@app.route("/chat", methods=["POST"])
def chat():
    if "user_id" not in session:
        return jsonify({"error": "يجب تسجيل الدخول أولاً"}), 401
    return _handle_chat(request.get_json() or {})

def _handle_chat(data):
    global model, model_idx
    try:
        user_message = data.get("message", "").strip()
        session_id   = data.get("session_id", "default")
        if not user_message:
            return jsonify({"error": "No message provided"}), 400

        # 1) local static match
        local_reply = find_local_match(user_message)
        if local_reply:
            return jsonify({"reply": local_reply, "session_id": session_id})

        # 2) cache
        cache_key = user_message.lower()
        if cache_key in response_cache:
            return jsonify({"reply": response_cache[cache_key], "session_id": session_id})

        # 3) Gemini (fresh model so admin data is always current)
        fresh = genai.GenerativeModel(
            MODEL_VERSIONS[model_idx % len(MODEL_VERSIONS)],
            system_instruction=get_system_instruction()
        )
        if session_id not in chat_sessions:
            chat_sessions[session_id] = []

        history = chat_sessions[session_id]
        gemini_history = []
        for turn in history[-5:]:
            gemini_history.append({"role": "user",  "parts": [turn["user"]]})
            gemini_history.append({"role": "model", "parts": [turn["bot"]]})

        chat_obj  = fresh.start_chat(history=gemini_history)
        response  = chat_obj.send_message(user_message)
        bot_reply = response.text.strip()

        if not bot_reply.startswith(("🤖", "📚", "📊")):
            bot_reply = "🤖 (AI): " + bot_reply

        # save to DB
        user_id = session.get("user_id")
        if user_id:
            db.session.add(Chat(user_id=user_id, session_id=session_id,
                                user_message=user_message, bot_reply=bot_reply))
            db.session.commit()

        response_cache[cache_key] = bot_reply
        history.append({"user": user_message, "bot": bot_reply})
        return jsonify({"reply": bot_reply, "session_id": session_id})

    except Exception as e:
        err = str(e)
        if "429" in err or "Quota" in err or "404" in err:
            retries = data.get("retries", 0)
            if retries >= len(MODEL_VERSIONS) * max(len(API_KEYS), 1):
                return jsonify({"error": "عذراً، ضغط الأسئلة كبير. انتظر 30 ثانية ⏱️"}), 429
            model_idx += 1
            model = get_next_model()
            data["retries"] = retries + 1
            return _handle_chat(data)
        return jsonify({"error": f"AI Error: {err}"}), 500

# ─── Graduation Checker ───────────────────────────────────────────────────────
@app.route("/check-requirements", methods=["POST"])
def check_requirements():
    try:
        data         = request.get_json() or {}
        credit_hours = data.get("credit_hours", 0)
        gpa          = data.get("gpa", 0.0)
        attendance   = data.get("attendance", 0)
        years        = data.get("years", 0)
        student_name = data.get("name", "Student")

        prompt = f"""You are a strict academic advisor at Sphinx University.
{UNIVERSITY_RULES}
Student: {student_name}
- Credit Hours: {credit_hours}/138
- GPA: {gpa}/4.0
- Attendance: {attendance}%
- Years: {years}/8
Give ✅/❌ per requirement, overall verdict (CAN GRADUATE / CANNOT GRADUATE YET), specific advice, and estimated semesters remaining. Use emojis. Respond in Arabic and English."""

        fresh    = genai.GenerativeModel(MODEL_VERSIONS[model_idx % len(MODEL_VERSIONS)],
                                         system_instruction=get_system_instruction())
        response = fresh.generate_content(prompt)
        result   = response.text.strip()

        can_graduate = (int(credit_hours) >= 138 and float(gpa) >= 2.0
                        and int(attendance) >= 75 and int(years) <= 8)

        return jsonify({"analysis": result, "can_graduate": can_graduate})
    except Exception as e:
        err = str(e)
        if "429" in err or "Quota" in err:
            return jsonify({"error": "تجاوزت الحد المسموح مؤقتاً. انتظر دقيقة."}), 429
        return jsonify({"error": f"AI Error: {err}"}), 500

# ─── Admin ────────────────────────────────────────────────────────────────────
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin12345")

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"error": "غير مصرح لك"}), 401
        return f(*args, **kwargs)
    return decorated

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        data = request.get_json() or {}
        if (data.get("username","").strip() == ADMIN_USERNAME and
                data.get("password","").strip() == ADMIN_PASSWORD):
            session["is_admin"] = True
            return jsonify({"success": True})
        return jsonify({"error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401
    return render_template("admin_login.html")

@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return jsonify({"success": True})

@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("is_admin"):
        return render_template("admin_login.html")
    return render_template("admin_dashboard.html")

# --- Admin Data API ---
@app.route("/admin/api/data", methods=["GET"])
@admin_required
def admin_get_data():
    rows = AdminData.query.order_by(AdminData.created_at.desc()).all()
    return jsonify({"success": True, "data": [r.to_dict() for r in rows]})

@app.route("/admin/api/data", methods=["POST"])
@admin_required
def admin_add_data():
    body  = request.get_json() or {}
    key   = body.get("key",   "").strip()
    value = body.get("value", "").strip()
    if not key or not value:
        return jsonify({"error": "الحقلان مطلوبان"}), 400

    # لو الـ key موجود قبل كده، بنعمله update
    existing = AdminData.query.filter_by(key=key).first()
    if existing:
        existing.value = value
    else:
        db.session.add(AdminData(key=key, value=value))
    db.session.commit()
    response_cache.clear()
    return jsonify({"success": True})

@app.route("/admin/api/data/<int:row_id>", methods=["DELETE"])
@admin_required
def admin_delete_data(row_id):
    row = AdminData.query.get_or_404(row_id)
    db.session.delete(row)
    db.session.commit()
    response_cache.clear()
    return jsonify({"success": True})

# ─── Static & Index ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)

# ─── Init ─────────────────────────────────────────────────────────────────────
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
