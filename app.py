import os
import sqlite3
from datetime import datetime, date
from zoneinfo import ZoneInfo

from flask import (
    Flask, g, render_template, request, redirect,
    url_for, session, flash
)
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "couple_app.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-me"
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB 上限

FEMALE_STATUSES = ["開心", "沒睡好", "祕書長好煩", "想你", "麵今天不乖", "工作好多"]
MALE_STATUSES = ["開心", "累", "想你", "好多功課"]

GIFT_LABELS = {
    "heart": ("愛心", "ti-heart"),
    "cake": ("蛋糕", "ti-cake"),
    "coffee": ("咖啡", "ti-coffee"),
    "miss_you": ("想你了", "ti-heart-filled"),
}

COMMON_TIMEZONES = [
    "Asia/Taipei", "Asia/Tokyo", "Asia/Seoul", "Asia/Hong_Kong",
    "Asia/Shanghai", "Asia/Singapore", "Asia/Bangkok",
    "Europe/London", "Europe/Paris", "Europe/Berlin",
    "America/Los_Angeles", "America/New_York", "America/Chicago",
    "Australia/Sydney", "Pacific/Auckland",
]


# ---------- 資料庫 ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    first_time = not os.path.exists(DB_PATH)
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            gender TEXT NOT NULL,
            city TEXT NOT NULL,
            timezone TEXT NOT NULL,
            weather TEXT DEFAULT '',
            status TEXT DEFAULT '',
            avatar_color TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT NOT NULL,
            text TEXT,
            image_filename TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT NOT NULL,
            gift_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asker_id TEXT NOT NULL,
            question_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS question_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            sender_id TEXT NOT NULL,
            reply_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (question_id) REFERENCES questions(id)
        );

        CREATE TABLE IF NOT EXISTS checklist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            text TEXT NOT NULL,
            is_done INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    if first_time:
        db.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
            ("a", "美", "f", "台北", "Asia/Taipei", "26°C 晴", "想你", "#D85A30"),
        )
        db.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?)",
            ("b", "Alex", "m", "東京", "Asia/Tokyo", "18°C 小雨", "工作好多", "#EF9F27"),
        )
        db.execute(
            "INSERT INTO settings VALUES ('meeting_date', ?)",
            ("2026-12-18",),
        )
        db.execute(
            "INSERT INTO checklist_items (category, text, is_done, created_at) VALUES "
            "('bring','護照',1,?), ('bring','給對方的禮物',0,?), "
            "('bring','充電器 / 轉接頭',0,?), "
            "('place','下北澤選物咖啡廳',0,?), ('place','江之島看夕陽',0,?)",
            (now_str(), now_str(), now_str(), now_str(), now_str()),
        )
        db.commit()
    db.close()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fetch_user(uid):
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return row


def other_id(uid):
    return "b" if uid == "a" else "a"


def get_setting(key, default=None):
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    db = get_db()
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    db.commit()


def current_user_id():
    return session.get("me", "a")


@app.context_processor
def inject_globals():
    return {
        "me_id": current_user_id(),
        "gift_labels": GIFT_LABELS,
    }


# ---------- 路由 ----------

@app.route("/")
def index():
    return redirect(url_for("home"))


@app.route("/switch/<uid>")
def switch(uid):
    if uid in ("a", "b"):
        session["me"] = uid
    return redirect(request.referrer or url_for("home"))


@app.route("/home")
def home():
    me = fetch_user(current_user_id())
    partner = fetch_user(other_id(current_user_id()))

    try:
        partner_time = datetime.now(ZoneInfo(partner["timezone"])).strftime("%H:%M")
    except Exception:
        partner_time = "--:--"

    meeting_date_str = get_setting("meeting_date")
    days_left = None
    if meeting_date_str:
        try:
            m_date = date.fromisoformat(meeting_date_str)
            days_left = (m_date - date.today()).days
        except ValueError:
            days_left = None

    db = get_db()
    recent_gifts = db.execute(
        "SELECT * FROM gifts ORDER BY id DESC LIMIT 5"
    ).fetchall()
    latest_question = db.execute(
        "SELECT * FROM questions ORDER BY id DESC LIMIT 1"
    ).fetchone()

    status_options = FEMALE_STATUSES if me["gender"] == "f" else MALE_STATUSES

    return render_template(
        "home.html",
        me=me,
        partner=partner,
        partner_time=partner_time,
        days_left=days_left,
        meeting_date=meeting_date_str,
        recent_gifts=recent_gifts,
        latest_question=latest_question,
        status_options=status_options,
    )


@app.route("/update_status", methods=["POST"])
def update_status():
    status = request.form.get("status", "").strip()
    weather = request.form.get("weather", "").strip()
    db = get_db()
    db.execute(
        "UPDATE users SET status = ?, weather = ? WHERE id = ?",
        (status, weather, current_user_id()),
    )
    db.commit()
    flash("已更新你的狀態")
    return redirect(url_for("home"))


@app.route("/gift/<gift_type>", methods=["POST"])
def send_gift(gift_type):
    if gift_type not in GIFT_LABELS:
        flash("不支援的禮物類型")
        return redirect(url_for("home"))
    db = get_db()
    db.execute(
        "INSERT INTO gifts (sender_id, gift_type, created_at) VALUES (?, ?, ?)",
        (current_user_id(), gift_type, now_str()),
    )
    db.commit()
    label = GIFT_LABELS[gift_type][0]
    flash(f"已送出「{label}」給對方")
    return redirect(url_for("home"))


@app.route("/messages", methods=["GET", "POST"])
def messages():
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        image_filename = None
        file = request.files.get("image")
        if file and file.filename and allowed_file(file.filename):
            image_filename = f"{int(datetime.now().timestamp())}_{secure_filename(file.filename)}"
            file.save(os.path.join(UPLOAD_DIR, image_filename))
        if text or image_filename:
            db = get_db()
            db.execute(
                "INSERT INTO messages (sender_id, text, image_filename, created_at) VALUES (?,?,?,?)",
                (current_user_id(), text or None, image_filename, now_str()),
            )
            db.commit()
        return redirect(url_for("messages"))

    db = get_db()
    msgs = db.execute("SELECT * FROM messages ORDER BY id ASC").fetchall()
    me = fetch_user(current_user_id())
    partner = fetch_user(other_id(current_user_id()))
    return render_template("messages.html", messages=msgs, me=me, partner=partner)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


@app.route("/questions")
def questions():
    db = get_db()
    rows = db.execute(
        """
        SELECT q.*,
               (SELECT COUNT(*) FROM question_replies r WHERE r.question_id = q.id) AS reply_count
        FROM questions q
        ORDER BY q.id DESC
        """
    ).fetchall()
    return render_template("questions.html", threads=rows)


@app.route("/questions/new", methods=["POST"])
def new_question():
    text = request.form.get("question_text", "").strip()
    if text:
        db = get_db()
        cur = db.execute(
            "INSERT INTO questions (asker_id, question_text, created_at) VALUES (?,?,?)",
            (current_user_id(), text, now_str()),
        )
        db.commit()
        return redirect(url_for("question_thread", qid=cur.lastrowid))
    return redirect(url_for("questions"))


@app.route("/questions/<int:qid>", methods=["GET", "POST"])
def question_thread(qid):
    db = get_db()
    if request.method == "POST":
        reply_text = request.form.get("reply_text", "").strip()
        if reply_text:
            db.execute(
                "INSERT INTO question_replies (question_id, sender_id, reply_text, created_at) VALUES (?,?,?,?)",
                (qid, current_user_id(), reply_text, now_str()),
            )
            db.commit()
        return redirect(url_for("question_thread", qid=qid))

    question = db.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
    if question is None:
        flash("找不到這個問題")
        return redirect(url_for("questions"))
    replies = db.execute(
        "SELECT * FROM question_replies WHERE question_id = ? ORDER BY id ASC", (qid,)
    ).fetchall()
    return render_template("question_thread.html", question=question, replies=replies)


@app.route("/checklist")
def checklist():
    db = get_db()
    bring_items = db.execute(
        "SELECT * FROM checklist_items WHERE category = 'bring' ORDER BY id ASC"
    ).fetchall()
    place_items = db.execute(
        "SELECT * FROM checklist_items WHERE category = 'place' ORDER BY id ASC"
    ).fetchall()
    return render_template("checklist.html", bring_items=bring_items, place_items=place_items)


@app.route("/checklist/toggle/<int:item_id>", methods=["POST"])
def toggle_checklist(item_id):
    db = get_db()
    db.execute(
        "UPDATE checklist_items SET is_done = 1 - is_done WHERE id = ?", (item_id,)
    )
    db.commit()
    return redirect(url_for("checklist"))


@app.route("/checklist/add", methods=["POST"])
def add_checklist_item():
    category = request.form.get("category")
    text = request.form.get("text", "").strip()
    if text and category in ("bring", "place"):
        db = get_db()
        db.execute(
            "INSERT INTO checklist_items (category, text, is_done, created_at) VALUES (?,?,0,?)",
            (category, text, now_str()),
        )
        db.commit()
    return redirect(url_for("checklist"))


@app.route("/checklist/delete/<int:item_id>", methods=["POST"])
def delete_checklist_item(item_id):
    db = get_db()
    db.execute("DELETE FROM checklist_items WHERE id = ?", (item_id,))
    db.commit()
    return redirect(url_for("checklist"))


@app.route("/settings", methods=["GET", "POST"])
def settings():
    db = get_db()
    if request.method == "POST":
        meeting_date = request.form.get("meeting_date", "").strip()
        if meeting_date:
            set_setting("meeting_date", meeting_date)

        for uid in ("a", "b"):
            name = request.form.get(f"name_{uid}", "").strip()
            city = request.form.get(f"city_{uid}", "").strip()
            timezone = request.form.get(f"timezone_{uid}", "").strip()
            if name and city and timezone:
                db.execute(
                    "UPDATE users SET name = ?, city = ?, timezone = ? WHERE id = ?",
                    (name, city, timezone, uid),
                )
        db.commit()
        flash("設定已儲存")
        return redirect(url_for("settings"))

    user_a = fetch_user("a")
    user_b = fetch_user("b")
    meeting_date = get_setting("meeting_date")
    return render_template(
        "settings.html",
        user_a=user_a,
        user_b=user_b,
        meeting_date=meeting_date,
        timezones=COMMON_TIMEZONES,
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="127.0.0.1", port=5050)
