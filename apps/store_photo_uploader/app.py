"""店舗写真アップロードフォーム。

投稿された写真を Google Drive の店舗別フォルダに保存し、共有リンクを発行して
スプレッドシートの該当行に書き込む。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import drive_uploader  # noqa: E402
import sheet_writer  # noqa: E402
from config import AppConfig, load_config  # noqa: E402
from google_services import build_credentials, build_drive, build_sheets  # noqa: E402


JST = ZoneInfo("Asia/Tokyo")
ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "heic", "heif"]

st.set_page_config(page_title="店舗写真アップロード", page_icon="📷")


@st.cache_resource(show_spinner=False)
def get_services(_service_account_info: dict):
    credentials = build_credentials(_service_account_info)
    return build_drive(credentials), build_sheets(credentials)


def sheet_target(config: AppConfig) -> sheet_writer.SheetTarget:
    return sheet_writer.SheetTarget(
        spreadsheet_id=config.spreadsheet_id,
        sheet_name=config.sheet_name,
        store_name_column=config.store_name_column,
        link_column=config.link_column,
        first_data_row=config.first_data_row,
    )


@st.cache_data(ttl=300, show_spinner=False)
def load_store_names(_sheets, target: sheet_writer.SheetTarget) -> list[str]:
    """シートに登録済みの店舗名を重複なしで返す。"""
    names = sheet_writer.read_store_names(_sheets, target)
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        cleaned = (name or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        unique.append(cleaned)
    return unique


def render_setup_help(missing: list[str]) -> None:
    st.error("設定が不足しているため起動できません: " + ", ".join(missing))
    st.markdown(
        "`.streamlit/secrets.toml`（または環境変数）に設定してください。"
        "書き方は `apps/store_photo_uploader/README.md` と "
        "`.streamlit/secrets.toml.example` を参照してください。"
    )


def validate_files(files, config: AppConfig) -> list[str]:
    errors: list[str] = []
    if len(files) > config.max_files:
        errors.append(f"写真は一度に{config.max_files}枚までです（{len(files)}枚選択されています）。")
    for file in files:
        if file.size > config.max_file_bytes:
            errors.append(
                f"「{file.name}」が上限{config.max_file_mb}MBを超えています"
                f"（{file.size / 1024 / 1024:.1f}MB）。"
            )
    return errors


def submit(drive, sheets, config: AppConfig, store_name: str, files) -> dict:
    """アップロード〜シート書き込みまでを実行して結果を返す。"""
    result: dict = {"warnings": [], "uploaded": [], "rows": []}

    store_folder_id = drive_uploader.ensure_folder(drive, config.drive_folder_id, store_name)

    stamp = datetime.now(JST).strftime("%Y%m%d-%H%M%S")
    for index, file in enumerate(files, start=1):
        uploaded = drive_uploader.upload_file(
            drive,
            store_folder_id,
            name=f"{stamp}_{index:02d}_{file.name}",
            data=file.getvalue(),
            mime_type=file.type or "application/octet-stream",
        )
        result["uploaded"].append(uploaded)

    # 共有リンクの対象（フォルダ単位が既定。単票運用なら LINK_TARGET=file）。
    if config.link_target == "file" and len(result["uploaded"]) == 1:
        share_id = result["uploaded"][0].file_id
        link = result["uploaded"][0].link
    else:
        share_id = store_folder_id
        link = drive_uploader.folder_link(store_folder_id)
        if config.link_target == "file" and len(result["uploaded"]) > 1:
            result["warnings"].append(
                "写真が複数枚のため、ファイル単体ではなくフォルダの共有リンクを書き込みます。"
            )
    result["link"] = link

    try:
        drive_uploader.share_with_anyone(drive, share_id)
    except Exception as error:  # noqa: BLE001 - 共有ポリシーで失敗しても保存自体は成功
        result["warnings"].append(
            f"共有設定（リンクを知っている全員が閲覧可）の付与に失敗しました: {error}"
        )

    target = sheet_target(config)
    column_values = sheet_writer.read_store_names(sheets, target)
    rows = sheet_writer.find_matching_rows(column_values, store_name, target.first_data_row)
    if not rows:
        result["warnings"].append(
            f"スプレッドシートに「{store_name}」と一致する行が見つからず、"
            f"{target.link_column}列への書き込みはスキップしました。"
        )
    else:
        if len(rows) > 1:
            result["warnings"].append(
                "店舗名が複数行に一致したため、すべての行に書き込みました: "
                + ", ".join(str(row) for row in rows)
            )
        for row in rows:
            sheet_writer.write_link(sheets, target, row, link)
    result["rows"] = rows
    return result


def main() -> None:
    st.title("📷 店舗写真アップロード")

    config = load_config()
    missing = config.missing_settings()
    if missing:
        render_setup_help(missing)
        return

    drive, sheets = get_services(config.service_account_info)
    target = sheet_target(config)

    try:
        known_stores = load_store_names(sheets, target)
    except Exception as error:  # noqa: BLE001 - シートが読めなくても手入力で投稿できる
        known_stores = []
        st.warning(f"スプレッドシートの店舗名一覧を読み込めませんでした: {error}")

    st.caption(
        f"保存先: Google Drive の指定フォルダ / 書き込み先: "
        f"{config.sheet_name} シートの {config.link_column} 列"
    )

    manual_label = "リストにない（手入力する）"
    with st.form("upload_form", clear_on_submit=False):
        if known_stores:
            choice = st.selectbox("店舗名", [*known_stores, manual_label], index=0)
            manual_name = ""
            if choice == manual_label:
                manual_name = st.text_input("店舗名を入力")
            store_name = manual_name if choice == manual_label else choice
        else:
            store_name = st.text_input("店舗名")

        files = st.file_uploader(
            "写真",
            type=ALLOWED_EXTENSIONS,
            accept_multiple_files=True,
            help=f"{config.max_files}枚 / 1枚あたり{config.max_file_mb}MB まで",
        )
        st.caption(
            f"写真は一度に{config.max_files}枚まで / 1枚あたり{config.max_file_mb}MB まで"
        )
        submitted = st.form_submit_button("投稿する", type="primary")

    if files:
        previewable = [file for file in files if (file.type or "").startswith("image/")]
        if previewable:
            st.image(previewable, width=160, caption=[file.name for file in previewable])

    if not submitted:
        return

    store_name = (store_name or "").strip()
    errors: list[str] = []
    if not store_name:
        errors.append("店舗名を入力してください。")
    if not files:
        errors.append("写真を1枚以上選択してください。")
    errors.extend(validate_files(files or [], config))
    if errors:
        for message in errors:
            st.error(message)
        return

    with st.spinner("アップロードしています…"):
        try:
            result = submit(drive, sheets, config, store_name, files)
        except Exception as error:  # noqa: BLE001 - 失敗理由を画面に出す
            st.error(f"処理に失敗しました: {error}")
            return

    # 店舗が増えた可能性があるので、次回の一覧を取り直す。
    load_store_names.clear()

    st.success(f"{len(result['uploaded'])}枚を「{store_name}」に保存しました。")
    st.write("共有リンク:", result["link"])
    if result["rows"]:
        st.write(
            "書き込んだセル: "
            + ", ".join(f"{config.link_column}{row}" for row in result["rows"])
        )
    for warning in result["warnings"]:
        st.warning(warning)
    with st.expander("保存したファイル"):
        for uploaded in result["uploaded"]:
            st.write(f"- [{uploaded.name}]({uploaded.link})")


if __name__ == "__main__":
    main()
