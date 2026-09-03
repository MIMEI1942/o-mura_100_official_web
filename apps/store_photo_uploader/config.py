"""アプリ設定の読み込み。

設定は次の優先順で解決する。

1. 環境変数
2. ``.streamlit/secrets.toml``（Streamlit の secrets）
3. 既定値

Streamlit に依存しないでも import できるようにしてある（テスト用）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


DEFAULTS: dict[str, str] = {
    "SHEET_NAME": "シート1",
    "STORE_NAME_COLUMN": "A",
    "LINK_COLUMN": "B",
    "FIRST_DATA_ROW": "2",
    "LINK_TARGET": "folder",
    "MAX_FILES": "10",
    "MAX_FILE_MB": "20",
}

# サービスアカウントに必要な権限。
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _from_secrets(key: str) -> Any:
    """``st.secrets`` から値を取る。secrets.toml が無い場合は None。"""
    try:
        import streamlit as st

        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return None


def get_setting(key: str, default: Any = None) -> Any:
    value = os.environ.get(key)
    if value not in (None, ""):
        return value
    value = _from_secrets(key)
    if value not in (None, ""):
        return value
    if default is not None:
        return default
    return DEFAULTS.get(key)


def _to_int(value: Any, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def load_service_account_info() -> dict[str, Any] | None:
    """サービスアカウントの資格情報を dict で返す。

    次のいずれかで指定できる。

    - ``GOOGLE_SERVICE_ACCOUNT_JSON``: JSON 文字列そのもの
    - ``GOOGLE_APPLICATION_CREDENTIALS``: JSON ファイルへのパス
    - secrets.toml の ``[gcp_service_account]`` テーブル
    """
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        return json.loads(raw)

    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    table = _from_secrets("gcp_service_account")
    if table:
        return dict(table)

    raw = _from_secrets("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        return json.loads(raw)

    return None


@dataclass(frozen=True)
class AppConfig:
    drive_folder_id: str
    spreadsheet_id: str
    sheet_name: str
    store_name_column: str
    link_column: str
    first_data_row: int
    link_target: str
    max_files: int
    max_file_mb: int
    service_account_info: dict[str, Any] | None = field(default=None, repr=False)

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    def missing_settings(self) -> list[str]:
        missing: list[str] = []
        if not self.drive_folder_id:
            missing.append("DRIVE_FOLDER_ID")
        if not self.spreadsheet_id:
            missing.append("SPREADSHEET_ID")
        if not self.service_account_info:
            missing.append("gcp_service_account / GOOGLE_SERVICE_ACCOUNT_JSON")
        return missing


def load_config() -> AppConfig:
    return AppConfig(
        drive_folder_id=str(get_setting("DRIVE_FOLDER_ID", "") or ""),
        spreadsheet_id=str(get_setting("SPREADSHEET_ID", "") or ""),
        sheet_name=str(get_setting("SHEET_NAME")),
        store_name_column=str(get_setting("STORE_NAME_COLUMN")).strip().upper(),
        link_column=str(get_setting("LINK_COLUMN")).strip().upper(),
        first_data_row=_to_int(get_setting("FIRST_DATA_ROW"), 2),
        link_target=str(get_setting("LINK_TARGET")).strip().lower(),
        max_files=_to_int(get_setting("MAX_FILES"), 10),
        max_file_mb=_to_int(get_setting("MAX_FILE_MB"), 20),
        service_account_info=load_service_account_info(),
    )
