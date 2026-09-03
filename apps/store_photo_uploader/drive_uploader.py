"""Google Drive へのアップロードと共有リンク発行。

共有ドライブ（Shared drive）にも対応するため、全リクエストに
``supportsAllDrives`` / ``includeItemsFromAllDrives`` を付けている。
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from googleapiclient.http import MediaIoBaseUpload


FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


@dataclass(frozen=True)
class UploadedFile:
    file_id: str
    name: str
    link: str


def _escape_query_value(value: str) -> str:
    """Drive の検索クエリ用にシングルクォートとバックスラッシュを退避する。"""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_folder(drive, parent_id: str, name: str) -> str | None:
    query = (
        f"'{_escape_query_value(parent_id)}' in parents"
        f" and name = '{_escape_query_value(name)}'"
        f" and mimeType = '{FOLDER_MIME_TYPE}'"
        " and trashed = false"
    )
    response = (
        drive.files()
        .list(
            q=query,
            fields="files(id, name)",
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = response.get("files", [])
    return files[0]["id"] if files else None


def ensure_folder(drive, parent_id: str, name: str) -> str:
    """``parent_id`` 直下に ``name`` フォルダを用意して ID を返す（既存なら再利用）。"""
    existing = find_folder(drive, parent_id, name)
    if existing:
        return existing

    created = (
        drive.files()
        .create(
            body={"name": name, "mimeType": FOLDER_MIME_TYPE, "parents": [parent_id]},
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )
    return created["id"]


def upload_file(drive, folder_id: str, name: str, data: bytes, mime_type: str) -> UploadedFile:
    media = MediaIoBaseUpload(
        io.BytesIO(data),
        mimetype=mime_type or "application/octet-stream",
        resumable=True,
    )
    created = (
        drive.files()
        .create(
            body={"name": name, "parents": [folder_id]},
            media_body=media,
            fields="id, name, webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )
    return UploadedFile(
        file_id=created["id"],
        name=created.get("name", name),
        link=created.get("webViewLink") or file_link(created["id"]),
    )


def share_with_anyone(drive, file_id: str) -> None:
    """「リンクを知っている全員が閲覧可」を付与する。

    既に同等の権限がある場合や、組織のポリシーで外部共有が禁止されている場合は
    Drive 側がエラーを返すため、呼び出し側で握りつぶすかどうかを判断する。
    """
    drive.permissions().create(
        fileId=file_id,
        body={"role": "reader", "type": "anyone"},
        supportsAllDrives=True,
    ).execute()


def file_link(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"


def folder_link(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"
