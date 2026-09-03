"""Google API クライアントの生成。"""

from __future__ import annotations

from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from config import SCOPES


def build_credentials(service_account_info: dict[str, Any]) -> Credentials:
    return Credentials.from_service_account_info(service_account_info, scopes=SCOPES)


def build_drive(credentials: Credentials):
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def build_sheets(credentials: Credentials):
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)
