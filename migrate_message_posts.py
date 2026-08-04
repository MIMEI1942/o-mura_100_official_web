from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

try:
    import psycopg
except ImportError:
    print("psycopg がありません。先に `pip install psycopg[binary]` を実行してください。")
    sys.exit(1)


JST = ZoneInfo("Asia/Tokyo")
SOURCE_KEY = "centennial_message_posts"
MIGRATION_MARKER = "centennial_message_posts_table_migrated_v1"
BATCH_SIZE = 10


def database_url() -> str:
    url = (
        os.getenv("CENTENNIAL_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or getpass.getpass("Supabaseの接続URLを貼り付けてEnterしてください（画面には表示されません）: ")
    )
    if not url:
        raise RuntimeError("接続URLが入力されていません。")
    return url


def parse_created_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip())
        except ValueError:
            dt = datetime.now(JST)
    else:
        dt = datetime.now(JST)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt


def derive_file_type(item: dict[str, Any], file_data: str | None) -> str | None:
    explicit = item.get("fileType")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    if isinstance(file_data, str) and file_data.startswith("data:") and ";" in file_data:
        return file_data[5:].split(";", 1)[0] or None
    return None


def post_id(item: dict[str, Any]) -> str:
    current = item.get("id")
    if isinstance(current, str) and current.strip():
        return current.strip()

    stable_json = json.dumps(item, ensure_ascii=False, sort_keys=True)
    return "post_" + hashlib.md5(stable_json.encode("utf-8")).hexdigest()


def normalize_post(item: dict[str, Any]) -> tuple[str, str, datetime, str | None, str | None, str | None]:
    file_data = item.get("fileDataUrl") or item.get("fileData")
    if not isinstance(file_data, str) or not file_data:
        file_data = None

    file_name = item.get("fileName")
    if not isinstance(file_name, str) or not file_name:
        file_name = None

    body = item.get("text")
    if body is None:
        body = item.get("body", "")
    body = str(body)

    return (
        post_id(item),
        body,
        parse_created_at(item.get("createdAt") or item.get("created_at")),
        file_name,
        derive_file_type(item, file_data),
        file_data,
    )


def main() -> None:
    url = database_url()

    print("1/5 旧投稿JSONを取得しています。79MBあるため時間がかかる場合があります。")
    with psycopg.connect(url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT value
                FROM public.kv_storage
                WHERE key = %s
                """,
                (SOURCE_KEY,),
            )
            row = cur.fetchone()

    if not row:
        raise RuntimeError("public.kv_storage に既存投稿データが見つかりません。")

    print("2/5 JSONをCodespaces側で解析しています。")
    raw = row[0]
    posts = json.loads(raw)
    if not isinstance(posts, list):
        raise RuntimeError("既存投稿データがJSON配列ではありません。")

    normalized_by_id: dict[str, tuple[str, str, datetime, str | None, str | None, str | None]] = {}
    for item in posts:
        if isinstance(item, dict):
            normalized = normalize_post(item)
            normalized_by_id[normalized[0]] = normalized

    records = list(normalized_by_id.values())
    print(f"移行対象: 元JSON {len(posts)}件 / 一意ID {len(records)}件")

    print("3/5 新テーブルを確認しています。")
    with psycopg.connect(url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS public.centennial_message_posts (
                    id TEXT PRIMARY KEY,
                    body TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    file_name TEXT,
                    file_type TEXT,
                    file_data TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_centennial_message_posts_created_at
                ON public.centennial_message_posts (created_at DESC)
                """
            )
        conn.commit()

    print("4/5 投稿を少量ずつ移行しています。途中で止まっても再実行できます。")
    insert_sql = """
        INSERT INTO public.centennial_message_posts (
            id, body, created_at, file_name, file_type, file_data
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
    """

    total = len(records)
    for start in range(0, total, BATCH_SIZE):
        batch = records[start:start + BATCH_SIZE]
        with psycopg.connect(url, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.executemany(insert_sql, batch)
            conn.commit()
        done = min(start + len(batch), total)
        print(f"  {done}/{total}件")

    print("5/5 件数を確認しています。")
    with psycopg.connect(url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM public.centennial_message_posts")
            destination_count = int(cur.fetchone()[0])

            if destination_count < len(records):
                raise RuntimeError(
                    f"移行先件数が不足しています。移行対象={len(records)}件、移行先={destination_count}件"
                )

            cur.execute(
                """
                INSERT INTO public.kv_storage(key, value, updated_at)
                VALUES (%s, 'done', NOW())
                ON CONFLICT(key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = EXCLUDED.updated_at
                """,
                (MIGRATION_MARKER,),
            )
        conn.commit()

    print("")
    print("移行が完了しました。")
    print(f"旧JSON件数: {len(posts)}件")
    print(f"新テーブル件数: {destination_count}件")
    print("public.kv_storage の旧データは削除・変更していません。")


if __name__ == "__main__":
    main()