from __future__ import annotations

import base64
import html
import importlib
import json
import os
import sqlite3
import sys
import threading
import uuid
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote_to_bytes
from zoneinfo import ZoneInfo

import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "storage.sqlite3"
MEMBERS_PATH = BASE_DIR / "members.json"
ASSETS_DIR = BASE_DIR / "assets"
JST = ZoneInfo("Asia/Tokyo")
DB_LOCK = threading.Lock()

STORAGE_KEYS = {
    "minutes": "centennial_minutes_posts",
    "message": "centennial_message_posts",
    "tasks": "centennial_member_tasks_shared",
    "planning": "centennial_member_planning_proposals",
    "voice": "centennial_member_voice_memos",
    "board": "centennial_public_board_posts",
}

NAV_PAGES = [
    ("home", "トップ"),
    ("message", "100周年News"),
    ("minutes", "お知らせ"),
    ("board", "掲示板"),
]

WORKSPACE_SECTION_LABELS = {
    "news": "100周年News",
    "minutes": "お知らせ",
    "board": "掲示板",
    "voice": "100周年プロジェクトへの声",
    "tasks": "タスク",
    "planning": "企画立案",
}

TASK_PRIORITY_OPTIONS = [
    "緊急であり重要",
    "緊急ではあるが重要ではない",
    "緊急ではないが重要",
    "緊急ではなく重要でもない",
]
TASK_PRIORITY_ORDER = {label: index for index, label in enumerate(TASK_PRIORITY_OPTIONS)}
TASK_PRIORITY_META = {
    "緊急であり重要": {"quadrant": "urgent_important"},
    "緊急ではあるが重要ではない": {"quadrant": "urgent_not_important"},
    "緊急ではないが重要": {"quadrant": "not_urgent_important"},
    "緊急ではなく重要でもない": {"quadrant": "not_urgent_not_important"},
}

SHARED_LOGIN_PASSWORD = "39_oomura"
SHARED_AUTHOR_NAME = "100周年プロジェクト"
AUTH_QUERY_VALUE = "member"
CEREMONY_DATE = date(2026, 10, 11)
DEPARTMENT_OPTIONS = [
    "株式会社オームラ営業部",
    "株式会社オームラアフター法要部",
    "株式会社オームラ営業事務部",
    "株式会社エンバーミングサービス",
    "一般社団法人ふくい身元保証サービスおりづる",
    "ききょう商事有限会社",
]
VOICE_STATUS_OPTIONS = ["未確認", "確認中", "対応予定", "対応済み"]

DEFAULT_MEMBERS = [
    {"id": "m1", "name": "牧野", "role": "プロジェクトリーダー", "dept": "100周年プロジェクト"},
    {"id": "m2", "name": "田中", "role": "メンバー", "dept": "100周年プロジェクト"},
]

SEED_DATA = {
    STORAGE_KEYS["message"]: [
        {
            "id": "seed_message_1",
            "text": "100周年に向けた準備状況や公開情報をこちらで共有します。",
            "createdAt": "2026-02-18T09:00:00",
        }
    ],
    STORAGE_KEYS["minutes"]: [
        {
            "id": "seed_minutes_1",
            "text": "共有事項や添付資料はお知らせから確認できます。",
            "createdAt": "2026-02-20T10:00:00",
        }
    ],
    STORAGE_KEYS["tasks"]: [
        {
            "id": "seed_task_1",
            "text": "式典進行案の確認",
            "assignee": "牧野",
            "priority": "緊急ではないが重要",
            "deadline": "2026-03-21",
            "author": SHARED_AUTHOR_NAME,
            "createdAt": "2026-03-10T09:00:00",
            "completed": False,
            "completedAt": "",
        }
    ],
    STORAGE_KEYS["planning"]: [
        {
            "id": "seed_plan_1",
            "title": "来場導線の演出見直し",
            "description": "受付から式典開始までの流れをよりわかりやすく整理する提案です。",
            "proposer": SHARED_AUTHOR_NAME,
            "createdAt": "2026-03-10T10:15:00",
            "status": "proposing",
            "decidedAt": "",
        }
    ],
    STORAGE_KEYS["voice"]: [],
    STORAGE_KEYS["board"]: [
        {
            "id": "seed_board_1",
            "name": "総務部",
            "text": "掲示板では社員同士で自由にコメントできます。",
            "createdAt": "2026-03-10T11:00:00",
        }
    ],
}


def get_secret_or_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        secret_value = st.secrets.get(name, default)
    except Exception:
        return default
    if isinstance(secret_value, str):
        return secret_value
    return default


def external_database_url() -> str:
    return get_secret_or_env("CENTENNIAL_DATABASE_URL") or get_secret_or_env("DATABASE_URL")


def using_external_db() -> bool:
    return bool(external_database_url())


def connect_external_db():
    psycopg = importlib.import_module("psycopg")
    return psycopg.connect(external_database_url())


def now_iso() -> str:
    return datetime.now(JST).replace(microsecond=0).isoformat()


def jst_now() -> datetime:
    return datetime.now(JST)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def format_dt(value: str | None, include_weekday: bool = False) -> str:
    dt = parse_iso(value)
    if not dt:
        return "日時未設定"
    if include_weekday:
        weekdays = "月火水木金土日"
        return dt.strftime("%Y年%m月%d日") + f"（{weekdays[dt.weekday()]}）" + dt.strftime(" %H:%M")
    return dt.strftime("%Y年%m月%d日 %H:%M")


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def migrate_local_sqlite_to_external() -> None:
    if not using_external_db() or not DB_PATH.exists():
        return
    with sqlite3.connect(DB_PATH) as local_conn:
        rows = local_conn.execute("SELECT key, value, updated_at FROM kv_storage").fetchall()
    if not rows:
        return
    with DB_LOCK, connect_external_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key FROM kv_storage")
            existing = {row[0] for row in cur.fetchall()}
            for key, value, updated_at in rows:
                if key in existing:
                    continue
                cur.execute(
                    """
                    INSERT INTO kv_storage(key, value, updated_at)
                    VALUES(%s, %s, %s)
                    ON CONFLICT(key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (key, value, updated_at),
                )
        conn.commit()


def init_db() -> None:
    if using_external_db():
        with DB_LOCK, connect_external_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS kv_storage (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            conn.commit()
        migrate_local_sqlite_to_external()
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_storage (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def get_raw_value(key: str) -> str | None:
    if using_external_db():
        with DB_LOCK, connect_external_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM kv_storage WHERE key = %s", (key,))
                row = cur.fetchone()
        return row[0] if row else None
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT value FROM kv_storage WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


@st.cache_data(ttl=10, show_spinner=False)
def load_json_cached(key: str, fallback_json: str):
    raw = get_raw_value(key)
    if raw is None:
        return json.loads(fallback_json)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(fallback_json)


def set_raw_value(key: str, value: str) -> None:
    if using_external_db():
        with DB_LOCK, connect_external_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kv_storage(key, value, updated_at)
                    VALUES(%s, %s, %s)
                    ON CONFLICT(key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (key, value, now_iso()),
                )
            conn.commit()
        return
    with DB_LOCK, sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO kv_storage(key, value, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now_iso()),
        )
        conn.commit()


def load_json(key: str, fallback: list | dict | None = None):
    default_value = [] if fallback is None else fallback
    return load_json_cached(key, json.dumps(default_value, ensure_ascii=False))


def save_json(key: str, value) -> None:
    set_raw_value(key, json.dumps(value, ensure_ascii=False))
    load_json_cached.clear()


def load_members() -> list[dict]:
    if MEMBERS_PATH.exists():
        try:
            return json.loads(MEMBERS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return DEFAULT_MEMBERS
    return DEFAULT_MEMBERS


def ensure_seed_data() -> None:
    for key, value in SEED_DATA.items():
        if get_raw_value(key) is None:
            save_json(key, value)


def sorted_entries(items: list[dict], field: str = "createdAt", reverse: bool = True) -> list[dict]:
    return sorted(items, key=lambda item: item.get(field, ""), reverse=reverse)


def decode_data_url(data_url: str | None) -> tuple[bytes | None, str | None]:
    if not data_url or "," not in data_url or not data_url.startswith("data:"):
        return None, None
    header, payload = data_url.split(",", 1)
    mime = header[5:].split(";")[0] or "application/octet-stream"
    try:
        if ";base64" in header:
            return base64.b64decode(payload), mime
        return unquote_to_bytes(payload), mime
    except Exception:
        return None, mime


def upload_to_data_url(uploaded_file) -> tuple[str | None, str | None]:
    if not uploaded_file:
        return None, None
    payload = base64.b64encode(uploaded_file.getvalue()).decode("ascii")
    mime = uploaded_file.type or "application/octet-stream"
    return uploaded_file.name, f"data:{mime};base64,{payload}"


def normalize_entries(items: list[dict], prefix: str) -> list[dict]:
    normalized = []
    changed = False
    for item in items:
        row = dict(item)
        if not row.get("id"):
            row["id"] = make_id(prefix)
            changed = True
        if not row.get("createdAt"):
            row["createdAt"] = now_iso()
            changed = True
        normalized.append(row)
    return normalized if changed else items


def load_normalized_list(key: str, prefix: str) -> list[dict]:
    rows = load_json(key, [])
    normalized = normalize_entries(rows, prefix)
    if normalized is not rows:
        save_json(key, normalized)
    return normalized


def load_board_rows() -> list[dict]:
    rows = load_normalized_list(STORAGE_KEYS["board"], "board")
    normalized = []
    changed = False
    for item in rows:
        row = dict(item)
        if "parentId" not in row:
            row["parentId"] = ""
            changed = True
        normalized.append(row)
    if changed:
        save_json(STORAGE_KEYS["board"], normalized)
    return normalized


def load_voice_rows() -> list[dict]:
    rows = load_normalized_list(STORAGE_KEYS["voice"], "voice")
    normalized = []
    changed = False
    for item in rows:
        row = dict(item)
        if not row.get("status"):
            row["status"] = VOICE_STATUS_OPTIONS[0]
            changed = True
        if "responseMemo" not in row:
            row["responseMemo"] = ""
            changed = True
        normalized.append(row)
    if changed:
        save_json(STORAGE_KEYS["voice"], normalized)
    return normalized


def board_parent_id(item: dict) -> str:
    return str(item.get("parentId", "") or "").strip()


def board_reply_map(rows: list[dict]) -> dict[str, list[dict]]:
    replies: dict[str, list[dict]] = {}
    for item in rows:
        parent_id = board_parent_id(item)
        if parent_id:
            replies.setdefault(parent_id, []).append(item)
    for parent_id in replies:
        replies[parent_id] = sorted_entries(replies[parent_id], reverse=False)
    return replies


def render_board_entry_card(item: dict, key_prefix: str, indent: bool = False) -> None:
    wrapper_style = "margin-left:1.1rem;padding-left:0.95rem;border-left:3px solid rgba(122,103,199,0.22);" if indent else ""
    st.markdown(
        f"""
        <div style="{wrapper_style}">
          <div class="entry-card">
            <div class="entry-head">
              <div class="entry-title">{escape_html(item.get("name", "匿名"))}</div>
              <div class="entry-meta">{escape_html(format_dt(item.get("createdAt")))}</div>
            </div>
            <div class="entry-body">{escape_html(item.get("text", ""))}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def launched_via_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


def init_session_state() -> None:
    st.session_state.setdefault("member_authenticated", False)
    st.session_state.setdefault("member_password_input", "")
    st.session_state.setdefault("voice_submit_success", False)
    auth_value = st.query_params.get("auth", "")
    if isinstance(auth_value, list):
        auth_value = auth_value[0] if auth_value else ""
    if auth_value == AUTH_QUERY_VALUE:
        st.session_state["member_authenticated"] = True


def get_allowed_pages(member_authenticated: bool) -> list[tuple[str, str]]:
    pages = list(NAV_PAGES)
    pages.extend(
        [
            ("voice", "100周年プロジェクトへの声"),
            ("members", "プロジェクトメンバー ログイン"),
            ("easteregg", "Easter Egg"),
        ]
    )
    if member_authenticated:
        pages.append(("workspace", "運営ワークスペース"))
    return pages


def get_current_page(member_authenticated: bool) -> str:
    allowed = {slug for slug, _ in get_allowed_pages(member_authenticated)}
    page = st.query_params.get("page", "home")
    if isinstance(page, list):
        page = page[0] if page else "home"
    return page if page in allowed else "home"


def query_param_value(name: str, default: str = "") -> str:
    value = st.query_params.get(name, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value


def build_page_href(page: str, **params: str) -> str:
    query = [f"page={page}"]
    if st.session_state.get("member_authenticated"):
        query.append(f"auth={AUTH_QUERY_VALUE}")
    for key, value in params.items():
        if value:
            query.append(f"{key}={value}")
    return "?" + "&".join(query)


def navigate_to(page: str, **params: str) -> None:
    st.query_params.clear()
    st.query_params["page"] = page
    if st.session_state.get("member_authenticated"):
        st.query_params["auth"] = AUTH_QUERY_VALUE
    for key, value in params.items():
        if value:
            st.query_params[key] = value
    st.rerun()


def make_workspace_href(section: str, item_key: str = "", item_id: str = "") -> str:
    params = {"section": section}
    if item_key and item_id:
        params[item_key] = item_id
    return build_page_href("workspace", **params)


@st.cache_data(show_spinner=False)
def image_to_data_uri(path: str) -> str:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def find_logo_path() -> Path | None:
    priority_patterns = (
        "100周年ロゴ.png",
        "*100周年*ロゴ*.png",
        "*100*周年*ロゴ*.png",
        "100周年ロゴ.webp",
        "*100周年*ロゴ*.webp",
        "*100*周年*ロゴ*.webp",
        "100周年ロゴ.jpg",
        "100周年ロゴ.jpeg",
        "*100周年*ロゴ*.jpg",
        "*100周年*ロゴ*.jpeg",
        "*100*周年*ロゴ*.jpg",
        "*100*周年*ロゴ*.jpeg",
    )
    for pattern in priority_patterns:
        matches = sorted(ASSETS_DIR.glob(pattern))
        if matches:
            return matches[0]
    return None


def escape_html(text: str) -> str:
    return html.escape(text, quote=True)


def ceremony_countdown_days() -> int:
    return max(0, (CEREMONY_DATE - jst_now().date()).days)


def split_assignees(raw_value: str) -> list[str]:
    cleaned = raw_value
    for token in ["、", "，", ",", "/", "\n", "・"]:
        cleaned = cleaned.replace(token, "|")
    return [part.strip() for part in cleaned.split("|") if part.strip()]


def task_priority_value(item: dict) -> str:
    value = item.get("priority")
    return value if value in TASK_PRIORITY_OPTIONS else "緊急ではないが重要"


def task_deadline_value(item: dict) -> str:
    value = item.get("deadline")
    return value if isinstance(value, str) and value else "未設定"


def task_sort_key(item: dict) -> tuple[int, str, str]:
    return (
        TASK_PRIORITY_ORDER.get(task_priority_value(item), 2),
        item.get("deadline") or "9999-12-31",
        item.get("createdAt") or "",
    )


def parse_deadline_for_input(value: str) -> date:
    if value:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            pass
    return jst_now().date()


def task_matches_assignees(item: dict, selected_assignees: list[str]) -> bool:
    if not selected_assignees or "全員" in selected_assignees:
        return True
    assignees = set(split_assignees(item.get("assignee", "")))
    return bool(assignees.intersection(selected_assignees))


def is_due_soon_task(item: dict) -> bool:
    deadline = item.get("deadline")
    if not deadline:
        return False
    try:
        remaining = (datetime.fromisoformat(deadline).date() - jst_now().date()).days
    except ValueError:
        return False
    return 0 <= remaining < 7 and not item.get("completed")


def due_soon_task_count(tasks: list[dict]) -> int:
    return sum(1 for item in tasks if is_due_soon_task(item))


def priority_guide_markdown() -> str:
    rows = [
        "緊急であり重要: すぐ着手したい最優先事項",
        "緊急ではあるが重要ではない: 締切は近いが影響範囲は限定的な事項",
        "緊急ではないが重要: 中長期で着実に進めたい事項",
        "緊急ではなく重要でもない: 状況を見ながら進める事項",
    ]
    return "\n".join(f"- {row}" for row in rows)


def inject_style() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg-1: #edf3ff;
            --bg-2: #f7f0e4;
            --ink: #2f2945;
            --muted: #655d79;
            --line: rgba(110, 95, 170, 0.18);
            --card: rgba(255, 255, 255, 0.78);
        }
        .stApp {
            background:
                radial-gradient(18px 18px at 12% 20%, rgba(137, 118, 205, 0.10) 0%, rgba(137, 118, 205, 0.10) 42%, transparent 46%),
                radial-gradient(18px 18px at 15% 17%, rgba(160, 133, 224, 0.08) 0%, rgba(160, 133, 224, 0.08) 42%, transparent 46%),
                radial-gradient(18px 18px at 18% 20%, rgba(128, 108, 194, 0.10) 0%, rgba(128, 108, 194, 0.10) 42%, transparent 46%),
                radial-gradient(circle at 8% 12%, rgba(122, 103, 199, 0.18), transparent 24%),
                radial-gradient(circle at 88% 10%, rgba(78, 123, 201, 0.18), transparent 26%),
                radial-gradient(circle at 50% 120%, rgba(207, 171, 98, 0.16), transparent 28%),
                linear-gradient(155deg, var(--bg-1), #e6def7 48%, var(--bg-2));
            color: var(--ink);
        }
        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stSidebar"],
        [data-testid="collapsedControl"],
        #MainMenu,
        footer {
            display: none;
        }
        .block-container {
            padding-top: 0.4rem;
            padding-bottom: 3rem;
        }
        .nav-shell {
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
            margin-bottom: 1rem;
        }
        .section-title {
            font-family: "Yu Mincho", "Hiragino Mincho ProN", "MS PMincho", serif;
            font-size: 1.55rem;
            color: #3d3368;
            margin-bottom: 0.6rem;
        }
        .section-copy {
            color: var(--muted);
            margin-bottom: 1rem;
        }
        .soft-card,
        .entry-card {
            background: linear-gradient(180deg, rgba(255,255,255,0.84), rgba(248,246,255,0.74));
            border: 1px solid var(--line);
            border-radius: 24px;
            padding: 1.15rem 1.2rem;
            margin-bottom: 1rem;
            box-shadow: 0 12px 30px rgba(87, 74, 143, 0.08);
        }
        .entry-head {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            flex-wrap: wrap;
            margin-bottom: 0.75rem;
        }
        .entry-title {
            font-weight: 700;
            color: #403469;
        }
        .entry-meta {
            font-size: 0.85rem;
            color: var(--muted);
        }
        .entry-body {
            white-space: pre-wrap;
            line-height: 1.8;
            color: #322a4c;
        }
        .chip {
            display: inline-block;
            padding: 0.25rem 0.65rem;
            border-radius: 999px;
            background: rgba(207, 171, 98, 0.12);
            border: 1px solid rgba(207, 171, 98, 0.35);
            color: #7a5920;
            font-size: 0.84rem;
            margin-right: 0.45rem;
            margin-bottom: 0.4rem;
        }
        div[data-testid="stMetric"] {
            background: rgba(255,255,255,0.72);
            border: 1px solid var(--line);
            padding: 0.8rem 0.9rem;
            border-radius: 20px;
            box-shadow: 0 10px 24px rgba(87, 74, 143, 0.08);
        }
        .floating-shortcut {
            position: fixed;
            bottom: 18px;
            z-index: 999;
        }
        .floating-shortcut.left {
            left: 18px;
        }
        .floating-shortcut.right {
            right: 18px;
        }
        .floating-shortcut a,
        .floating-shortcut button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 240px;
            min-height: 52px;
            padding: 0 18px;
            border-radius: 999px;
            border: 1px solid rgba(116, 101, 176, 0.22);
            background: linear-gradient(145deg, rgba(255,255,255,0.88), rgba(241,237,252,0.76));
            color: #403469;
            font-weight: 700;
            font-size: 0.92rem;
            text-decoration: none;
            box-shadow: 0 14px 28px rgba(83, 70, 143, 0.14);
            backdrop-filter: blur(10px);
            cursor: pointer;
        }
        .workspace-note {
            padding: 0.9rem 1rem;
            border-radius: 18px;
            background: rgba(255,255,255,0.72);
            border: 1px dashed rgba(122, 103, 199, 0.28);
            color: var(--muted);
            margin-bottom: 1rem;
        }
        .app-loading-overlay {
            position: fixed;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(237, 243, 255, 0.92);
            color: #3d3368;
            font-family: "Yu Mincho", "Hiragino Mincho ProN", "MS PMincho", serif;
            font-size: 1.55rem;
            letter-spacing: 0.08em;
            z-index: 2000;
            backdrop-filter: blur(6px);
        }
        @media (max-width: 820px) {
            .block-container {
                padding-top: 0.35rem;
                padding-bottom: 8.5rem;
            }
            .section-title {
                font-size: 1.25rem;
                margin-bottom: 0.45rem;
            }
            .section-copy {
                font-size: 0.92rem;
                line-height: 1.7;
            }
            .soft-card,
            .entry-card {
                border-radius: 18px;
                padding: 0.95rem 0.9rem;
                margin-bottom: 0.8rem;
            }
            .entry-head {
                gap: 0.35rem;
                margin-bottom: 0.55rem;
            }
            .entry-meta {
                width: 100%;
                font-size: 0.8rem;
            }
            .entry-body {
                font-size: 0.94rem;
                line-height: 1.7;
            }
            .floating-shortcut {
                right: 12px !important;
                left: 12px !important;
            }
            .floating-shortcut.left {
                bottom: 74px;
            }
            .floating-shortcut.right {
                bottom: 12px;
            }
            .floating-shortcut a,
            .floating-shortcut button {
                display: flex;
                width: 100%;
                min-width: 0;
                min-height: 48px;
                padding: 0 14px;
                font-size: 0.88rem;
                text-align: center;
            }
            .app-loading-overlay {
                font-size: 1.2rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def show_loading_overlay():
    placeholder = st.empty()
    placeholder.markdown('<div class="app-loading-overlay">読み込み中...</div>', unsafe_allow_html=True)
    return placeholder


def render_navigation_buttons(current_page: str) -> None:
    items = []
    for slug, label in NAV_PAGES:
        active = " is-active" if slug == current_page else ""
        items.append(
            f"""
            <button class="top-nav-button{active}" type="button" data-href="{build_page_href(slug)}">{escape_html(label)}</button>
            """
        )
    st.html(
        """
        <style>
        .top-nav {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.65rem;
            margin-bottom: 1rem;
        }
        .top-nav-form {
            margin: 0;
        }
        .top-nav-button {
            width: 100%;
            min-height: 46px;
            border-radius: 16px;
            border: 1px solid rgba(116, 101, 176, 0.18);
            background: rgba(255, 255, 255, 0.72);
            color: #403469;
            font-weight: 700;
            font-size: 0.9rem;
            box-shadow: 0 10px 22px rgba(83, 70, 143, 0.08);
            cursor: pointer;
        }
        .top-nav-button.is-active {
            background: linear-gradient(145deg, rgba(122, 103, 199, 0.96), rgba(89, 123, 202, 0.95));
            color: #fff;
        }
        @media (max-width: 820px) {
            .top-nav {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.5rem;
            }
            .top-nav-button {
                min-height: 42px;
                border-radius: 14px;
                font-size: 0.84rem;
            }
        }
        </style>
        <div class="top-nav">
        """
        + "".join(items)
        + """
        </div>
        <script>
        document.querySelectorAll(".top-nav-button[data-href]").forEach((button) => {
            if (button.dataset.bound === "true") return;
            button.dataset.bound = "true";
            button.addEventListener("click", () => {
                window.location.assign(button.dataset.href);
            });
        });
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def render_member_login_shortcut() -> None:
    logo_path = find_logo_path()
    logo_src = image_to_data_uri(str(logo_path)) if logo_path else ""
    logo_html = f'<img src="{logo_src}" alt="100周年ロゴ">' if logo_src else '<span>100</span>'
    st.html(
        f"""
        <style>
        .logo-unlock-shell {{
            position: fixed;
            left: max(12px, env(safe-area-inset-left));
            bottom: calc(max(12px, env(safe-area-inset-bottom)) + 0px);
            z-index: 999;
            width: clamp(54px, 7vw, 76px);
            height: clamp(54px, 7vw, 76px);
        }}
        .logo-unlock-button {{
            width: 100%;
            height: 100%;
            display: block;
            border: 0;
            border-radius: 0;
            background: transparent;
            box-shadow: none;
            backdrop-filter: none;
            padding: 0;
            margin: 0;
            outline: none;
            cursor: pointer;
            user-select: none;
            -webkit-user-select: none;
            touch-action: manipulation;
        }}
        .logo-unlock-button img {{
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
            mix-blend-mode: multiply;
            opacity: 0.96;
            filter: drop-shadow(0 10px 18px rgba(83, 70, 143, 0.08));
        }}
        .logo-unlock-button span {{
            display: flex;
            width: 100%;
            height: 100%;
            align-items: center;
            justify-content: center;
            color: #403469;
            font-weight: 800;
            font-size: 1.15rem;
        }}
        @media (max-width: 820px) {{
            .logo-unlock-shell {{
                left: max(12px, env(safe-area-inset-left));
                bottom: calc(max(12px, env(safe-area-inset-bottom)) + 86px);
                width: 58px;
                height: 58px;
            }}
        }}
        </style>
        <div class="logo-unlock-shell">
          <div class="logo-unlock-button" id="logo-unlock-button" role="button" tabindex="0" aria-label="メンバーログイン" data-target="{build_page_href('members')}">
            {logo_html}
          </div>
        </div>
        <script>
          const unlockButton = document.getElementById("logo-unlock-button");
          if (unlockButton && !unlockButton.dataset.bound) {{
            unlockButton.dataset.bound = "true";
            let clickCount = 0;
            let timerId = null;
            const handleUnlockClick = () => {{
              clickCount += 1;
              if (timerId) window.clearTimeout(timerId);
              if (clickCount >= 3) {{
                window.location.href = unlockButton.dataset.target;
                return;
              }}
              timerId = window.setTimeout(() => {{
                clickCount = 0;
              }}, 900);
            }};
            unlockButton.addEventListener("click", handleUnlockClick);
            unlockButton.addEventListener("keydown", (event) => {{
              if (event.key === "Enter" || event.key === " ") {{
                event.preventDefault();
                handleUnlockClick();
              }}
            }});
          }}
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def render_project_voice_shortcut() -> None:
    st.html(
        f"""
        <style>
        .voice-shortcut-button {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            min-height: 48px;
            border: 0;
            cursor: pointer;
        }}
        </style>
        <div class="floating-shortcut right">
          <button class="voice-shortcut-button" type="button" data-href="{build_page_href('voice')}">100周年プロジェクトへの声を投稿</button>
        </div>
        <script>
        document.querySelectorAll(".voice-shortcut-button[data-href]").forEach((button) => {{
            if (button.dataset.bound === "true") return;
            button.dataset.bound = "true";
            button.addEventListener("click", () => {{
                window.location.assign(button.dataset.href);
            }});
        }});
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def render_attachment_preview(data: bytes, mime: str, file_name: str, key_prefix: str, item_id: str) -> None:
    if mime.startswith("image/"):
        st.image(data, caption=file_name, width="stretch")
        return

    if mime == "application/pdf":
        try:
            st.pdf(data, height=720, key=f"pdf_{key_prefix}_{item_id}")
        except Exception:
            encoded = base64.b64encode(data).decode("ascii")
            st.markdown(
                f"""
                <object
                    data="data:application/pdf;base64,{encoded}"
                    type="application/pdf"
                    width="100%"
                    height="720"
                    style="border:0; border-radius:18px; background:rgba(255,255,255,0.82);">
                  <iframe
                      src="data:application/pdf;base64,{encoded}"
                      width="100%"
                      height="720"
                      style="border:0; border-radius:18px; background:rgba(255,255,255,0.82);">
                  </iframe>
                </object>
                """,
                unsafe_allow_html=True,
            )
        return

    if mime.startswith("text/") or mime in {"application/json", "application/xml"}:
        st.text(data.decode("utf-8", errors="replace"))
        return

    if mime.startswith("audio/"):
        st.audio(data, format=mime)
        return

    if mime.startswith("video/"):
        st.video(data, format=mime)
        return

    st.info(f"この形式のプレビューには未対応です: {file_name} ({mime})")


def show_attachment(item: dict, key_prefix: str) -> None:
    data, mime = decode_data_url(item.get("fileDataUrl"))
    file_name = item.get("fileName")
    if data and file_name:
        with st.expander(f"表示: {file_name}"):
            render_attachment_preview(data, mime or "application/octet-stream", file_name, key_prefix, item.get("id", file_name))


def render_entry(item: dict, title: str, meta: str, key_prefix: str) -> None:
    st.markdown(
        f"""
        <div class="entry-card">
          <div class="entry-head">
            <div class="entry-title">{escape_html(title)}</div>
            <div class="entry-meta">{escape_html(meta)}</div>
          </div>
          <div class="entry-body">{escape_html(item.get("text", ""))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    show_attachment(item, key_prefix)


def render_board_posts(posts: list[dict]) -> None:
    if not posts:
        st.info("投稿はまだありません。")
        return
    replies = board_reply_map(posts)
    top_level = [item for item in sorted_entries(posts) if not board_parent_id(item)]
    for item in top_level:
        render_board_entry_card(item, "board_root")
        for reply in replies.get(item.get("id", ""), []):
            render_board_entry_card(reply, "board_reply", indent=True)


def add_post_entry(key: str, text: str, uploaded_file) -> None:
    rows = load_normalized_list(key, "post")
    file_name, file_data_url = upload_to_data_url(uploaded_file)
    rows.append(
        {
            "id": make_id("post"),
            "text": text.strip(),
            "fileName": file_name,
            "fileDataUrl": file_data_url,
            "createdAt": now_iso(),
        }
    )
    save_json(key, rows)


def render_home_hero() -> None:
    logo_path = find_logo_path()
    logo_src = image_to_data_uri(str(logo_path)) if logo_path else ""
    countdown_days = ceremony_countdown_days()
    auth_input = f'<input type="hidden" name="auth" value="{AUTH_QUERY_VALUE}">' if st.session_state.get("member_authenticated") else ""
    hero_html = f"""
    <style>
      .hero-wrap {{
        position: relative;
        min-height: 100vh;
        padding: 0;
      }}
      .hero-stage {{
        position: relative;
        min-height: 100vh;
        display: grid;
        justify-items: center;
        align-items: start;
        padding-top: clamp(20px, 4vh, 42px);
        overflow: hidden;
      }}
      .hero {{
        width: min(880px, 94%);
        text-align: center;
        margin-top: clamp(0px, 1vh, 10px);
        transform: translateY(12px) scale(0.96);
        opacity: 0;
        filter: blur(10px);
        transition: transform 1.1s ease, opacity 1.1s ease, filter 1.1s ease;
      }}
      .hero.ready {{
        transform: translateY(0) scale(1);
        opacity: 1;
        filter: blur(0);
      }}
      .hero-easter-ready .logo-img {{
        filter: drop-shadow(0 18px 30px rgba(95, 83, 166, 0.08)) brightness(1.02);
      }}
      .logo-shell {{
        position: relative;
        width: min(760px, 92%);
        margin: 0 auto;
        isolation: isolate;
      }}
      .logo-shell::before {{
        content: "";
        position: absolute;
        inset: 5% 6% 7%;
        border-radius: 50%;
        background: radial-gradient(circle at center, rgba(255,255,255,0.62) 0%, rgba(255,255,255,0.26) 34%, rgba(238,233,255,0.12) 56%, rgba(238,233,255,0) 78%);
        filter: blur(32px);
        z-index: 0;
      }}
      .logo-img {{
        position: relative;
        z-index: 1;
        width: 100%;
        max-height: 62vh;
        object-fit: contain;
        opacity: 0.96;
        mix-blend-mode: multiply;
        filter: drop-shadow(0 18px 30px rgba(95, 83, 166, 0.08));
      }}
      .hero-title {{
        margin: 18px 0 0;
        font-family: "Yu Mincho", "Hiragino Mincho ProN", "MS PMincho", serif;
        font-size: clamp(2rem, 5vw, 4rem);
        letter-spacing: 0.08em;
        color: #352c5d;
      }}
      .scroll-note {{
        margin-top: 16px;
        color: #5c5581;
        font-size: 0.88rem;
        letter-spacing: 0.08em;
      }}
      .menu-shell {{
        position: absolute;
        inset: 0;
        display: grid;
        justify-items: center;
        align-items: start;
        padding: clamp(78px, 12vh, 118px) 18px 0;
        pointer-events: none;
      }}
      .menu-panel {{
        width: min(980px, 96%);
        opacity: 0;
        transform: translateY(32px) scale(0.96);
        filter: blur(16px);
        transition: opacity 0.7s ease, transform 0.7s ease, filter 0.7s ease;
        pointer-events: none;
      }}
      .countdown-card {{
        width: fit-content;
        margin: 0 auto 16px;
        padding: 0.9rem 1.15rem;
        border-radius: 24px;
        border: 1px solid rgba(116, 101, 176, 0.18);
        background: linear-gradient(145deg, rgba(255,255,255,0.78), rgba(246,243,255,0.54));
        box-shadow: 0 18px 34px rgba(83, 70, 143, 0.10);
        text-align: center;
      }}
      .countdown-label {{
        font-size: 0.78rem;
        letter-spacing: 0.18em;
        color: #6a6092;
      }}
      .countdown-days {{
        margin-top: 0.15rem;
        font-family: "Yu Mincho", "Hiragino Mincho ProN", "MS PMincho", serif;
        font-size: clamp(1.5rem, 3vw, 2.15rem);
        color: #3f3468;
      }}
      .countdown-date {{
        margin-top: 0.2rem;
        color: #6a6092;
        font-size: 0.88rem;
      }}
      .member-login-fab {{
        position: absolute;
        left: 18px;
        bottom: 18px;
        z-index: 4;
        margin: 0;
        opacity: 0;
        transform: translateY(18px);
        transition: opacity 0.5s ease, transform 0.5s ease;
        pointer-events: none;
      }}
      .member-login-logo {{
        width: 76px;
        height: 76px;
        border-radius: 22px;
        border: 0;
        background: transparent;
        box-shadow: none;
        padding: 0;
        cursor: pointer;
      }}
      .member-login-logo img {{
        width: 100%;
        height: 100%;
        object-fit: contain;
        display: block;
        mix-blend-mode: multiply;
        opacity: 0.96;
        filter: drop-shadow(0 10px 18px rgba(83, 70, 143, 0.08));
      }}
      .member-login-logo span {{
        display: flex;
        width: 100%;
        height: 100%;
        align-items: center;
        justify-content: center;
        color: #403469;
        font-weight: 800;
        font-size: 1.15rem;
      }}
      .menu-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 14px;
        align-items: stretch;
      }}
      .menu-card-form {{
        margin: 0;
        display: block;
        height: 100%;
      }}
      .menu-card {{
        display: block;
        width: 100%;
        min-height: 132px;
        height: 100%;
        text-align: left;
        color: #362d5d;
        border-radius: 24px;
        padding: 20px 18px;
        background: linear-gradient(145deg, rgba(255,255,255,0.64), rgba(246,243,255,0.42));
        border: 1px solid rgba(116, 101, 176, 0.18);
        box-shadow: 0 20px 36px rgba(83, 70, 143, 0.12);
        cursor: pointer;
      }}
      .menu-card strong {{
        display: block;
        margin-bottom: 8px;
        font-size: 1.02rem;
        color: #47397d;
      }}
      .menu-card span {{
        color: #5b537c;
        line-height: 1.7;
        font-size: 0.92rem;
      }}
      @media (max-width: 640px) {{
        .hero-stage {{
          min-height: 100dvh;
          padding-top: 16px;
          padding-bottom: 144px;
        }}
        .hero {{
          width: 94%;
        }}
        .logo-shell {{
          width: min(92vw, 520px);
        }}
        .logo-img {{
          max-height: 42vh;
        }}
        .hero-title {{
          margin-top: 12px;
          font-size: clamp(1.6rem, 8vw, 2.4rem);
        }}
        .scroll-note {{
          margin-top: 12px;
          font-size: 0.76rem;
        }}
        .menu-shell {{
          padding: 54px 12px 132px;
        }}
        .menu-panel {{
          width: 100%;
        }}
        .countdown-card {{
          width: 100%;
          padding: 0.8rem 0.9rem;
          border-radius: 18px;
          margin-bottom: 12px;
        }}
        .countdown-label {{
          font-size: 0.72rem;
        }}
        .countdown-days {{
          font-size: clamp(1.2rem, 6vw, 1.6rem);
        }}
        .countdown-date {{
          font-size: 0.8rem;
        }}
        .menu-card {{
          min-height: 104px;
          border-radius: 18px;
          padding: 16px 14px;
        }}
        .menu-card strong {{
          margin-bottom: 6px;
          font-size: 0.96rem;
        }}
        .menu-card span {{
          font-size: 0.86rem;
          line-height: 1.55;
        }}
        .menu-grid {{
          grid-template-columns: 1fr;
          gap: 10px;
        }}
        .member-login-fab {{
          left: 12px;
          bottom: 12px;
        }}
        .member-login-logo {{
          width: 64px;
          height: 64px;
          border-radius: 0;
          padding: 0;
        }}
      }}
    </style>
    <section class="hero-wrap">
      <div class="hero-stage">
        <div class="hero" id="hero">
          {f'<div class="logo-shell"><img class="logo-img" src="{logo_src}" alt="100周年ロゴ"></div>' if logo_src else '<div class="logo-shell"></div>'}
          <h1 class="hero-title">100周年特設ページ</h1>
          <div class="scroll-note">SCROLL OR SWIPE</div>
        </div>
        <div class="menu-shell">
          <div class="menu-panel" id="menu">
            <div class="countdown-card">
              <div class="countdown-label">CEREMONY COUNTDOWN</div>
              <div class="countdown-days">式典まであと {countdown_days}日</div>
              <div class="countdown-date">2026年10月11日</div>
            </div>
            <div class="menu-grid">
              <button class="menu-card" type="button" data-href="{build_page_href('message')}">
                <strong>100周年News</strong>
                <span>100周年に関する最新トピックをまとめて確認します。</span>
              </button>
              <button class="menu-card" type="button" data-href="{build_page_href('minutes')}">
                <strong>お知らせ</strong>
                <span>共有事項や添付資料を時系列で確認できます。</span>
              </button>
              <button class="menu-card" type="button" data-href="{build_page_href('board')}">
                <strong>掲示板</strong>
                <span>社員同士で自由にコメントし合える公開掲示板です。</span>
              </button>
            </div>
          </div>
        </div>
        <div class="member-login-fab">
          <div class="member-login-logo" id="member-login-logo" role="button" tabindex="0" aria-label="メンバーログイン" data-target="{build_page_href('members')}">
            {f'<img src="{logo_src}" alt="100周年ロゴ">' if logo_src else '<span>100</span>'}
          </div>
        </div>
      </div>
    </section>
    <script>
      const hero = document.getElementById("hero");
      const menu = document.getElementById("menu");
      const memberLoginFab = document.querySelector(".member-login-fab");
      const memberLoginLogo = document.getElementById("member-login-logo");
      const heroLogo = hero ? hero.querySelector(".logo-img") : null;
      let view = 0;
      let wheelLock = false;
      let touchStartY = null;
      let loginClickCount = 0;
      let loginClickTimer = null;
      let easterHoverReady = false;
      let easterClickCount = 0;
      let easterHoverTimer = null;
      let easterClickTimer = null;
      requestAnimationFrame(() => hero.classList.add("ready"));

      function sync() {{
        const eased = view === 1 ? 1 : 0;
        hero.style.opacity = String(Math.max(0, 1 - eased * 1.18));
        hero.style.transform = `translateY(${{-18 * eased}}px) scale(${{1 - eased * 0.08}})`;
        hero.style.filter = `blur(${{eased * 12}}px)`;
        menu.style.opacity = String(eased);
        menu.style.transform = `translateY(${{54 - eased * 54}}px) scale(${{0.96 + eased * 0.04}})`;
        menu.style.filter = `blur(${{16 - eased * 16}}px)`;
        menu.style.pointerEvents = view === 1 ? "auto" : "none";
        if (memberLoginFab) {{
          memberLoginFab.style.opacity = String(eased);
          memberLoginFab.style.transform = `translateY(${{18 - eased * 18}}px)`;
          memberLoginFab.style.pointerEvents = view === 1 ? "auto" : "none";
        }}
      }}

      function switchView(nextView) {{
        view = nextView;
        sync();
      }}

      function handleWheel(event) {{
        event.preventDefault();
        if (wheelLock || Math.abs(event.deltaY) < 12) return;
        wheelLock = true;
        window.setTimeout(() => {{ wheelLock = false; }}, 520);
        if (event.deltaY > 0 && view === 0) switchView(1);
        if (event.deltaY < 0 && view === 1) switchView(0);
      }}

      function handleKey(event) {{
        if ((event.key === "ArrowDown" || event.key === "PageDown" || event.key === " ")) {{
          event.preventDefault();
          switchView(1);
        }}
        if (event.key === "ArrowUp" || event.key === "PageUp") {{
          event.preventDefault();
          switchView(0);
        }}
      }}

      function handleTouchStart(event) {{
        touchStartY = event.touches[0].clientY;
      }}

      function handleTouchEnd(event) {{
        if (touchStartY === null) return;
        const delta = touchStartY - event.changedTouches[0].clientY;
        if (Math.abs(delta) > 24) switchView(delta > 0 ? 1 : 0);
        touchStartY = null;
      }}

      function resetEasterEgg() {{
        easterHoverReady = false;
        easterClickCount = 0;
        if (easterHoverTimer) window.clearTimeout(easterHoverTimer);
        if (easterClickTimer) window.clearTimeout(easterClickTimer);
        easterHoverTimer = null;
        easterClickTimer = null;
        hero.classList.remove("hero-easter-ready");
      }}

      document.querySelectorAll(".menu-card[data-href]").forEach((button) => {{
        if (button.dataset.bound === "true") return;
        button.dataset.bound = "true";
        button.addEventListener("click", () => {{
          window.location.assign(button.dataset.href);
        }});
      }});

      if (memberLoginLogo) {{
        memberLoginLogo.addEventListener("click", () => {{
          loginClickCount += 1;
          if (loginClickTimer) window.clearTimeout(loginClickTimer);
          if (loginClickCount >= 3) {{
            window.location.assign(memberLoginLogo.dataset.target);
            return;
          }}
          loginClickTimer = window.setTimeout(() => {{
            loginClickCount = 0;
          }}, 900);
        }});
      }}

      if (heroLogo) {{
        heroLogo.addEventListener("mouseenter", () => {{
          if (easterHoverReady) return;
          if (easterHoverTimer) window.clearTimeout(easterHoverTimer);
          easterHoverTimer = window.setTimeout(() => {{
            easterHoverReady = true;
            hero.classList.add("hero-easter-ready");
          }}, 3000);
        }});
        heroLogo.addEventListener("mouseleave", () => {{
          resetEasterEgg();
        }});
        heroLogo.addEventListener("click", () => {{
          if (!easterHoverReady) return;
          easterClickCount += 1;
          if (easterClickTimer) window.clearTimeout(easterClickTimer);
          if (easterClickCount >= 3) {{
            window.location.assign("{build_page_href('easteregg')}");
            return;
          }}
          easterClickTimer = window.setTimeout(() => {{
            easterClickCount = 0;
          }}, 1200);
        }});
      }}

      sync();
      window.addEventListener("wheel", handleWheel, {{ passive: false }});
      window.addEventListener("keydown", handleKey, {{ passive: false }});
      window.addEventListener("touchstart", handleTouchStart, {{ passive: true }});
      window.addEventListener("touchend", handleTouchEnd, {{ passive: true }});
    </script>
    """
    st.html(hero_html, unsafe_allow_javascript=True)


def render_home(messages: list[dict], minutes: list[dict], members: list[dict]) -> None:
    render_project_voice_shortcut()
    render_home_hero()


def render_message_page(messages: list[dict]) -> None:
    render_member_login_shortcut()
    render_project_voice_shortcut()
    st.markdown('<div class="section-title">100周年News</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-copy">100周年に関する最新トピックを時系列で確認できます。</div>', unsafe_allow_html=True)
    rows = sorted_entries(messages)
    for index, item in enumerate(rows, start=1):
        render_entry(item, f"News {len(rows) - index + 1}", format_dt(item.get("createdAt")), f"message_{index}")
    if not rows:
        st.info("100周年News はまだありません。")


def render_minutes_page(minutes: list[dict]) -> None:
    render_member_login_shortcut()
    render_project_voice_shortcut()
    st.markdown('<div class="section-title">お知らせ</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-copy">共有事項や添付資料をまとめて確認できます。</div>', unsafe_allow_html=True)
    rows = sorted_entries(minutes)
    for index, item in enumerate(rows, start=1):
        render_entry(item, f"お知らせ {len(rows) - index + 1}", format_dt(item.get("createdAt")), f"minutes_{index}")
    if not rows:
        st.info("お知らせはまだありません。")


def render_public_board_page() -> None:
    render_member_login_shortcut()
    render_project_voice_shortcut()
    st.markdown('<div class="section-title">掲示板</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-copy">社員同士で自由にコメントできる公開掲示板です。</div>', unsafe_allow_html=True)
    rows = load_board_rows()
    reply_target_id = st.session_state.get("board_reply_target_id", "")
    reply_target = next((item for item in rows if item.get("id") == reply_target_id and not board_parent_id(item)), None)
    if reply_target:
        reply_cols = st.columns([5, 1])
        reply_cols[0].info(f"返信先: {reply_target.get('name', '')} / {reply_target.get('text', '')}")
        if reply_cols[1].button("解除", key="clear_board_reply_target", width="stretch"):
            st.session_state["board_reply_target_id"] = ""
            st.rerun()
    with st.form("public_board_form", clear_on_submit=True):
        name = st.selectbox("部署", DEPARTMENT_OPTIONS)
        text = st.text_area("コメント", height=160)
        submitted = st.form_submit_button("返信する" if reply_target else "投稿する")
    if submitted:
        if not text.strip():
            st.error("部署とコメントを入力してください。")
        else:
            rows.append(
                {
                    "id": make_id("board"),
                    "name": name.strip(),
                    "text": text.strip(),
                    "parentId": reply_target.get("id", "") if reply_target else "",
                    "createdAt": now_iso(),
                }
            )
            save_json(STORAGE_KEYS["board"], rows)
            st.session_state["board_reply_target_id"] = ""
            st.rerun()
    replies = board_reply_map(rows)
    top_level = [item for item in sorted_entries(rows) if not board_parent_id(item)]
    if not top_level:
        st.info("投稿はまだありません。")
        return
    for item in top_level:
        render_board_entry_card(item, "board_public")
        action_cols = st.columns([1, 5])
        if action_cols[0].button("返信", key=f"reply_board_{item.get('id')}", width="stretch"):
            st.session_state["board_reply_target_id"] = item.get("id", "")
            st.rerun()
        for reply in replies.get(item.get("id", ""), []):
            render_board_entry_card(reply, "board_public_reply", indent=True)


def render_project_voice_page() -> None:
    render_member_login_shortcut()
    st.markdown('<div class="section-title">100周年プロジェクトへの声</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-copy">100周年プロジェクトへの意見や提案を送るフォームです。</div>', unsafe_allow_html=True)
    if st.session_state.get("voice_submit_success"):
        st.success("送信が完了しました。")
        st.session_state["voice_submit_success"] = False
    voices = load_voice_rows()
    with st.form("project_voice_form", clear_on_submit=True):
        author = st.selectbox("部署", DEPARTMENT_OPTIONS)
        text = st.text_area("メッセージ", height=180)
        submitted = st.form_submit_button("送信する")
    if submitted:
        if not text.strip():
            st.error("部署とメッセージを入力してください。")
        else:
            voices.append(
                {
                    "id": make_id("voice"),
                    "author": author.strip(),
                    "text": text.strip(),
                    "status": VOICE_STATUS_OPTIONS[0],
                    "responseMemo": "",
                    "createdAt": now_iso(),
                }
            )
            save_json(STORAGE_KEYS["voice"], voices)
            st.session_state["voice_submit_success"] = True
            st.rerun()


def render_task_map(tasks: list[dict]) -> None:
    if not tasks:
        st.info("表示対象のタスクはありません。")
        return

    quadrant_titles = {
        "not_urgent_important": "緊急ではないが重要",
        "urgent_important": "緊急であり重要",
        "not_urgent_not_important": "緊急ではなく重要でもない",
        "urgent_not_important": "緊急ではあるが重要ではない",
    }
    buckets = {key: [] for key in quadrant_titles}
    for item in tasks:
        buckets[TASK_PRIORITY_META[task_priority_value(item)]["quadrant"]].append(item)

    html_parts = [
        """
        <style>
        .task-map-shell { margin-top: 0.5rem; overflow: visible; }
        .task-map-axis { display: grid; grid-template-columns: 68px 1fr; gap: 0.8rem; align-items: stretch; overflow: visible; }
        .task-map-y-label { writing-mode: vertical-rl; display: flex; align-items: center; justify-content: center; color: var(--muted); font-weight: 600; letter-spacing: 0.06em; }
        .task-map-body { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; gap: 0.8rem; min-height: 28rem; overflow: visible; }
        .task-map-cell { position: relative; border: 1px solid rgba(122, 103, 199, 0.18); border-radius: 20px; background: rgba(255, 255, 255, 0.72); padding: 1rem; box-shadow: 0 14px 34px rgba(70, 60, 110, 0.08); overflow: visible; }
        .task-map-cell h4 { margin: 0 0 0.75rem; color: var(--ink); font-size: 0.98rem; }
        .task-map-items { display: flex; flex-wrap: wrap; gap: 0.7rem; }
        .task-map-item { position: relative; display: inline-flex; align-items: center; justify-content: center; min-width: 9.2rem; max-width: 100%; padding: 0.78rem 0.9rem; border-radius: 16px; border: 0; background: linear-gradient(135deg, rgba(122, 103, 199, 0.96), rgba(89, 123, 202, 0.95)); color: #fff; text-decoration: none; font-weight: 700; line-height: 1.35; box-shadow: 0 12px 26px rgba(71, 63, 132, 0.18); overflow: visible; z-index: 1; cursor: pointer; appearance: none; -webkit-appearance: none; }
        .task-map-item-due-soon { background: linear-gradient(135deg, rgba(205, 69, 69, 0.98), rgba(235, 130, 78, 0.96)); box-shadow: 0 16px 34px rgba(198, 92, 61, 0.26); outline: 2px solid rgba(255, 224, 173, 0.92); }
        .task-map-item:hover { transform: translateY(-2px); z-index: 30; }
        .task-map-item-label { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
        .task-map-item-badge { position: absolute; top: -0.45rem; right: -0.35rem; padding: 0.18rem 0.42rem; border-radius: 999px; background: rgba(255, 247, 231, 0.96); color: #a64524; font-size: 0.68rem; font-weight: 800; letter-spacing: 0.04em; }
        .task-map-tooltip { position: absolute; left: 50%; bottom: calc(100% + 12px); transform: translateX(-50%); width: min(320px, 72vw); padding: 0.9rem 1rem; border-radius: 16px; background: rgba(36, 31, 58, 0.96); color: #fff; font-size: 0.92rem; line-height: 1.6; box-shadow: 0 18px 40px rgba(24, 22, 40, 0.28); opacity: 0; pointer-events: none; transition: opacity 0.18s ease; z-index: 40; }
        .task-map-item:hover .task-map-tooltip { opacity: 1; }
        .task-map-empty { color: var(--muted); font-size: 0.92rem; }
        .task-map-x-label { text-align: center; color: var(--muted); font-weight: 600; margin-top: 0.8rem; letter-spacing: 0.06em; }
        .task-map-x-ends { display: flex; justify-content: space-between; color: var(--muted); font-size: 0.85rem; margin-top: 0.25rem; padding: 0 0.3rem; }
        @media (max-width: 820px) {
            .task-map-shell {
                overflow-x: auto;
                padding-bottom: 0.2rem;
            }
            .task-map-axis {
                grid-template-columns: 52px minmax(560px, 1fr);
                gap: 0.55rem;
                min-width: 612px;
            }
            .task-map-y-label {
                font-size: 0.82rem;
                letter-spacing: 0.04em;
            }
            .task-map-body {
                min-height: 22rem;
                gap: 0.6rem;
            }
            .task-map-cell {
                border-radius: 16px;
                padding: 0.78rem;
            }
            .task-map-cell h4 {
                font-size: 0.84rem;
                margin-bottom: 0.55rem;
            }
            .task-map-items {
                gap: 0.5rem;
            }
            .task-map-item {
                min-width: 7.4rem;
                padding: 0.68rem 0.72rem;
                font-size: 0.84rem;
            }
            .task-map-tooltip {
                width: min(260px, 62vw);
                font-size: 0.82rem;
                line-height: 1.45;
            }
            .task-map-x-label {
                margin-top: 0.55rem;
                font-size: 0.82rem;
            }
            .task-map-x-ends {
                font-size: 0.76rem;
            }
        }
        </style>
        <div class="task-map-shell">
          <div class="task-map-axis">
            <div class="task-map-y-label">重要度</div>
            <div>
              <div class="task-map-body">
        """
    ]

    for quadrant in ["not_urgent_important", "urgent_important", "not_urgent_not_important", "urgent_not_important"]:
        html_parts.append(f'<div class="task-map-cell"><h4>{escape_html(quadrant_titles[quadrant])}</h4><div class="task-map-items">')
        if buckets[quadrant]:
            for item in sorted(buckets[quadrant], key=task_sort_key):
                due_soon = is_due_soon_task(item)
                badge_html = '<span class="task-map-item-badge">締切間近</span>' if due_soon else ""
                item_class = "task-map-item task-map-item-due-soon" if due_soon else "task-map-item"
                tooltip = (
                    f"<strong>{escape_html(item.get('text', ''))}</strong><br>"
                    f"担当者: {escape_html(item.get('assignee', '未設定'))}<br>"
                    f"優先度: {escape_html(task_priority_value(item))}<br>"
                    f"締切: {escape_html(task_deadline_value(item))}<br>"
                    f"登録日: {escape_html(format_dt(item.get('createdAt')))}"
                )
                html_parts.append(
                    f"""
                    <button class="{item_class}" type="button" data-href="{make_workspace_href('tasks', 'task_id', item.get('id', ''))}">
                      {badge_html}
                      <span class="task-map-item-label">{escape_html(item.get("text", ""))}</span>
                      <span class="task-map-tooltip">{tooltip}</span>
                    </button>
                    """
                )
        else:
            html_parts.append('<div class="task-map-empty">タスクはありません。</div>')
        html_parts.append("</div></div>")

    html_parts.append(
        """
              </div>
              <div class="task-map-x-label">緊急度</div>
              <div class="task-map-x-ends"><span>低</span><span>高</span></div>
            </div>
          </div>
        </div>
        <script>
        document.querySelectorAll(".task-map-item[data-href]").forEach((button) => {
            if (button.dataset.bound === "true") return;
            button.dataset.bound = "true";
            button.addEventListener("click", () => {
                window.location.assign(button.dataset.href);
            });
        });
        </script>
        """
    )
    st.html("".join(html_parts))


def render_plan_links(plans: list[dict]) -> None:
    if not plans:
        st.info("提案中の企画はありません。")
        return
    cards = ['<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0.9rem;">']
    for item in plans:
        cards.append(
            f"""
            <button type="button"
               class="plan-link-card"
               data-href="{make_workspace_href('planning', 'plan_id', item.get('id', ''))}"
               style="display:block;width:100%;text-align:left;padding:1rem 1.05rem;border-radius:18px;border:1px solid rgba(122,103,199,0.16);background:rgba(255,255,255,0.78);box-shadow:0 12px 28px rgba(70,60,110,0.08);color:var(--ink);cursor:pointer;">
              <div style="font-weight:700;margin-bottom:0.4rem;">{escape_html(item.get("title", ""))}</div>
              <div style="font-size:0.88rem;color:var(--muted);margin-bottom:0.55rem;">提案者: {escape_html(item.get("proposer", ""))}</div>
              <div style="font-size:0.92rem;line-height:1.55;color:var(--ink);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;">
                {escape_html(item.get("description", ""))}
              </div>
            </button>
            """
        )
    cards.append("</div>")
    cards.append(
        """
        <script>
        document.querySelectorAll(".plan-link-card[data-href]").forEach((button) => {
            if (button.dataset.bound === "true") return;
            button.dataset.bound = "true";
            button.addEventListener("click", () => {
                window.location.assign(button.dataset.href);
            });
        });
        </script>
        """
    )
    st.html("".join(cards), unsafe_allow_javascript=True)


def render_members_page() -> None:
    if not st.session_state["member_authenticated"]:
        st.markdown('<div class="section-title">プロジェクトメンバー ログイン</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-copy">共通パスワードを入力してください。</div>', unsafe_allow_html=True)
        with st.form("member_login_form"):
            st.text_input("共通パスワード", type="password", key="member_password_input")
            submitted = st.form_submit_button("ログイン")
        if submitted:
            if st.session_state.get("member_password_input") == SHARED_LOGIN_PASSWORD:
                st.session_state["member_authenticated"] = True
                navigate_to("members")
            else:
                st.error("パスワードが一致しません。")
        return

    tasks = load_normalized_list(STORAGE_KEYS["tasks"], "task")
    planning = load_normalized_list(STORAGE_KEYS["planning"], "plan")
    current_tasks = sorted([item for item in tasks if not item.get("completed")], key=task_sort_key)
    completed_tasks = sorted([item for item in tasks if item.get("completed")], key=lambda item: item.get("completedAt", ""), reverse=True)
    proposing = [item for item in sorted_entries(planning) if item.get("status") != "approved"]
    decided_plans = [item for item in sorted_entries(planning) if item.get("status") == "approved"]

    st.markdown('<div class="section-title">プロジェクトダッシュボード</div>', unsafe_allow_html=True)
    action_cols = st.columns([1, 1, 4])
    if action_cols[0].button("運営メニューへ", key="go_workspace_from_dashboard", width="stretch"):
        navigate_to("workspace", section="news")
    if action_cols[1].button("ログアウト", key="logout_from_dashboard", width="stretch"):
        st.session_state["member_authenticated"] = False
        st.session_state["member_password_input"] = ""
        navigate_to("home")

    summary_cols = st.columns(3)
    summary_cols[0].metric("進行中タスク", str(len(current_tasks)))
    summary_cols[1].metric("締切まで時間がないタスク", str(due_soon_task_count(current_tasks)))
    summary_cols[2].metric("提案中の企画", str(len(proposing)))

    st.markdown("#### タスクマップ")
    assignee_options = sorted({name for item in current_tasks for name in split_assignees(item.get("assignee", ""))})
    selected_assignees = st.multiselect(
        "表示する担当者",
        ["全員", *assignee_options],
        default=["全員"],
        help="担当者は複数選択できます。",
    )
    filtered_tasks = [item for item in current_tasks if task_matches_assignees(item, selected_assignees)]
    render_task_map(filtered_tasks)

    st.markdown("#### 企画立案")
    render_plan_links(proposing)

    archive_cols = st.columns(2, gap="large")
    with archive_cols[0]:
        st.markdown("#### 完了したタスク")
        if completed_tasks:
            for item in completed_tasks:
                st.markdown(
                    f"""
                    <div class="entry-card">
                      <div class="entry-head">
                        <div class="entry-title">{escape_html(item.get("text", ""))}</div>
                        <div class="entry-meta">完了日: {escape_html(format_dt(item.get("completedAt")))}</div>
                      </div>
                      <div class="entry-body">担当者: {escape_html(item.get("assignee", ""))} / 締切: {escape_html(task_deadline_value(item))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("完了したタスクはありません。")

    with archive_cols[1]:
        st.markdown("#### 決議した企画")
        if decided_plans:
            for item in decided_plans:
                st.markdown(
                    f"""
                    <div class="entry-card">
                      <div class="entry-head">
                        <div class="entry-title">{escape_html(item.get("title", ""))}</div>
                        <div class="entry-meta">決議日: {escape_html(format_dt(item.get("decidedAt")))}</div>
                      </div>
                      <div class="entry-body">{escape_html(item.get("description", ""))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("決議した企画はありません。")


def render_workspace() -> None:
    if not st.session_state["member_authenticated"]:
        st.warning("ログイン後に利用してください。")
        if st.button("ログイン画面へ", key="go_member_login"):
            navigate_to("members")
        return

    st.markdown('<div class="section-title">運営ワークスペース</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="workspace-note">投稿と更新は共通権限で行います。ログイン識別名: <strong>{escape_html(SHARED_AUTHOR_NAME)}</strong></div>',
        unsafe_allow_html=True,
    )

    header_cols = st.columns([1, 2, 4])
    if header_cols[0].button("ダッシュボードへ戻る", key="back_to_dashboard", width="stretch"):
        navigate_to("members")

    current_section = query_param_value("section", "news")
    if current_section not in WORKSPACE_SECTION_LABELS:
        current_section = "news"
    labels = list(WORKSPACE_SECTION_LABELS.values())
    selected_label = header_cols[1].radio(
        "表示セクション",
        labels,
        index=list(WORKSPACE_SECTION_LABELS.keys()).index(current_section),
        horizontal=True,
        label_visibility="collapsed",
    )
    selected_section = next(key for key, value in WORKSPACE_SECTION_LABELS.items() if value == selected_label)

    if selected_section == "news":
        with st.form("message_form", clear_on_submit=True):
            text = st.text_area("本文", height=160)
            uploaded = st.file_uploader("添付ファイル", key="message_upload")
            submitted = st.form_submit_button("投稿する")
        if submitted and text.strip():
            add_post_entry(STORAGE_KEYS["message"], text, uploaded)
            navigate_to("workspace", section="news")

        rows = sorted_entries(load_normalized_list(STORAGE_KEYS["message"], "message"))
        for item in rows:
            render_entry(item, "公開中の100周年News", format_dt(item.get("createdAt")), f"admin_message_{item.get('id')}")
            if st.button("削除", key=f"del_message_{item.get('id')}", width="stretch"):
                save_json(STORAGE_KEYS["message"], [row for row in rows if row.get("id") != item.get("id")])
                navigate_to("workspace", section="news")

    elif selected_section == "minutes":
        with st.form("minutes_form", clear_on_submit=True):
            text = st.text_area("本文", height=160, key="minutes_text")
            uploaded = st.file_uploader("添付ファイル", key="minutes_upload")
            submitted = st.form_submit_button("投稿する")
        if submitted and text.strip():
            add_post_entry(STORAGE_KEYS["minutes"], text, uploaded)
            navigate_to("workspace", section="minutes")

        rows = sorted_entries(load_normalized_list(STORAGE_KEYS["minutes"], "minutes"))
        for item in rows:
            render_entry(item, "公開中のお知らせ", format_dt(item.get("createdAt")), f"admin_minutes_{item.get('id')}")
            if st.button("削除", key=f"del_minutes_{item.get('id')}", width="stretch"):
                save_json(STORAGE_KEYS["minutes"], [row for row in rows if row.get("id") != item.get("id")])
                navigate_to("workspace", section="minutes")

    elif selected_section == "board":
        rows = load_board_rows()
        replies = board_reply_map(rows)
        top_level = [item for item in sorted_entries(rows) if not board_parent_id(item)]
        if not top_level:
            st.info("掲示板の投稿はまだありません。")
        for item in top_level:
            render_board_entry_card(item, "admin_board")
            action_cols = st.columns([1, 1, 4])
            if action_cols[0].button("返信一覧", key=f"open_board_thread_{item.get('id')}", width="stretch"):
                st.session_state["workspace_board_open_id"] = item.get("id", "")
            if action_cols[1].button("削除", key=f"del_board_root_{item.get('id')}", width="stretch"):
                target_id = item.get("id")
                save_json(
                    STORAGE_KEYS["board"],
                    [row for row in rows if row.get("id") != target_id and board_parent_id(row) != target_id],
                )
                navigate_to("workspace", section="board")

            if st.session_state.get("workspace_board_open_id") == item.get("id"):
                thread_replies = replies.get(item.get("id", ""), [])
                if not thread_replies:
                    st.caption("返信はまだありません。")
                for reply in thread_replies:
                    render_board_entry_card(reply, "admin_board_reply", indent=True)
                    reply_cols = st.columns([1, 5])
                    if reply_cols[0].button("削除", key=f"del_board_reply_{reply.get('id')}", width="stretch"):
                        save_json(STORAGE_KEYS["board"], [row for row in rows if row.get("id") != reply.get("id")])
                        navigate_to("workspace", section="board")

    elif selected_section == "voice":
        voices = sorted_entries(load_voice_rows())
        if not voices:
            st.info("100周年プロジェクトへの声はまだありません。")
        for item in voices:
            st.markdown(
                f"""
                <div class="entry-card">
                  <div class="entry-head">
                    <div class="entry-title">{escape_html(item.get("author", "未設定"))}</div>
                    <div class="entry-meta">{escape_html(format_dt(item.get("createdAt")))}</div>
                  </div>
                  <div class="entry-body">{escape_html(item.get("text", ""))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.form(f"voice_manage_{item.get('id')}"):
                cols = st.columns([1, 2])
                current_status = item.get("status", VOICE_STATUS_OPTIONS[0])
                if current_status not in VOICE_STATUS_OPTIONS:
                    current_status = VOICE_STATUS_OPTIONS[0]
                status = cols[0].selectbox(
                    "対応状況",
                    VOICE_STATUS_OPTIONS,
                    index=VOICE_STATUS_OPTIONS.index(current_status),
                    key=f"voice_status_{item.get('id')}",
                )
                memo = cols[1].text_area(
                    "対応メモ",
                    value=item.get("responseMemo", ""),
                    height=120,
                    key=f"voice_memo_{item.get('id')}",
                )
                form_cols = st.columns([1, 1, 4])
                updated = form_cols[0].form_submit_button("更新")
                deleted = form_cols[1].form_submit_button("削除")
            if updated:
                for row in voices:
                    if row.get("id") == item.get("id"):
                        row["status"] = status
                        row["responseMemo"] = memo.strip()
                save_json(STORAGE_KEYS["voice"], voices)
                navigate_to("workspace", section="voice")
            if deleted:
                save_json(STORAGE_KEYS["voice"], [row for row in voices if row.get("id") != item.get("id")])
                navigate_to("workspace", section="voice")

    elif selected_section == "tasks":
        tasks = load_normalized_list(STORAGE_KEYS["tasks"], "task")
        task_id = query_param_value("task_id")
        editing_task = next((item for item in tasks if item.get("id") == task_id), None)

        st.markdown(priority_guide_markdown())
        if editing_task:
            st.info("選択中のタスクを編集できます。")

        form_key = f"task_form_{editing_task.get('id', 'new') if editing_task else 'new'}"
        with st.form(form_key, clear_on_submit=editing_task is None):
            text = st.text_input("タスク名", value=editing_task.get("text", "") if editing_task else "")
            assignee = st.text_input(
                "担当者",
                value=editing_task.get("assignee", "") if editing_task else "",
                help="1人でも複数人でも自由入力できます。",
            )
            priority = st.selectbox(
                "優先度",
                TASK_PRIORITY_OPTIONS,
                index=TASK_PRIORITY_OPTIONS.index(task_priority_value(editing_task or {})),
            )
            deadline = st.date_input(
                "締切",
                value=parse_deadline_for_input(editing_task.get("deadline", "") if editing_task else ""),
            )
            submitted = st.form_submit_button("タスクを更新" if editing_task else "タスクを追加")
        if submitted and text.strip():
            if editing_task:
                for row in tasks:
                    if row.get("id") == editing_task.get("id"):
                        row["text"] = text.strip()
                        row["assignee"] = assignee.strip()
                        row["priority"] = priority
                        row["deadline"] = deadline.isoformat()
            else:
                tasks.append(
                    {
                        "id": make_id("task"),
                        "text": text.strip(),
                        "assignee": assignee.strip(),
                        "priority": priority,
                        "deadline": deadline.isoformat(),
                        "author": SHARED_AUTHOR_NAME,
                        "createdAt": now_iso(),
                        "completed": False,
                        "completedAt": "",
                    }
                )
            save_json(STORAGE_KEYS["tasks"], tasks)
            navigate_to("workspace", section="tasks")

        if editing_task and st.button("新規作成に戻る", key="task_new_mode", width="stretch"):
            navigate_to("workspace", section="tasks")

        current_tasks = sorted([item for item in tasks if not item.get("completed")], key=task_sort_key)
        completed_tasks = sorted([item for item in tasks if item.get("completed")], key=lambda item: item.get("completedAt", ""), reverse=True)
        task_tabs = st.tabs(["進行中", "完了"])

        with task_tabs[0]:
            for item in current_tasks:
                st.markdown(
                    f"""
                    <div class="entry-card">
                      <div class="entry-head">
                        <div class="entry-title">{escape_html(item.get("text", ""))}</div>
                        <div class="entry-meta">担当者: {escape_html(item.get("assignee", ""))} / 優先度: {escape_html(task_priority_value(item))}</div>
                      </div>
                      <div class="entry-body">締切: {escape_html(task_deadline_value(item))} / 登録者: {escape_html(item.get("author", ""))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                cols = st.columns([1, 1, 1, 4])
                if cols[0].button("編集", key=f"edit_task_{item.get('id')}", width="stretch"):
                    navigate_to("workspace", section="tasks", task_id=item.get("id", ""))
                if cols[1].button("完了", key=f"done_task_{item.get('id')}", width="stretch"):
                    for row in tasks:
                        if row.get("id") == item.get("id"):
                            row["completed"] = True
                            row["completedAt"] = now_iso()
                    save_json(STORAGE_KEYS["tasks"], tasks)
                    navigate_to("workspace", section="tasks")
                if cols[2].button("削除", key=f"del_task_{item.get('id')}", width="stretch"):
                    save_json(STORAGE_KEYS["tasks"], [row for row in tasks if row.get("id") != item.get("id")])
                    navigate_to("workspace", section="tasks")

        with task_tabs[1]:
            for item in completed_tasks:
                st.markdown(
                    f"""
                    <div class="entry-card">
                      <div class="entry-head">
                        <div class="entry-title">{escape_html(item.get("text", ""))}</div>
                        <div class="entry-meta">完了日: {escape_html(format_dt(item.get("completedAt")))}</div>
                      </div>
                      <div class="entry-body">担当者: {escape_html(item.get("assignee", ""))} / 優先度: {escape_html(task_priority_value(item))} / 締切: {escape_html(task_deadline_value(item))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                cols = st.columns([1, 1, 1, 4])
                if cols[0].button("編集", key=f"edit_done_task_{item.get('id')}", width="stretch"):
                    navigate_to("workspace", section="tasks", task_id=item.get("id", ""))
                if cols[1].button("未完了へ戻す", key=f"undo_task_{item.get('id')}", width="stretch"):
                    for row in tasks:
                        if row.get("id") == item.get("id"):
                            row["completed"] = False
                            row["completedAt"] = ""
                    save_json(STORAGE_KEYS["tasks"], tasks)
                    navigate_to("workspace", section="tasks")
                if cols[2].button("削除", key=f"del_done_task_{item.get('id')}", width="stretch"):
                    save_json(STORAGE_KEYS["tasks"], [row for row in tasks if row.get("id") != item.get("id")])
                    navigate_to("workspace", section="tasks")

    else:
        proposals = load_normalized_list(STORAGE_KEYS["planning"], "plan")
        plan_id = query_param_value("plan_id")
        editing_plan = next((item for item in proposals if item.get("id") == plan_id), None)

        if editing_plan:
            st.info("選択中の企画を編集できます。")

        form_key = f"planning_form_{editing_plan.get('id', 'new') if editing_plan else 'new'}"
        with st.form(form_key, clear_on_submit=editing_plan is None):
            title = st.text_input("企画タイトル", value=editing_plan.get("title", "") if editing_plan else "")
            description = st.text_area("企画内容", height=140, value=editing_plan.get("description", "") if editing_plan else "")
            submitted = st.form_submit_button("企画を更新" if editing_plan else "企画を追加")
        if submitted and title.strip() and description.strip():
            if editing_plan:
                for row in proposals:
                    if row.get("id") == editing_plan.get("id"):
                        row["title"] = title.strip()
                        row["description"] = description.strip()
            else:
                proposals.append(
                    {
                        "id": make_id("plan"),
                        "title": title.strip(),
                        "description": description.strip(),
                        "proposer": SHARED_AUTHOR_NAME,
                        "createdAt": now_iso(),
                        "status": "proposing",
                        "decidedAt": "",
                    }
                )
            save_json(STORAGE_KEYS["planning"], proposals)
            navigate_to("workspace", section="planning")

        if editing_plan and st.button("新規作成に戻る", key="plan_new_mode", width="stretch"):
            navigate_to("workspace", section="planning")

        proposing = [item for item in sorted_entries(proposals) if item.get("status") != "approved"]
        approved = [item for item in sorted_entries(proposals) if item.get("status") == "approved"]
        proposal_tabs = st.tabs(["提案中", "決議済み"])

        with proposal_tabs[0]:
            for item in proposing:
                st.markdown(
                    f"""
                    <div class="entry-card">
                      <div class="entry-head">
                        <div class="entry-title">{escape_html(item.get("title", ""))}</div>
                        <div class="entry-meta">提案者: {escape_html(item.get("proposer", ""))} / {escape_html(format_dt(item.get("createdAt")))}</div>
                      </div>
                      <div class="entry-body">{escape_html(item.get("description", ""))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                cols = st.columns([1, 1, 1, 4])
                if cols[0].button("編集", key=f"edit_plan_{item.get('id')}", width="stretch"):
                    navigate_to("workspace", section="planning", plan_id=item.get("id", ""))
                if cols[1].button("決議", key=f"approve_plan_{item.get('id')}", width="stretch"):
                    for row in proposals:
                        if row.get("id") == item.get("id"):
                            row["status"] = "approved"
                            row["decidedAt"] = now_iso()
                    save_json(STORAGE_KEYS["planning"], proposals)
                    navigate_to("workspace", section="planning")
                if cols[2].button("削除", key=f"del_plan_{item.get('id')}", width="stretch"):
                    save_json(STORAGE_KEYS["planning"], [row for row in proposals if row.get("id") != item.get("id")])
                    navigate_to("workspace", section="planning")

        with proposal_tabs[1]:
            for item in approved:
                st.markdown(
                    f"""
                    <div class="entry-card">
                      <div class="entry-head">
                        <div class="entry-title">{escape_html(item.get("title", ""))}</div>
                        <div class="entry-meta">決議日: {escape_html(format_dt(item.get("decidedAt")))}</div>
                      </div>
                      <div class="entry-body">{escape_html(item.get("description", ""))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                cols = st.columns([1, 1, 1, 4])
                if cols[0].button("編集", key=f"edit_approved_plan_{item.get('id')}", width="stretch"):
                    navigate_to("workspace", section="planning", plan_id=item.get("id", ""))
                if cols[1].button("提案中へ戻す", key=f"undo_plan_{item.get('id')}", width="stretch"):
                    for row in proposals:
                        if row.get("id") == item.get("id"):
                            row["status"] = "proposing"
                            row["decidedAt"] = ""
                    save_json(STORAGE_KEYS["planning"], proposals)
                    navigate_to("workspace", section="planning")
                if cols[2].button("削除", key=f"del_approved_plan_{item.get('id')}", width="stretch"):
                    save_json(STORAGE_KEYS["planning"], [row for row in proposals if row.get("id") != item.get("id")])
                    navigate_to("workspace", section="planning")


def render_easter_egg_page() -> None:
    logo_path = find_logo_path()
    logo_src = image_to_data_uri(str(logo_path)) if logo_path else ""
    easter_html = f"""
    <style>
      .egg-shell {{
        position: relative;
        min-height: 100vh;
        overflow: hidden;
        border-radius: 28px;
      }}
      .egg-canvas {{
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
      }}
      .egg-content {{
        position: relative;
        z-index: 2;
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 2rem 1rem;
      }}
      .egg-card {{
        width: min(760px, 92vw);
        padding: 2rem 1.4rem 1.6rem;
        border-radius: 28px;
        background: rgba(255, 255, 255, 0.18);
        border: 1px solid rgba(255, 255, 255, 0.22);
        backdrop-filter: blur(14px);
        text-align: center;
        box-shadow: 0 24px 60px rgba(32, 26, 58, 0.22);
      }}
      .egg-logo {{
        width: min(340px, 72vw);
        margin: 0 auto 1.25rem;
        display: block;
        mix-blend-mode: screen;
        filter: drop-shadow(0 18px 32px rgba(255,255,255,0.12));
      }}
      .egg-title {{
        font-family: "Yu Mincho", "Hiragino Mincho ProN", "MS PMincho", serif;
        color: #fff;
        font-size: clamp(1.5rem, 4vw, 2.4rem);
        margin-bottom: 1rem;
        letter-spacing: 0.06em;
      }}
      .egg-copy {{
        color: rgba(255,255,255,0.92);
        font-size: clamp(0.98rem, 2vw, 1.12rem);
        line-height: 1.95;
        white-space: pre-wrap;
      }}
    </style>
    <section class="egg-shell">
      <canvas class="egg-canvas" id="egg-canvas"></canvas>
      <div class="egg-content">
        <div class="egg-card">
          {f'<img class="egg-logo" src="{logo_src}" alt="100周年ロゴ">' if logo_src else ''}
          <div class="egg-title">100周年ありがとう</div>
          <div class="egg-copy">このページを発見したことと「100周年ありがとう」のメッセージを営業部 見谷までお知らせください。もしあなたが一番最初の発見者だった場合、素敵な特典が用意されています。</div>
        </div>
      </div>
    </section>
    <script>
      const canvas = document.getElementById("egg-canvas");
      const ctx = canvas.getContext("2d");
      const fireworks = [];
      const particles = [];

      function resizeCanvas() {{
        canvas.width = canvas.clientWidth * window.devicePixelRatio;
        canvas.height = canvas.clientHeight * window.devicePixelRatio;
        ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
      }}

      function rand(min, max) {{
        return Math.random() * (max - min) + min;
      }}

      function launchFirework() {{
        fireworks.push({{
          x: rand(80, canvas.clientWidth - 80),
          y: canvas.clientHeight + 20,
          targetY: rand(90, canvas.clientHeight * 0.45),
          speed: rand(5, 7.5),
          hue: rand(0, 360),
        }});
      }}

      function burst(firework) {{
        for (let i = 0; i < 36; i += 1) {{
          const angle = (Math.PI * 2 * i) / 36;
          const velocity = rand(1.4, 4.8);
          particles.push({{
            x: firework.x,
            y: firework.targetY,
            vx: Math.cos(angle) * velocity,
            vy: Math.sin(angle) * velocity,
            alpha: 1,
            life: rand(32, 48),
            hue: firework.hue + rand(-18, 18),
          }});
        }}
      }}

      function draw() {{
        ctx.fillStyle = "rgba(22, 18, 44, 0.16)";
        ctx.fillRect(0, 0, canvas.clientWidth, canvas.clientHeight);

        for (let i = fireworks.length - 1; i >= 0; i -= 1) {{
          const firework = fireworks[i];
          firework.y -= firework.speed;
          ctx.beginPath();
          ctx.arc(firework.x, firework.y, 2.4, 0, Math.PI * 2);
          ctx.fillStyle = `hsla(${{firework.hue}}, 100%, 74%, 0.95)`;
          ctx.fill();
          if (firework.y <= firework.targetY) {{
            burst(firework);
            fireworks.splice(i, 1);
          }}
        }}

        for (let i = particles.length - 1; i >= 0; i -= 1) {{
          const particle = particles[i];
          particle.x += particle.vx;
          particle.y += particle.vy;
          particle.vy += 0.04;
          particle.alpha -= 1 / particle.life;
          ctx.beginPath();
          ctx.arc(particle.x, particle.y, 2.2, 0, Math.PI * 2);
          ctx.fillStyle = `hsla(${{particle.hue}}, 100%, 70%, ${{Math.max(particle.alpha, 0)}})`;
          ctx.fill();
          if (particle.alpha <= 0) {{
            particles.splice(i, 1);
          }}
        }}

        requestAnimationFrame(draw);
      }}

      resizeCanvas();
      for (let i = 0; i < 3; i += 1) {{
        setTimeout(launchFirework, i * 500);
      }}
      setInterval(launchFirework, 900);
      window.addEventListener("resize", resizeCanvas);
      draw();
    </script>
    """
    st.html(easter_html, unsafe_allow_javascript=True)


def main() -> None:
    st.set_page_config(
        page_title="100周年特設ページ 公開用",
        page_icon="100",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_style()
    loading = show_loading_overlay()

    init_db()
    ensure_seed_data()
    members = load_members()
    init_session_state()

    messages = load_normalized_list(STORAGE_KEYS["message"], "message")
    minutes = load_normalized_list(STORAGE_KEYS["minutes"], "minutes")
    current_page = get_current_page(st.session_state["member_authenticated"])

    loading.empty()

    if current_page not in {"home", "members", "workspace", "easteregg"}:
        render_navigation_buttons(current_page)

    if current_page == "home":
        render_home(messages, minutes, members)
    elif current_page == "message":
        render_message_page(messages)
    elif current_page == "minutes":
        render_minutes_page(minutes)
    elif current_page == "board":
        render_public_board_page()
    elif current_page == "voice":
        render_project_voice_page()
    elif current_page == "members":
        render_members_page()
    elif current_page == "workspace":
        render_workspace()
    elif current_page == "easteregg":
        render_easter_egg_page()
    else:
        st.warning("ページを開けませんでした。")


if __name__ == "__main__":
    if launched_via_streamlit():
        main()
    else:
        os.execv(
            sys.executable,
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(Path(__file__).resolve()),
            ],
        )
