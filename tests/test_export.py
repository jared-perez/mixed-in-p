"""Tests for the CSV export helper."""

import csv

from src.utils.export import write_csv


class TestWriteCsv:
    def test_writes_headers_and_rows(self, tmp_path):
        out = tmp_path / "out.csv"
        write_csv(out, ["A", "B"], [[1, 2], [3, 4]])
        with open(out, newline="", encoding="utf-8-sig") as f:
            assert list(csv.reader(f)) == [["A", "B"], ["1", "2"], ["3", "4"]]

    def test_none_becomes_empty_cell(self, tmp_path):
        """Missing analysis values (no BPM, no energy) export as blanks."""
        out = tmp_path / "out.csv"
        write_csv(out, ["A", "B"], [[None, 1]])
        with open(out, newline="", encoding="utf-8-sig") as f:
            assert list(csv.reader(f))[1] == ["", "1"]

    def test_quotes_commas_and_newlines_in_values(self, tmp_path):
        """Track titles routinely contain commas and quotes."""
        out = tmp_path / "out.csv"
        tricky = 'Artist, The - "Remix" (feat. X)'
        write_csv(out, ["Name"], [[tricky], ["line\nbreak"]])
        with open(out, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        assert rows[1] == [tricky]
        assert rows[2] == ["line\nbreak"]

    def test_written_as_utf8_with_bom(self, tmp_path):
        """The BOM is what stops Excel on Windows mangling non-ASCII titles."""
        out = tmp_path / "out.csv"
        write_csv(out, ["Name"], [["Björk – Jóga"]])
        raw = out.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")
        with open(out, newline="", encoding="utf-8-sig") as f:
            assert list(csv.reader(f))[1] == ["Björk – Jóga"]

    def test_accepts_str_path(self, tmp_path):
        out = tmp_path / "out.csv"
        write_csv(str(out), ["A"], [["x"]])
        assert out.exists()

    def test_empty_rows_still_writes_header(self, tmp_path):
        out = tmp_path / "out.csv"
        write_csv(out, ["A", "B"], [])
        with open(out, newline="", encoding="utf-8-sig") as f:
            assert list(csv.reader(f)) == [["A", "B"]]
