"""Tabular export helpers.

Deliberately free of Qt and of app state so it can be unit-tested directly and
reused from the CLI. Callers supply already-built headers and rows.

CSV headers are English regardless of UI language: exported files are read by
spreadsheets and scripts, where a localized column name breaks import mappings.
This mirrors the rule that keeps key codes and format names untranslated.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence


def write_csv(
    path: str | Path,
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
) -> None:
    """Write `headers` + `rows` to `path` as CSV.

    Encoded utf-8-sig (UTF-8 with BOM): without it Excel on Windows reads a
    plain UTF-8 file as the system codepage and mangles any non-ASCII text in
    track titles. Other tools ignore the BOM.

    `None` values are written as empty cells. Quoting, embedded commas and
    newlines are handled by the stdlib writer.
    """
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(["" if value is None else value for value in row])
