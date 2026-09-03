"""スプレッドシートの店舗名照合とリンク書き込み。

照合ロジック（``normalize_store_name`` / ``find_matching_rows``）は
Google API に依存しない純粋関数なので、単体テストできる。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class SheetTarget:
    """書き込み先セルの座標。"""

    spreadsheet_id: str
    sheet_name: str
    store_name_column: str
    link_column: str
    first_data_row: int


def normalize_store_name(name: str | None) -> str:
    """表記ゆれを吸収した比較用のキーを返す。

    全角/半角（NFKC）、前後と途中の空白、大文字小文字の差を無視する。
    """
    text = unicodedata.normalize("NFKC", name or "")
    text = re.sub(r"\s+", "", text)
    return text.casefold()


def find_matching_rows(
    column_values: Sequence[str | None],
    store_name: str,
    first_data_row: int,
) -> list[int]:
    """店舗名が一致する行番号（1 始まり）をすべて返す。

    ``column_values`` は ``first_data_row`` 行目から並んだ店舗名列の値。
    """
    target = normalize_store_name(store_name)
    if not target:
        return []
    return [
        first_data_row + offset
        for offset, value in enumerate(column_values)
        if normalize_store_name(value) == target
    ]


def quote_sheet_name(sheet_name: str) -> str:
    """A1 記法用にシート名をクォートする（シングルクォートは重ねてエスケープ）。"""
    return "'" + sheet_name.replace("'", "''") + "'"


def read_store_names(sheets, target: SheetTarget) -> list[str]:
    """店舗名列の値を ``first_data_row`` 行目から順に返す。"""
    a1 = (
        f"{quote_sheet_name(target.sheet_name)}!"
        f"{target.store_name_column}{target.first_data_row}:{target.store_name_column}"
    )
    response = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=target.spreadsheet_id, range=a1)
        .execute()
    )
    rows = response.get("values", [])
    return [row[0] if row else "" for row in rows]


def write_link(sheets, target: SheetTarget, row: int, link: str) -> None:
    a1 = f"{quote_sheet_name(target.sheet_name)}!{target.link_column}{row}"
    sheets.spreadsheets().values().update(
        spreadsheetId=target.spreadsheet_id,
        range=a1,
        valueInputOption="USER_ENTERED",
        body={"values": [[link]]},
    ).execute()
