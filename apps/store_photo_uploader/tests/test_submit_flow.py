"""Google API に接続せず、投稿フロー全体（Drive 保存 → 共有 → シート書き込み）を確認する。"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app import submit  # noqa: E402
from config import AppConfig  # noqa: E402


@dataclass
class FakeUpload:
    name: str
    type: str
    _data: bytes = b"binary"

    @property
    def size(self) -> int:
        return len(self._data)

    def getvalue(self) -> bytes:
        return self._data


class _Request:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeDrive:
    """Drive API の files()/permissions() を最小限だけ模倣する。"""

    def __init__(self, existing_folders: dict[tuple[str, str], str] | None = None):
        self.existing_folders = dict(existing_folders or {})
        self.created_files: list[dict] = []
        self.shared_ids: list[str] = []
        self._counter = 0

    def files(self):
        return self

    def permissions(self):
        return self

    def list(self, q, **_kwargs):
        for (parent, name), folder_id in self.existing_folders.items():
            if f"'{parent}' in parents" in q and f"name = '{name}'" in q:
                return _Request({"files": [{"id": folder_id, "name": name}]})
        return _Request({"files": []})

    def create(self, body=None, media_body=None, fileId=None, **_kwargs):
        if fileId is not None:  # permissions().create()
            self.shared_ids.append(fileId)
            return _Request({"id": "permission-1"})

        self._counter += 1
        new_id = f"id-{self._counter}"
        self.created_files.append({**body, "id": new_id})
        parents = body.get("parents") or []
        if body.get("mimeType", "").endswith("folder") and parents:
            self.existing_folders[(parents[0], body["name"])] = new_id
        return _Request(
            {
                "id": new_id,
                "name": body["name"],
                "webViewLink": f"https://drive.google.com/file/d/{new_id}/view",
            }
        )


class FakeSheets:
    def __init__(self, store_names: list[str]):
        self.store_names = store_names
        self.writes: list[tuple[str, str]] = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **_kwargs):
        return _Request({"values": [[name] for name in self.store_names]})

    def update(self, range, body, **_kwargs):  # noqa: A002 - API のキーワード名に合わせる
        self.writes.append((range, body["values"][0][0]))
        return _Request({})


def make_config(**overrides) -> AppConfig:
    defaults = dict(
        drive_folder_id="root-folder",
        spreadsheet_id="sheet-id",
        sheet_name="シート1",
        store_name_column="A",
        link_column="D",
        first_data_row=2,
        link_target="folder",
        max_files=10,
        max_file_mb=20,
        service_account_info={"client_email": "x@example.com"},
    )
    defaults.update(overrides)
    return AppConfig(**defaults)


def test_uploads_shares_and_writes_folder_link():
    drive = FakeDrive()
    sheets = FakeSheets(["大村本店", "大村南店"])

    result = submit(
        drive,
        sheets,
        make_config(),
        "大村 南店",  # 表記ゆれがあってもシートの「大村南店」に一致する
        [FakeUpload("a.jpg", "image/jpeg"), FakeUpload("b.jpg", "image/jpeg")],
    )

    store_folder_id = drive.existing_folders[("root-folder", "大村 南店")]
    assert result["link"] == f"https://drive.google.com/drive/folders/{store_folder_id}"
    assert drive.shared_ids == [store_folder_id]
    assert len(result["uploaded"]) == 2
    # 3 行目（ヘッダー1行 + 2件目）の D 列に書き込まれる。
    assert sheets.writes == [("'シート1'!D3", result["link"])]
    assert result["rows"] == [3]
    assert result["warnings"] == []


def test_reuses_existing_store_folder():
    drive = FakeDrive(existing_folders={("root-folder", "大村本店"): "existing-folder"})
    sheets = FakeSheets(["大村本店"])

    result = submit(drive, sheets, make_config(), "大村本店", [FakeUpload("a.jpg", "image/jpeg")])

    assert result["link"] == "https://drive.google.com/drive/folders/existing-folder"
    # 再利用したのでフォルダは新規作成されていない。
    assert [f for f in drive.created_files if "folder" in f.get("mimeType", "")] == []


def test_link_target_file_uses_the_single_file_link():
    drive = FakeDrive()
    sheets = FakeSheets(["大村本店"])

    result = submit(
        drive,
        sheets,
        make_config(link_target="file"),
        "大村本店",
        [FakeUpload("a.jpg", "image/jpeg")],
    )

    uploaded = result["uploaded"][0]
    assert result["link"] == uploaded.link
    assert drive.shared_ids == [uploaded.file_id]


def test_link_target_file_falls_back_to_folder_for_multiple_photos():
    drive = FakeDrive()
    sheets = FakeSheets(["大村本店"])

    result = submit(
        drive,
        sheets,
        make_config(link_target="file"),
        "大村本店",
        [FakeUpload("a.jpg", "image/jpeg"), FakeUpload("b.jpg", "image/jpeg")],
    )

    assert result["link"].startswith("https://drive.google.com/drive/folders/")
    assert any("フォルダの共有リンク" in w for w in result["warnings"])


def test_unmatched_store_still_uploads_but_skips_the_sheet():
    drive = FakeDrive()
    sheets = FakeSheets(["大村本店"])

    result = submit(drive, sheets, make_config(), "存在しない店", [FakeUpload("a.jpg", "image/jpeg")])

    assert len(result["uploaded"]) == 1
    assert sheets.writes == []
    assert result["rows"] == []
    assert any("見つからず" in w for w in result["warnings"])


def test_duplicate_store_rows_all_get_the_link():
    drive = FakeDrive()
    sheets = FakeSheets(["大村本店", "他店", "大村本店"])

    result = submit(drive, sheets, make_config(), "大村本店", [FakeUpload("a.jpg", "image/jpeg")])

    assert result["rows"] == [2, 4]
    assert [range_ for range_, _ in sheets.writes] == ["'シート1'!D2", "'シート1'!D4"]
    assert any("複数行に一致" in w for w in result["warnings"])


def test_share_failure_is_reported_but_does_not_abort():
    drive = FakeDrive()
    sheets = FakeSheets(["大村本店"])

    def failing_permissions():
        raise RuntimeError("外部共有が禁止されています")

    drive.permissions = failing_permissions

    result = submit(drive, sheets, make_config(), "大村本店", [FakeUpload("a.jpg", "image/jpeg")])

    assert any("共有設定" in w for w in result["warnings"])
    assert sheets.writes  # 共有に失敗してもシートへの書き込みは行う


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
