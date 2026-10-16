// ================================
// CONFIG
// ================================
const API_BASE = ""; // Relative path so it works on any domain or tunnel link
let SESSION_ID = "session_" + Date.now();
let isLoginMode = true;

function newChat() {
    if (!confirm("هل تريد بدء محادثة جديدة؟ سيتم مسح الرسائل الحالية. / Start a new chat? Current messages will be cleared.")) return;

    // Reset Session to a new unique ID
    SESSION_ID = "session_" + Date.now();

    // Clear UI and show fresh welcome message
    const container = document.getElementById("chat-messages");
    container.innerHTML = `
        <div class="msg-row bot-row">
            <div class="avatar bot-avatar">🤖</div>
            <div class="bubble bot-bubble">
              <p>مرحباً! أنا مستشارك الأكاديمي الذكي في جامعة سفنكس 👋</p>
              <p>يمكنك سؤالي عن أي موضوع أكاديمي، أو أخبرني ببياناتك (ساعات، GPA، حضور) وهحللها فوراً!</p>
              <p class="msg-time">Now</p>
            </div>
        </div>
    `;
    
    // Refresh sidebar WITHOUT auto-loading any session
    loadChats(true);

    // Focus input
    document.getElementById("chat-input").focus();
}

// ================================
// AUTHENTICATION LOGIC
// ================================
async function checkAuth() {
    try {
        const res = await fetch(API_BASE + "/check_auth");
        const data = await res.json();
        if (data.logged_in) {
            document.getElementById("auth-modal").classList.remove("active");
            document.getElementById("user-info-display").textContent = "مرحباً، " + data.username;
            loadChats();
        } else {
            document.getElementById("auth-modal").classList.add("active");
        }
    } catch (err) {
        console.error("Auth check failed", err);
    }
}

function toggleAuthMode() {
    isLoginMode = !isLoginMode;
    document.getElementById("auth-error").textContent = "";
    document.getElementById("auth-username").value = "";
    document.getElementById("auth-password").value = "";
    
    if (isLoginMode) {
        document.getElementById("auth-title").textContent = "تسجيل الدخول";
        document.getElementById("auth-btn-text").textContent = "دخول";
        document.getElementById("auth-switch-text").textContent = "ليس لديك حساب؟";
        document.getElementById("auth-switch-link").textContent = "سجل الآن";
    } else {
        document.getElementById("auth-title").textContent = "إنشاء حساب";
        document.getElementById("auth-btn-text").textContent = "تسجيل";
        document.getElementById("auth-switch-text").textContent = "لديك حساب بالفعل؟";
        document.getElementById("auth-switch-link").textContent = "سجل الدخول";
    }
}

async function submitAuth() {
    const username = document.getElementById("auth-username").value.trim();
    const password = document.getElementById("auth-password").value.trim();
    const errorEl = document.getElementById("auth-error");
    
    if (!username || !password) {
        errorEl.textContent = "الرجاء إدخال اسم المستخدم وكلمة المرور";
        return;
    }
    
    errorEl.textContent = "جاري التحميل...";
    
    const endpoint = isLoginMode ? "/login" : "/register";
    try {
        const res = await fetch(API_BASE + endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password })
        });
        const data = await res.json();
        
        if (data.error) {
            errorEl.textContent = data.error;
        } else {
            errorEl.textContent = "";
            document.getElementById("auth-modal").classList.remove("active");
            document.getElementById("user-info-display").textContent = "مرحباً، " + data.username;
            loadChats();
        }
    } catch (err) {
        errorEl.textContent = "خطأ في الاتصال بالخادم";
    }
}

let allSessions = [];

async function logout() {
    try {
        await fetch(API_BASE + "/logout", { method: "POST" });
        document.getElementById("chat-messages").innerHTML = "";
        document.getElementById("user-info-display").textContent = "";
        document.getElementById("history-section").style.display = "none";
        document.getElementById("history-list").innerHTML = "";
        document.getElementById("auth-modal").classList.add("active");
    } catch (err) {
        console.error("Logout failed", err);
    }
}

async function loadChats(skipAutoLoad = false) {
    try {
        const res = await fetch(API_BASE + "/get_chats");
        const data = await res.json();
        if (data.success && data.sessions && data.sessions.length > 0) {
            allSessions = data.sessions;
            
            const historySection = document.getElementById("history-section");
            const historyList = document.getElementById("history-list");
            if(historySection) historySection.style.display = "block";
            if(historyList) historyList.innerHTML = "";
            
            data.sessions.forEach(session => {
                const btn = document.createElement("button");
                btn.className = "sidebar-item history-item";
                btn.textContent = "💬 " + session.title;
                btn.onclick = () => loadSession(session.session_id);
                if(historyList) historyList.appendChild(btn);
            });
            
            // Auto-load the most recent session only if not skipped
            if (!skipAutoLoad) {
                loadSession(data.sessions[0].session_id);
            }
        } else {
            const historySection = document.getElementById("history-section");
            if(historySection) historySection.style.display = "none";
        }
    } catch (err) {
        console.error("Failed to load chats", err);
    }
}

function loadSession(sessionId) {
    const session = allSessions.find(s => s.session_id === sessionId);
    if (!session) return;
    
    SESSION_ID = sessionId;
    
    const container = document.getElementById("chat-messages");
    container.innerHTML = `
        <div class="msg-row bot-row">
            <div class="avatar bot-avatar">🤖</div>
            <div class="bubble bot-bubble">
              <p>مرحباً بعودتك! أنا مستشارك الأكاديمي الذكي 👋</p>
              <p class="msg-time">Now</p>
            </div>
        </div>
    `;
    
    session.messages.forEach(msg => {
        appendMessage(msg.text, msg.sender);
    });
    
    switchTab('chat');
}

// ================================
// NAVIGATION & SIDEBAR
// ================================
function switchTab(tab) {
    // Hide all contents
    document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
    
    // Deactivate all nav items (sidebar items)
    document.querySelectorAll(".sidebar-item").forEach(el => el.classList.remove("active"));
    
    // Show target content
    const targetContent = document.getElementById("tab-" + tab);
    if (targetContent) targetContent.classList.add("active");
    
    // Activate target nav item
    const targetBtn = document.getElementById("tab-" + tab + "-btn");
    if (targetBtn) targetBtn.classList.add("active");

    // Close sidebar on mobile after clicking
    if (window.innerWidth <= 768) {
        document.getElementById("sidebar").classList.remove("open");
        const overlay = document.getElementById("sidebar-overlay");
        if (overlay) overlay.classList.remove("active");
    }
}

function toggleSidebar() {
    const sidebar = document.getElementById("sidebar");
    sidebar.classList.toggle("open");
    const overlay = document.getElementById("sidebar-overlay");
    if (overlay) overlay.classList.toggle("active");
}

// ================================
// HEALTH CHECK
// ================================
async function checkHealth() {
    try {
        const res = await fetch(API_BASE + "/health");
        if (res.ok) {
            const dot = document.querySelector(".status-dot");
            dot.classList.add("online");
            document.getElementById("status-text").textContent = "AI Online";
        }
    } catch {
        document.getElementById("status-text").textContent = "Offline — start app.py";
    }
}

// ================================
// CHAT LOGIC
// ================================
function getTime() {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function appendMessage(text, sender) {
    const container = document.getElementById("chat-messages");

    const row = document.createElement("div");
    row.className = "msg-row " + (sender === "user" ? "user-row" : "bot-row");

    const avatar = document.createElement("div");
    avatar.className = "avatar " + (sender === "user" ? "user-avatar" : "bot-avatar");
    avatar.textContent = sender === "user" ? "🧑" : "🤖";

    const bubble = document.createElement("div");
    bubble.className = "bubble " + (sender === "user" ? "user-bubble" : "bot-bubble");

    // Format markdown-like text
    bubble.innerHTML = formatText(text) + `<p class="msg-time">${getTime()}</p>`;

    row.appendChild(avatar);
    row.appendChild(bubble);
    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
}

function formatText(text) {
    // Convert **bold**, *italic*, newlines, numbered lists, bullets
    return text
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/```[\s\S]*?```/g, "")
        .replace(/#{1,3}\s(.+)/g, "<strong>$1</strong>")
        .replace(/\n/g, "<br>")
        .replace(/^- (.+)/gm, "• $1");
}

function showTyping() {
    const container = document.getElementById("chat-messages");
    const row = document.createElement("div");
    row.className = "msg-row bot-row";
    row.id = "typing-row";

    const avatar = document.createElement("div");
    avatar.className = "avatar bot-avatar";
    avatar.textContent = "🤖";

    const indicator = document.createElement("div");
    indicator.className = "typing-indicator";
    indicator.innerHTML = "<span></span><span></span><span></span>";

    row.appendChild(avatar);
    row.appendChild(indicator);
    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
}

function removeTyping() {
    const el = document.getElementById("typing-row");
    if (el) el.remove();
}

async function sendMessage() {
    const input = document.getElementById("chat-input");
    const btn = document.getElementById("send-btn");
    const text = input.value.trim();

    if (!text) return;

    appendMessage(text, "user");
    input.value = "";
    input.style.height = "auto";
    btn.disabled = true;
    showTyping();

    try {
        // إرسال الطلب إلى مسار الـ chat في الباك إند
        const res = await fetch(API_BASE + "/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text, session_id: SESSION_ID })
        });

        if (res.status === 401) {
            removeTyping();
            document.getElementById("auth-modal").classList.add("active");
            return;
        }

        // استقبال الرد اللي راجع من _handle_chat
        const data = await res.json();
        removeTyping();

        if (data.error) {
            // في حالة وجود خطأ (مثل 429 أو 500)
            appendMessage("⚠️ Error: " + data.error, "bot");
        } else {
            // عرض الـ reply اللي راجع من الباك إند
            appendMessage(data.reply, "bot");
            
            // تحديث القائمة الجانبية إذا كانت هذه الجلسة جديدة
            if (!allSessions.some(s => s.session_id === SESSION_ID)) {
                loadChats(true);
            }
        }
    } catch (err) {
        removeTyping();
        appendMessage("⚠️ Cannot connect to server. Make sure `app.py` is running on port 5000.", "bot");
    }

    btn.disabled = false;
    input.focus();
}
function handleKey(e) {
    // Auto-resize textarea
    const ta = document.getElementById("chat-input");
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px";

    // Send on Enter (not Shift+Enter)
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

// ================================
// REQUIREMENTS CHECKER
// ================================
function updateProgress(type, value, max) {
    const pct = Math.min((parseFloat(value) / max) * 100, 100);
    const bar = document.getElementById("prog-" + type);
    if (bar) {
        bar.style.width = pct + "%";
        // Color: green if above threshold, red if below
        let threshold = { hours: (138 / 138), gpa: (2.0 / 4.0), attendance: (75 / 100), years: (1.0) }[type];
        const ratio = parseFloat(value) / max;
        if (type === "years") {
            bar.style.background = ratio <= 1 ? "linear-gradient(90deg, #22c55e, #16a34a)" : "linear-gradient(90deg, #ef4444, #dc2626)";
        } else {
            bar.style.background = ratio >= threshold
                ? "linear-gradient(90deg, #22c55e, #16a34a)"
                : "linear-gradient(90deg, #ef4444, #dc2626)";
        }
    }
    updateQuickStatus();
}

function updateQuickStatus() {
    const hours = parseFloat(document.getElementById("req-hours").value) || 0;
    const gpa = parseFloat(document.getElementById("req-gpa").value) || 0;
    const att = parseFloat(document.getElementById("req-attendance").value) || 0;
    const years = parseFloat(document.getElementById("req-years").value) || 0;

    const set = (id, label, pass) => {
        const el = document.getElementById(id);
        el.textContent = label;
        el.className = "stat-item " + (pass ? "pass" : "fail");
    };

    if (hours > 0) set("stat-hours", `${hours >= 138 ? "✅" : "❌"} Credit Hours: ${hours}/138`, hours >= 138);
    if (gpa > 0) set("stat-gpa", `${gpa >= 2.0 ? "✅" : "❌"} GPA: ${gpa}/4.0`, gpa >= 2.0);
    if (att > 0) set("stat-att", `${att >= 75 ? "✅" : "❌"} Attendance: ${att}%`, att >= 75);
    if (years > 0) set("stat-years", `${years <= 8 ? "✅" : "❌"} Years: ${years}/8`, years <= 8);
}

async function checkRequirements() {
    const name = document.getElementById("req-name").value || "Student";
    const hours = parseFloat(document.getElementById("req-hours").value) || 0;
    const gpa = parseFloat(document.getElementById("req-gpa").value) || 0;
    const att = parseFloat(document.getElementById("req-attendance").value) || 0;
    const years = parseFloat(document.getElementById("req-years").value) || 0;

    if (!hours && !gpa && !att && !years) {
        alert("من فضلك أدخل بياناتك الأكاديمية أولاً");
        return;
    }

    const btn = document.getElementById("check-btn");
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> جاري التحليل بالـ AI...`;

    document.getElementById("result-placeholder").style.display = "none";
    document.getElementById("result-content").style.display = "none";

    try {
        const res = await fetch(API_BASE + "/check-requirements", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: name,
                credit_hours: hours,
                gpa: gpa,
                attendance: att,
                years: years
            })
        });

        const data = await res.json();

        if (data.error) {
            document.getElementById("result-placeholder").style.display = "flex";
            document.getElementById("result-placeholder").querySelector("p").textContent = "⚠️ " + data.error;
        } else {
            const verdict = document.getElementById("verdict-badge");
            const resultText = document.getElementById("result-text");
            const resultContent = document.getElementById("result-content");

            verdict.textContent = data.can_graduate
                ? "🎓 مؤهل للتخرج — Eligible to Graduate"
                : "📚 غير مؤهل بعد — Not Eligible Yet";
            verdict.className = "verdict-badge " + (data.can_graduate ? "can-graduate" : "cannot-graduate");

            resultText.textContent = data.analysis;
            resultContent.style.display = "flex";
        }

    } catch (err) {
        document.getElementById("result-placeholder").style.display = "flex";
        document.getElementById("result-placeholder").querySelector("p").textContent =
            "⚠️ Cannot connect to server. Make sure app.py is running.";
    }

    btn.disabled = false;
    btn.innerHTML = "<span>🔍 تحليل بـ AI</span>";
}

// ================================
// INIT
// ================================
document.addEventListener("DOMContentLoaded", () => {
    checkHealth();
    checkAuth();
    // Re-check every 10 seconds
    setInterval(checkHealth, 10000);
});
