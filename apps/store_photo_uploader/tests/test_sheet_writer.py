from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sheet_writer import (  # noqa: E402
    find_matching_rows,
    normalize_store_name,
    quote_sheet_name,
)


def test_normalize_absorbs_width_space_and_case():
    assert normalize_store_name("ＡＢＣ 店") == normalize_store_name("abc店")
    assert normalize_store_name(" 大村　本店 ") == normalize_store_name("大村本店")


def test_normalize_handles_none_and_blank():
    assert normalize_store_name(None) == ""
    assert normalize_store_name("   ") == ""


def test_find_matching_rows_returns_absolute_row_numbers():
    values = ["大村本店", "大村 南店", "大村北店"]
    assert find_matching_rows(values, "大村南店", first_data_row=2) == [3]


def test_find_matching_rows_reports_every_duplicate():
    values = ["大村本店", "", "大村本店"]
    assert find_matching_rows(values, "大村本店", first_data_row=5) == [5, 7]


def test_find_matching_rows_ignores_blank_query():
    assert find_matching_rows(["", "大村本店"], "  ", first_data_row=2) == []


def test_quote_sheet_name_escapes_single_quotes():
    assert quote_sheet_name("店舗'一覧") == "'店舗''一覧'"
