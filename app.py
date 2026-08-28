import json
import os
import re
import sqlite3
from datetime import datetime, date, timedelta
from html.parser import HTMLParser
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from flask import (
    Flask, g, render_template, request, redirect,
    url_for, session, flash, jsonify
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

# Supabase Storage：回憶相簿的照片要永久保存，就必須存在這裡，
# 不能存在 Render 本機磁碟（重新部署會不見）。
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "memories").strip()
SUPABASE_STORAGE_ENABLED = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)

# Web Push（讓對方即時收到「想你了」之類的推播通知）需要一組 VAPID 金鑰。
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
VAPID_CLAIM_EMAIL = os.environ.get("VAPID_CLAIM_EMAIL", "example@example.com").strip()
PUSH_ENABLED = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)

if PUSH_ENABLED:
    from pywebpush import webpush, WebPushException

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
        f"""
        CREATE TABLE IF NOT EXISTS memories (
            id {id_type},
            sender_id TEXT NOT NULL,
            image_url TEXT NOT NULL,
            memory_date TEXT NOT NULL,
            caption TEXT,
            created_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id {id_type},
            user_id TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS blog_posts (
            id {id_type},
            sender_id TEXT NOT NULL,
            content TEXT,
            image_url TEXT,
            youtube_url TEXT,
            youtube_title TEXT,
            youtube_thumbnail TEXT,
            created_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS blog_comments (
            id {id_type},
            post_id INTEGER NOT NULL,
            sender_id TEXT NOT NULL,
            comment_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (post_id) REFERENCES blog_posts(id)
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

    # 輕量欄位遷移：CREATE TABLE IF NOT EXISTS 不會幫已經存在的資料表加新欄位，
    # 這裡手動確保 blog_posts 有「通用連結預覽」需要的欄位（不限 YouTube）。
    def ensure_column(table, column, col_type):
        if USE_POSTGRES:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}")
        else:
            cur.execute(f"PRAGMA table_info({table})")
            existing_cols = [row[1] for row in cur.fetchall()]
            if column not in existing_cols:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    ensure_column("blog_posts", "link_url", "TEXT")
    ensure_column("blog_posts", "link_title", "TEXT")
    ensure_column("blog_posts", "link_thumbnail", "TEXT")
    ensure_column("blog_posts", "link_domain", "TEXT")
    ensure_column("blog_posts", "link_is_youtube", "INTEGER")
    conn.commit()

    # 把進度條起點設成指定的日期（2026-07-26）。用一個遷移旗標確保這件事
    # 只在第一次套用這次更新時強制蓋過去一次，之後如果使用者自己在設定頁
    # 改了見面日期、觸發了自動重設，就不會被這裡的邏輯再蓋回去。
    cur.execute(f"SELECT value FROM settings WHERE key = {ph}", ("countdown_start_migrated_20260726",))
    already_migrated = cur.fetchone() is not None
    if not already_migrated:
        cur.execute(
            "INSERT INTO settings (key, value) VALUES "
            f"({ph}, {ph}) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("countdown_start_date", "2026-07-26"),
        )
        cur.execute(
            f"INSERT INTO settings VALUES ({ph}, {ph})",
            ("countdown_start_migrated_20260726", "1"),
        )
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


# ---------- Supabase Storage（回憶相簿的照片） ----------

def upload_to_supabase_storage(file_storage, filename):
    """把上傳的檔案存到 Supabase Storage，回傳可公開存取的網址。
    沒有設定 SUPABASE_URL / SUPABASE_SERVICE_KEY 時會拋出例外，呼叫端要接住。"""
    if not SUPABASE_STORAGE_ENABLED:
        raise RuntimeError("尚未設定 Supabase Storage（缺少 SUPABASE_URL 或 SUPABASE_SERVICE_KEY）")

    upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/{filename}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": file_storage.mimetype or "application/octet-stream",
        "x-upsert": "true",
    }
    resp = requests.post(upload_url, headers=headers, data=file_storage.read(), timeout=20)
    resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/{filename}"


# ---------- 連結預覽（YouTube 用專屬 API，其他網站用通用的 og 標籤解析） ----------

YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([a-zA-Z0-9_-]{11})"
)


def extract_youtube_id(url):
    if not url:
        return None
    match = YOUTUBE_ID_RE.search(url)
    return match.group(1) if match else None


def fetch_youtube_title(url):
    """呼叫 YouTube 的公開 oEmbed API 拿標題，不需要金鑰。失敗就回傳 None。"""
    try:
        resp = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=6,
        )
        resp.raise_for_status()
        return resp.json().get("title")
    except (requests.RequestException, ValueError, KeyError):
        return None


class _MetaTagParser(HTMLParser):
    """輕量 HTML 解析器，只抓 <title> 跟 Open Graph 的 og:title / og:image。
    大部分網站（Threads、Instagram、新聞網站...）都會放這些標籤給連結預覽用。"""

    def __init__(self):
        super().__init__()
        self.title = None
        self.og_title = None
        self.og_image = None
        self._in_title_tag = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "meta":
            prop = attrs_dict.get("property") or attrs_dict.get("name") or ""
            content = attrs_dict.get("content")
            if content:
                if prop.lower() == "og:title":
                    self.og_title = content
                elif prop.lower() == "og:image":
                    self.og_image = content
        elif tag == "title":
            self._in_title_tag = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title_tag = False

    def handle_data(self, data):
        if self._in_title_tag and not self.title:
            self.title = data.strip()


def fetch_link_preview(url):
    """通用連結預覽：回傳 (title, thumbnail_url, domain)。抓不到的部分回傳 None，
    網域一定拿得到（純字串解析網址，不需要真的連線）。"""
    domain = urlparse(url).netloc.replace("www.", "") or url
    title, thumbnail = None, None
    try:
        resp = requests.get(
            url,
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CoupleAppLinkPreview/1.0)"},
        )
        content_type = resp.headers.get("Content-Type", "")
        if resp.ok and "text/html" in content_type:
            parser = _MetaTagParser()
            parser.feed(resp.text[:200000])  # 只解析前面一段，避免超大頁面拖慢速度
            title = parser.og_title or parser.title
            thumbnail = parser.og_image
    except requests.RequestException:
        pass
    return title, thumbnail, domain


# ---------- Web Push（即時推播通知） ----------

def send_push_to_user(uid, title, body, url_path="/home"):
    """推播給某個使用者的所有已訂閱裝置。沒設定 VAPID 金鑰時直接跳過，不影響原本功能。"""
    if not PUSH_ENABLED:
        return
    db = get_db()
    subs = run(db, "SELECT * FROM push_subscriptions WHERE user_id = ?", (uid,)).fetchall()
    payload = json.dumps({"title": title, "body": body, "url": url_path})
    for sub in subs:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{VAPID_CLAIM_EMAIL}"},
            )
        except WebPushException as ex:
            status = ex.response.status_code if ex.response is not None else None
            if status in (404, 410):
                # 訂閱已經失效（例如對方移除了 App 或很久沒開），順手清掉，避免每次都白跑一趟
                run(db, "DELETE FROM push_subscriptions WHERE id = ?", (sub["id"],))
                db.commit()


@app.context_processor
def inject_globals():
    a = fetch_user("a")
    b = fetch_user("b")
    return {
        "me_id": current_user_id(),
        "gift_labels": GIFT_LABELS,
        "user_names": {"a": a["name"], "b": b["name"]},
        "push_enabled": PUSH_ENABLED,
        "vapid_public_key": VAPID_PUBLIC_KEY,
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
    weeks_left, weeks_remaining_days = None, None
    progress_percent = None
    if meeting_date_str:
        try:
            m_date = date.fromisoformat(meeting_date_str)
            days_left = (m_date - date.today()).days
            weeks_left, weeks_remaining_days = divmod(max(days_left, 0), 7)
        except ValueError:
            days_left = None

        start_date_str = get_setting("countdown_start_date")
        if start_date_str:
            try:
                start_date = date.fromisoformat(start_date_str)
                total_days = (m_date - start_date).days
                elapsed_days = (date.today() - start_date).days
                if total_days > 0:
                    progress_percent = max(0, min(100, round(elapsed_days / total_days * 100)))
                else:
                    progress_percent = 100
            except ValueError:
                progress_percent = None

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
        weeks_left=weeks_left,
        weeks_remaining_days=weeks_remaining_days,
        progress_percent=progress_percent,
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

    me = fetch_user(current_user_id())
    if gift_type == "miss_you":
        send_push_to_user(other_id(current_user_id()), f"{me['name']} 想你了 💛", "點開來回應對方一下吧")
    else:
        send_push_to_user(other_id(current_user_id()), f"{me['name']} 送你「{label}」", "打開 App 看看吧")

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
            filename = f"{int(datetime.now().timestamp())}_{secure_filename(file.filename)}"
            if SUPABASE_STORAGE_ENABLED:
                # 存到 Supabase Storage，這樣 Render 重新部署後圖片才不會消失
                try:
                    image_filename = upload_to_supabase_storage(file, f"messages/{filename}")
                except (requests.RequestException, RuntimeError) as ex:
                    flash(f"上傳圖片失敗：{ex}")
            else:
                # 沒設定 Supabase Storage 時，退回存在 Render 本機磁碟
                # ⚠️ 這種狀況下，圖片會在下次重新部署後消失
                file.save(os.path.join(UPLOAD_DIR, filename))
                image_filename = filename
        if text or image_filename:
            db = get_db()
            run(
                db,
                "INSERT INTO messages (sender_id, text, image_filename, created_at) VALUES (?,?,?,?)",
                (current_user_id(), text or None, image_filename, now_str()),
            )
            db.commit()
            me = fetch_user(current_user_id())
            preview = text if text else "傳了一張照片"
            send_push_to_user(other_id(current_user_id()), f"{me['name']} 留言給你", preview, "/messages")
            if image_filename:
                flash("圖片已上傳")
        return redirect(url_for("messages"))

    db = get_db()
    msgs = run(db, "SELECT * FROM messages ORDER BY id ASC").fetchall()
    me = fetch_user(current_user_id())
    partner = fetch_user(other_id(current_user_id()))
    return render_template("messages.html", messages=msgs, me=me, partner=partner)



@app.route("/messages/delete/<int:message_id>", methods=["POST"])
def delete_message(message_id):
    db = get_db()
    run(db, "DELETE FROM messages WHERE id = ?", (message_id,))
    db.commit()
    return redirect(url_for("messages"))


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
        me = fetch_user(current_user_id())
        send_push_to_user(
            other_id(current_user_id()), f"{me['name']} 問了你一個小問題", text, f"/questions/{new_id}"
        )
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
            me = fetch_user(current_user_id())
            send_push_to_user(
                other_id(current_user_id()), f"{me['name']} 回覆了小問題", reply_text, f"/questions/{qid}"
            )
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
    food_items = run(db, "SELECT * FROM checklist_items WHERE category = 'food' ORDER BY id ASC").fetchall()
    return render_template(
        "checklist.html", bring_items=bring_items, place_items=place_items, food_items=food_items
    )


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
    if text and category in ("bring", "place", "food"):
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


@app.route("/memories")
def memories():
    db = get_db()
    # 越下面是越早的故事：依 memory_date 由新到舊排序（最新的在最上面）
    items = run(
        db, "SELECT * FROM memories ORDER BY memory_date DESC, id DESC"
    ).fetchall()
    return render_template(
        "memories.html", memories=items, storage_enabled=SUPABASE_STORAGE_ENABLED
    )


@app.route("/memories/add", methods=["POST"])
def add_memory():
    if not SUPABASE_STORAGE_ENABLED:
        flash("還沒有設定 Supabase Storage，沒辦法上傳照片，先去設定頁看說明")
        return redirect(url_for("memories"))

    file = request.files.get("image")
    memory_date = request.form.get("memory_date", "").strip()
    caption = request.form.get("caption", "").strip()

    if not file or not file.filename or not allowed_file(file.filename):
        flash("請選擇一張照片")
        return redirect(url_for("memories"))
    if not memory_date:
        flash("請選擇這張照片的日期")
        return redirect(url_for("memories"))

    filename = f"{int(datetime.now().timestamp())}_{secure_filename(file.filename)}"
    try:
        image_url = upload_to_supabase_storage(file, filename)
    except (requests.RequestException, RuntimeError) as ex:
        flash(f"上傳照片失敗：{ex}")
        return redirect(url_for("memories"))

    db = get_db()
    run(
        db,
        "INSERT INTO memories (sender_id, image_url, memory_date, caption, created_at) VALUES (?,?,?,?,?)",
        (current_user_id(), image_url, memory_date, caption or None, now_str()),
    )
    db.commit()
    flash("回憶已經加進時間軸了")
    return redirect(url_for("memories"))


@app.route("/memories/delete/<int:memory_id>", methods=["POST"])
def delete_memory(memory_id):
    db = get_db()
    run(db, "DELETE FROM memories WHERE id = ?", (memory_id,))
    db.commit()
    return redirect(url_for("memories"))


@app.route("/blog")
def blog():
    db = get_db()
    raw_posts = run(db, "SELECT * FROM blog_posts ORDER BY id DESC").fetchall()
    posts = []
    comments_by_post = {}
    for row in raw_posts:
        post = dict(row)
        # 相容舊資料：以前只有 youtube_* 欄位，現在統一用 link_* 欄位，
        # 沒有 link_url 的舊貼文就退回用 youtube_url 顯示。
        post["preview_url"] = post.get("link_url") or post.get("youtube_url")
        post["preview_title"] = post.get("link_title") or post.get("youtube_title")
        post["preview_thumbnail"] = post.get("link_thumbnail") or post.get("youtube_thumbnail")
        is_youtube = bool(post.get("link_is_youtube")) or bool(post.get("youtube_url"))
        post["preview_is_youtube"] = is_youtube
        post["preview_domain"] = post.get("link_domain") or ("youtube.com" if is_youtube else None)
        posts.append(post)
        comments_by_post[post["id"]] = run(
            db, "SELECT * FROM blog_comments WHERE post_id = ? ORDER BY id ASC", (post["id"],)
        ).fetchall()
    return render_template(
        "blog.html",
        posts=posts,
        comments_by_post=comments_by_post,
        storage_enabled=SUPABASE_STORAGE_ENABLED,
    )


@app.route("/blog/new", methods=["POST"])
def new_blog_post():
    content = request.form.get("content", "").strip()
    link_url = request.form.get("link_url", "").strip()
    file = request.files.get("image")

    image_url = None
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("圖片格式不支援")
            return redirect(url_for("blog"))
        if not SUPABASE_STORAGE_ENABLED:
            flash("還沒有設定 Supabase Storage，沒辦法上傳圖片")
            return redirect(url_for("blog"))
        filename = f"blog/{int(datetime.now().timestamp())}_{secure_filename(file.filename)}"
        try:
            image_url = upload_to_supabase_storage(file, filename)
        except (requests.RequestException, RuntimeError) as ex:
            flash(f"上傳圖片失敗：{ex}")
            return redirect(url_for("blog"))

    link_title, link_thumbnail, link_domain, is_youtube = None, None, None, False
    if link_url:
        video_id = extract_youtube_id(link_url)
        if video_id:
            is_youtube = True
            link_domain = "youtube.com"
            link_thumbnail = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
            link_title = fetch_youtube_title(link_url) or "YouTube 影片"
        else:
            # 不是 YouTube，就用通用的方式去抓網頁的標題跟縮圖（Threads、新聞網站...都適用）
            link_title, link_thumbnail, link_domain = fetch_link_preview(link_url)

    if not (content or image_url or link_url):
        flash("至少要留點文字、一張圖片，或一個連結")
        return redirect(url_for("blog"))

    db = get_db()
    cur = run(
        db,
        "INSERT INTO blog_posts "
        "(sender_id, content, image_url, link_url, link_title, link_thumbnail, link_domain, link_is_youtube, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?) RETURNING id",
        (
            current_user_id(), content or None, image_url,
            link_url or None, link_title, link_thumbnail, link_domain,
            1 if is_youtube else 0, now_str(),
        ),
    )
    new_id = cur.fetchone()["id"]
    db.commit()

    me = fetch_user(current_user_id())
    if content:
        preview = content
    elif link_url:
        preview = "分享了一個連結"
    else:
        preview = "分享了一張照片"
    send_push_to_user(other_id(current_user_id()), f"{me['name']} 發了新動態", preview, "/blog")

    return redirect(url_for("blog"))


@app.route("/blog/delete/<int:post_id>", methods=["POST"])
def delete_blog_post(post_id):
    db = get_db()
    run(db, "DELETE FROM blog_comments WHERE post_id = ?", (post_id,))
    run(db, "DELETE FROM blog_posts WHERE id = ?", (post_id,))
    db.commit()
    return redirect(url_for("blog"))


@app.route("/blog/comment/<int:post_id>", methods=["POST"])
def add_blog_comment(post_id):
    comment_text = request.form.get("comment_text", "").strip()
    if comment_text:
        db = get_db()
        run(
            db,
            "INSERT INTO blog_comments (post_id, sender_id, comment_text, created_at) VALUES (?,?,?,?)",
            (post_id, current_user_id(), comment_text, now_str()),
        )
        db.commit()
        me = fetch_user(current_user_id())
        send_push_to_user(other_id(current_user_id()), f"{me['name']} 留言了", comment_text, "/blog")
    return redirect(url_for("blog"))


@app.route("/push/subscribe", methods=["POST"])
def push_subscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")
    keys = data.get("keys") or {}
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not (endpoint and p256dh and auth):
        return jsonify({"ok": False, "error": "缺少必要欄位"}), 400

    db = get_db()
    existing = run(
        db, "SELECT id FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
        (current_user_id(), endpoint),
    ).fetchone()
    if not existing:
        run(
            db,
            "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at) VALUES (?,?,?,?,?)",
            (current_user_id(), endpoint, p256dh, auth, now_str()),
        )
        db.commit()
    return jsonify({"ok": True})


@app.route("/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")
    if endpoint:
        db = get_db()
        run(db, "DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        db.commit()
    return jsonify({"ok": True})


@app.route("/settings", methods=["GET", "POST"])
def settings():
    db = get_db()
    if request.method == "POST":
        meeting_date = request.form.get("meeting_date", "").strip()
        if meeting_date:
            old_meeting_date = get_setting("meeting_date")
            if meeting_date != old_meeting_date:
                # 見面日期改變了，進度條要從今天重新算起，不然百分比會亂跳
                set_setting("countdown_start_date", date.today().isoformat())
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
