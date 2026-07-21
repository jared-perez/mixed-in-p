"""Tests for History panel sort-key helpers."""

from src.gui.widgets.history_panel import _keycode_sort_key


class TestKeyCodeSortKey:
    """Tests for _keycode_sort_key zero-padding."""

    def test_pads_single_digit(self):
        """Single-digit codes gain a leading zero."""
        assert _keycode_sort_key("8A") == "08A"
        assert _keycode_sort_key("1A") == "01A"
        assert _keycode_sort_key("9B") == "09B"

    def test_leaves_two_digit_unchanged(self):
        """Two-digit codes already sort correctly."""
        assert _keycode_sort_key("10A") == "10A"
        assert _keycode_sort_key("12B") == "12B"

    def test_normalizes_case_and_whitespace(self):
        """Lowercase letters and stray whitespace still parse."""
        assert _keycode_sort_key("1a") == "01A"
        assert _keycode_sort_key(" 7b ") == "07B"

    def test_passes_through_unrecognized(self):
        """Unparseable values are returned as-is rather than raising."""
        assert _keycode_sort_key("") == ""
        assert _keycode_sort_key("garbage") == "garbage"
        assert _keycode_sort_key("13A") == "13A"

    def test_orders_codes_numerically(self):
        """The whole 1A-12B range sorts by number, A/B pairs adjacent."""
        codes = ["10A", "1A", "2B", "12B", "8A", "1B", "11B"]
        assert sorted(codes, key=_keycode_sort_key) == [
            "1A",
            "1B",
            "2B",
            "8A",
            "10A",
            "11B",
            "12B",
        ]

    def test_plain_text_sort_is_wrong_without_the_key(self):
        """Guards the reason this helper exists: "10A" < "1A" as plain text."""
        assert sorted(["10A", "1A"]) == ["10A", "1A"]
        assert sorted(["10A", "1A"], key=_keycode_sort_key) == ["1A", "10A"]
