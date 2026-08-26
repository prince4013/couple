import os
import sqlite3
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import (
    Flask, g, render_template, request, redirect,
    url_for, session, flash
)
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "couple_app.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

# 如果有設定 DATABASE_URL（例如 Supabase 給的 Postgres 連線字串），
# 就會改用 Postgres；沒有設定的話，退回用本機的 SQLite 檔案，
# 方便你在自己電腦上不用連 Supabase 也能開發測試。
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB 上限

GIFT_LABELS = {
    "heart": ("愛心", "ti-heart"),
    "cake": ("蛋糕", "ti-cake"),
    "coffee": ("咖啡", "ti-coffee"),
    "bouquet": ("花束", "ti-flower"),
    "miss_you": ("想你了", "ti-heart-filled"),
}

# 固定雙方地點（依需求直接寫死，不再開放編輯）
LOCATIONS = {
    "a": {"city": "新竹", "timezone": "Asia/Taipei", "lat": 24.8138, "lon": 120.9675},
    "b": {"city": "Glasgow", "timezone": "Europe/London", "lat": 55.8642, "lon": -4.2518},
}

# Open-Meteo 天氣代碼(WMO) 對照：(說明文字, tabler icon class)
WEATHER_CODES = {
    0: ("晴朗", "ti-sun"),
    1: ("晴時多雲", "ti-cloud-sun"),
    2: ("多雲", "ti-cloud"),
    3: ("陰天", "ti-cloud"),
    45: ("有霧", "ti-cloud-fog"),
    48: ("有霧", "ti-cloud-fog"),
    51: ("毛毛雨", "ti-cloud-drizzle"),
    53: ("毛毛雨", "ti-cloud-drizzle"),
    55: ("毛毛雨", "ti-cloud-drizzle"),
    56: ("凍雨", "ti-cloud-drizzle"),
    57: ("凍雨", "ti-cloud-drizzle"),
    61: ("小雨", "ti-cloud-rain"),
    63: ("下雨", "ti-cloud-rain"),
    65: ("大雨", "ti-cloud-rain"),
    66: ("凍雨", "ti-cloud-rain"),
    67: ("凍雨", "ti-cloud-rain"),
    71: ("小雪", "ti-snowflake"),
    73: ("下雪", "ti-snowflake"),
    75: ("大雪", "ti-snowflake"),
    77: ("下雪", "ti-snowflake"),
    80: ("陣雨", "ti-cloud-rain"),
    81: ("陣雨", "ti-cloud-rain"),
    82: ("強陣雨", "ti-cloud-rain"),
    85: ("陣雪", "ti-snowflake"),
    86: ("強陣雪", "ti-snowflake"),
    95: ("雷雨", "ti-cloud-lightning"),
    96: ("雷雨伴冰雹", "ti-cloud-lightning"),
    99: ("雷雨伴冰雹", "ti-cloud-lightning"),
}

WEATHER_CACHE_MINUTES = 15


# ---------- 資料庫 ----------

def get_db():
    if "db" not in g:
        if USE_POSTGRES:
            g.db = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            g.db = sqlite3.connect(DB_PATH)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def run(db, sql, params=()):
    """統一介面：跨 SQLite / Postgres 執行 SQL，並自動把 ? 轉成 Postgres 需要的 %s。"""
    cur = db.cursor()
    if USE_POSTGRES:
        sql = sql.replace("?", "%s")
    cur.execute(sql, params)
    return cur


def init_db():
    id_type = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ph = "%s" if USE_POSTGRES else "?"

    conn = psycopg2.connect(DATABASE_URL) if USE_POSTGRES else sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    schema_statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            gender TEXT NOT NULL,
            city TEXT NOT NULL,
            timezone TEXT NOT NULL,
            status TEXT DEFAULT '',
            avatar_color TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS messages (
            id {id_type},
            sender_id TEXT NOT NULL,
            text TEXT,
            image_filename TEXT,
            created_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS gifts (
            id {id_type},
            sender_id TEXT NOT NULL,
            gift_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS questions (
            id {id_type},
            asker_id TEXT NOT NULL,
            question_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS question_replies (
            id {id_type},
            question_id INTEGER NOT NULL,
            sender_id TEXT NOT NULL,
            reply_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (question_id) REFERENCES questions(id)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS checklist_items (
            id {id_type},
            category TEXT NOT NULL,
            text TEXT NOT NULL,
            is_done INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS status_options (
            id {id_type},
            gender TEXT NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """,
    ]
    for stmt in schema_statements:
        cur.execute(stmt)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM users")
    user_count = cur.fetchone()[0]

    if user_count == 0:
        row7 = "(" + ",".join([ph] * 7) + ")"
        cur.execute(
            f"INSERT INTO users VALUES {row7}",
            ("a", "幸運老婆", "f", LOCATIONS["a"]["city"], LOCATIONS["a"]["timezone"], "想你", "#D85A30"),
        )
        cur.execute(
            f"INSERT INTO users VALUES {row7}",
            ("b", "香噴噴包子", "m", LOCATIONS["b"]["city"], LOCATIONS["b"]["timezone"], "工作好多", "#EF9F27"),
        )
        cur.execute(
            f"INSERT INTO settings VALUES ({ph}, {ph})",
            ("meeting_date", "2026-12-18"),
        )

        ts = now_str()
        row4 = "(" + ",".join([ph] * 4) + ")"
        values_sql = ",".join([row4] * 5)
        cur.execute(
            f"INSERT INTO checklist_items (category, text, is_done, created_at) VALUES {values_sql}",
            (
                "bring", "護照", 1, ts,
                "bring", "給對方的禮物", 0, ts,
                "bring", "充電器 / 轉接頭", 0, ts,
                "place", "下北澤選物咖啡廳", 0, ts,
                "place", "江之島看夕陽", 0, ts,
            ),
        )

        female_defaults = ["開心", "沒睡好", "祕書長好煩", "想你", "麵今天不乖", "工作好多"]
        male_defaults = ["開心", "累", "想你", "好多功課"]
        status_rows = [("f", label) for label in female_defaults] + [("m", label) for label in male_defaults]
        status_params = []
        for gender, label in status_rows:
            status_params.extend([gender, label, ts])
        row3 = "(" + ",".join([ph] * 3) + ")"
        status_values_sql = ",".join([row3] * len(status_rows))
        cur.execute(
            f"INSERT INTO status_options (gender, label, created_at) VALUES {status_values_sql}",
            tuple(status_params),
        )
        conn.commit()

    cur.close()
    conn.close()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fetch_user(uid):
    return run(get_db(), "SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def other_id(uid):
    return "b" if uid == "a" else "a"


def get_setting(key, default=None):
    row = run(get_db(), "SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    db = get_db()
    run(
        db,
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    db.commit()


def current_user_id():
    return session.get("me", "a")


# ---------- 天氣（Open-Meteo，免金鑰） ----------

def describe_weather(code):
    return WEATHER_CODES.get(code, ("天氣不明", "ti-cloud"))


def fetch_weather_from_api(lat, lon):
    """呼叫 Open-Meteo 取得即時天氣，失敗時拋出例外由呼叫端處理。"""
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={"latitude": lat, "longitude": lon, "current_weather": "true"},
        timeout=6,
    )
    resp.raise_for_status()
    current = resp.json()["current_weather"]
    return round(current["temperature"]), int(current["weathercode"])


def get_weather_display(uid):
    """回傳 {'text': '18°C 小雨', 'icon': 'ti-cloud-rain'}，並用 settings 表快取 15 分鐘。"""
    loc = LOCATIONS[uid]
    time_key, temp_key, code_key = f"weather_{uid}_time", f"weather_{uid}_temp", f"weather_{uid}_code"

    cached_time = get_setting(time_key)
    is_stale = True
    if cached_time:
        try:
            is_stale = datetime.now() - datetime.fromisoformat(cached_time) > timedelta(minutes=WEATHER_CACHE_MINUTES)
        except ValueError:
            is_stale = True

    if is_stale:
        try:
            temp, code = fetch_weather_from_api(loc["lat"], loc["lon"])
            set_setting(temp_key, str(temp))
            set_setting(code_key, str(code))
            set_setting(time_key, datetime.now().isoformat())
        except (requests.RequestException, KeyError, ValueError):
            pass  # 抓取失敗就沿用快取中的舊值，不中斷頁面

    temp, code = get_setting(temp_key), get_setting(code_key)
    if temp is None:
        return {"text": "天氣資料取得中...", "icon": "ti-cloud"}
    desc, icon = describe_weather(int(code))
    return {"text": f"{temp}°C {desc}", "icon": icon}


@app.context_processor
def inject_globals():
    a = fetch_user("a")
    b = fetch_user("b")
    return {
        "me_id": current_user_id(),
        "gift_labels": GIFT_LABELS,
        "user_names": {"a": a["name"], "b": b["name"]},
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

    partner_weather = get_weather_display(other_id(current_user_id()))

    meeting_date_str = get_setting("meeting_date")
    days_left = None
    if meeting_date_str:
        try:
            m_date = date.fromisoformat(meeting_date_str)
            days_left = (m_date - date.today()).days
        except ValueError:
            days_left = None

    db = get_db()
    recent_gifts = run(db, "SELECT * FROM gifts ORDER BY id DESC LIMIT 5").fetchall()
    latest_question = run(db, "SELECT * FROM questions ORDER BY id DESC LIMIT 1").fetchone()

    status_options = run(
        db, "SELECT * FROM status_options WHERE gender = ? ORDER BY id ASC", (me["gender"],)
    ).fetchall()

    return render_template(
        "home.html",
        me=me,
        partner=partner,
        partner_time=partner_time,
        partner_weather=partner_weather,
        days_left=days_left,
        meeting_date=meeting_date_str,
        recent_gifts=recent_gifts,
        latest_question=latest_question,
        status_options=status_options,
    )


@app.route("/update_status", methods=["POST"])
def update_status():
    status = request.form.get("status", "").strip()
    db = get_db()
    run(db, "UPDATE users SET status = ? WHERE id = ?", (status, current_user_id()))
    db.commit()
    flash("已更新你的狀態")
    return redirect(url_for("home"))


@app.route("/status_options/add", methods=["POST"])
def add_status_option():
    label = request.form.get("label", "").strip()
    if label:
        me = fetch_user(current_user_id())
        db = get_db()
        run(
            db,
            "INSERT INTO status_options (gender, label, created_at) VALUES (?, ?, ?)",
            (me["gender"], label, now_str()),
        )
        db.commit()
    return redirect(url_for("home"))


@app.route("/status_options/delete/<int:option_id>", methods=["POST"])
def delete_status_option(option_id):
    db = get_db()
    run(db, "DELETE FROM status_options WHERE id = ?", (option_id,))
    db.commit()
    return redirect(url_for("home"))


@app.route("/gift/<gift_type>", methods=["POST"])
def send_gift(gift_type):
    if gift_type not in GIFT_LABELS:
        flash("不支援的禮物類型")
        return redirect(url_for("home"))
    db = get_db()
    run(
        db,
        "INSERT INTO gifts (sender_id, gift_type, created_at) VALUES (?, ?, ?)",
        (current_user_id(), gift_type, now_str()),
    )
    db.commit()
    label = GIFT_LABELS[gift_type][0]
    flash(f"已送出「{label}」給對方")
    return redirect(url_for("home"))


@app.route("/gifts/clear", methods=["POST"])
def clear_gifts():
    db = get_db()
    run(db, "DELETE FROM gifts")
    db.commit()
    flash("已清除「最近的禮物」記錄")
    return redirect(url_for("settings"))


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
            run(
                db,
                "INSERT INTO messages (sender_id, text, image_filename, created_at) VALUES (?,?,?,?)",
                (current_user_id(), text or None, image_filename, now_str()),
            )
            db.commit()
        return redirect(url_for("messages"))

    db = get_db()
    msgs = run(db, "SELECT * FROM messages ORDER BY id ASC").fetchall()
    me = fetch_user(current_user_id())
    partner = fetch_user(other_id(current_user_id()))
    return render_template("messages.html", messages=msgs, me=me, partner=partner)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


@app.route("/questions")
def questions():
    db = get_db()
    rows = run(
        db,
        """
        SELECT q.*,
               (SELECT COUNT(*) FROM question_replies r WHERE r.question_id = q.id) AS reply_count
        FROM questions q
        ORDER BY q.id DESC
        """,
    ).fetchall()
    return render_template("questions.html", threads=rows)


@app.route("/questions/new", methods=["POST"])
def new_question():
    text = request.form.get("question_text", "").strip()
    if text:
        db = get_db()
        cur = run(
            db,
            "INSERT INTO questions (asker_id, question_text, created_at) VALUES (?,?,?) RETURNING id",
            (current_user_id(), text, now_str()),
        )
        new_id = cur.fetchone()["id"]
        db.commit()
        return redirect(url_for("question_thread", qid=new_id))
    return redirect(url_for("questions"))


@app.route("/questions/<int:qid>", methods=["GET", "POST"])
def question_thread(qid):
    db = get_db()
    if request.method == "POST":
        reply_text = request.form.get("reply_text", "").strip()
        if reply_text:
            run(
                db,
                "INSERT INTO question_replies (question_id, sender_id, reply_text, created_at) VALUES (?,?,?,?)",
                (qid, current_user_id(), reply_text, now_str()),
            )
            db.commit()
        return redirect(url_for("question_thread", qid=qid))

    question = run(db, "SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
    if question is None:
        flash("找不到這個問題")
        return redirect(url_for("questions"))
    replies = run(
        db, "SELECT * FROM question_replies WHERE question_id = ? ORDER BY id ASC", (qid,)
    ).fetchall()
    return render_template("question_thread.html", question=question, replies=replies)


@app.route("/checklist")
def checklist():
    db = get_db()
    bring_items = run(db, "SELECT * FROM checklist_items WHERE category = 'bring' ORDER BY id ASC").fetchall()
    place_items = run(db, "SELECT * FROM checklist_items WHERE category = 'place' ORDER BY id ASC").fetchall()
    return render_template("checklist.html", bring_items=bring_items, place_items=place_items)


@app.route("/checklist/toggle/<int:item_id>", methods=["POST"])
def toggle_checklist(item_id):
    db = get_db()
    run(db, "UPDATE checklist_items SET is_done = 1 - is_done WHERE id = ?", (item_id,))
    db.commit()
    return redirect(url_for("checklist"))


@app.route("/checklist/add", methods=["POST"])
def add_checklist_item():
    category = request.form.get("category")
    text = request.form.get("text", "").strip()
    if text and category in ("bring", "place"):
        db = get_db()
        run(
            db,
            "INSERT INTO checklist_items (category, text, is_done, created_at) VALUES (?,?,0,?)",
            (category, text, now_str()),
        )
        db.commit()
    return redirect(url_for("checklist"))


@app.route("/checklist/delete/<int:item_id>", methods=["POST"])
def delete_checklist_item(item_id):
    db = get_db()
    run(db, "DELETE FROM checklist_items WHERE id = ?", (item_id,))
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
            if name:
                run(db, "UPDATE users SET name = ? WHERE id = ?", (name, uid))
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
        locations=LOCATIONS,
    )


# 不論是 `python app.py` 本機執行，還是被 gunicorn 匯入，
# 都要確保資料夾與資料表已經準備好。
os.makedirs(UPLOAD_DIR, exist_ok=True)
init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug_mode = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug_mode, host="0.0.0.0", port=port)
