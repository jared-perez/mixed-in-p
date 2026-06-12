"""Tests for the key code mapping module."""

import pytest

from src.analysis.keycode import (
    KEY_TO_KEYCODE,
    KEYCODE_TO_KEY,
    key_to_keycode,
    keycode_to_key,
    keycode_to_open_key,
    get_compatible_keys,
    normalize_key,
    render_key,
)


class TestKeyToKeyCode:
    """Tests for key_to_keycode conversion."""

    def test_minor_keys(self):
        """Test conversion of minor keys to A codes."""
        assert key_to_keycode("Am") == "8A"
        assert key_to_keycode("Dm") == "7A"
        assert key_to_keycode("Em") == "9A"
        assert key_to_keycode("Gm") == "6A"
        assert key_to_keycode("Cm") == "5A"
        assert key_to_keycode("Fm") == "4A"
        assert key_to_keycode("Bm") == "10A"

    def test_major_keys(self):
        """Test conversion of major keys to B codes."""
        assert key_to_keycode("C") == "8B"
        assert key_to_keycode("G") == "9B"
        assert key_to_keycode("D") == "10B"
        assert key_to_keycode("A") == "11B"
        assert key_to_keycode("E") == "12B"
        assert key_to_keycode("B") == "1B"
        assert key_to_keycode("F") == "7B"

    def test_sharp_keys(self):
        """Test keys with sharps."""
        assert key_to_keycode("F#m") == "11A"
        assert key_to_keycode("C#m") == "12A"
        assert key_to_keycode("G#m") == "1A"
        assert key_to_keycode("D#m") == "2A"
        assert key_to_keycode("A#m") == "3A"
        assert key_to_keycode("F#") == "2B"
        assert key_to_keycode("C#") == "3B"
        assert key_to_keycode("G#") == "4B"
        assert key_to_keycode("D#") == "5B"
        assert key_to_keycode("A#") == "6B"

    def test_flat_keys(self):
        """Test keys with flats (enharmonic equivalents)."""
        assert key_to_keycode("Abm") == "1A"
        assert key_to_keycode("Ebm") == "2A"
        assert key_to_keycode("Bbm") == "3A"
        assert key_to_keycode("Gbm") == "11A"
        assert key_to_keycode("Dbm") == "12A"
        assert key_to_keycode("Gb") == "2B"
        assert key_to_keycode("Db") == "3B"
        assert key_to_keycode("Ab") == "4B"
        assert key_to_keycode("Eb") == "5B"
        assert key_to_keycode("Bb") == "6B"

    def test_invalid_key_raises(self):
        """Test that invalid keys raise ValueError."""
        with pytest.raises(ValueError, match="Unknown key"):
            key_to_keycode("Xm")
        with pytest.raises(ValueError, match="Unknown key"):
            key_to_keycode("H")
        with pytest.raises(ValueError, match="Unknown key"):
            key_to_keycode("")


class TestKeyCodeToKey:
    """Tests for keycode_to_key conversion."""

    def test_a_codes_to_minor(self):
        """Test A codes convert to minor keys."""
        assert keycode_to_key("8A") == "Am"
        assert keycode_to_key("7A") == "Dm"
        assert keycode_to_key("9A") == "Em"
        assert keycode_to_key("1A") == "Abm"
        assert keycode_to_key("11A") == "F#m"
        assert keycode_to_key("12A") == "C#m"

    def test_b_codes_to_major(self):
        """Test B codes convert to major keys."""
        assert keycode_to_key("8B") == "C"
        assert keycode_to_key("9B") == "G"
        assert keycode_to_key("10B") == "D"
        assert keycode_to_key("1B") == "B"
        assert keycode_to_key("2B") == "Gb"
        assert keycode_to_key("3B") == "Db"

    def test_case_insensitive(self):
        """Test that key codes are case-insensitive."""
        assert keycode_to_key("8a") == "Am"
        assert keycode_to_key("8b") == "C"
        assert keycode_to_key("11A") == "F#m"
        assert keycode_to_key("11b") == "A"

    def test_handles_whitespace(self):
        """Test that whitespace is stripped."""
        assert keycode_to_key(" 8A ") == "Am"
        assert keycode_to_key("8B ") == "C"

    def test_invalid_code_raises(self):
        """Test that invalid codes raise ValueError."""
        with pytest.raises(ValueError, match="Invalid key code"):
            keycode_to_key("13A")
        with pytest.raises(ValueError, match="Invalid key code"):
            keycode_to_key("0B")
        with pytest.raises(ValueError, match="Invalid key code"):
            keycode_to_key("8C")
        with pytest.raises(ValueError, match="Invalid key code"):
            keycode_to_key("")


class TestGetCompatibleKeys:
    """Tests for harmonic compatibility suggestions."""

    def test_compatible_includes_self(self):
        """Test that the input key is included in results."""
        result = get_compatible_keys("8A")
        assert "8A" in result

    def test_compatible_includes_relative(self):
        """Test that relative major/minor is included."""
        result = get_compatible_keys("8A")  # Am
        assert "8B" in result  # C major (relative major)

        result = get_compatible_keys("8B")  # C major
        assert "8A" in result  # Am (relative minor)

    def test_compatible_includes_adjacent(self):
        """Test that adjacent key codes are included."""
        result = get_compatible_keys("8A")
        assert "7A" in result  # Dm
        assert "9A" in result  # Em

    def test_wrapping_at_12_to_1(self):
        """Test code-number wrapping from 12 to 1."""
        result = get_compatible_keys("12A")
        assert "11A" in result
        assert "1A" in result  # Wraps from 12 to 1

    def test_wrapping_at_1_to_12(self):
        """Test code-number wrapping from 1 to 12."""
        result = get_compatible_keys("1A")
        assert "12A" in result  # Wraps from 1 to 12
        assert "2A" in result

    def test_returns_four_compatible(self):
        """Test that exactly 4 compatible keys are returned."""
        result = get_compatible_keys("5B")
        assert len(result) == 4

    def test_invalid_code_raises(self):
        """Test that invalid codes raise ValueError."""
        with pytest.raises(ValueError, match="Invalid key code"):
            get_compatible_keys("15A")


class TestNormalizeKey:
    """Tests for key string normalization."""

    def test_already_normalized(self):
        """Test keys already in correct format."""
        assert normalize_key("Am") == "Am"
        assert normalize_key("F#m") == "F#m"
        assert normalize_key("C") == "C"
        assert normalize_key("Bb") == "Bb"

    def test_minor_variations(self):
        """Test various minor key formats."""
        assert normalize_key("A minor") == "Am"
        assert normalize_key("A Minor") == "Am"
        assert normalize_key("A min") == "Am"
        assert normalize_key("a minor") == "Am"
        assert normalize_key("F# minor") == "F#m"

    def test_major_variations(self):
        """Test various major key formats."""
        assert normalize_key("C major") == "C"
        assert normalize_key("C Major") == "C"
        assert normalize_key("C maj") == "C"
        assert normalize_key("c major") == "C"
        assert normalize_key("F# major") == "F#"

    def test_lowercase_simple(self):
        """Test simple lowercase keys."""
        assert normalize_key("c") == "C"
        assert normalize_key("am") == "Am"
        assert normalize_key("g") == "G"

    def test_whitespace_handling(self):
        """Test that whitespace is stripped."""
        assert normalize_key(" Am ") == "Am"
        assert normalize_key("  C  ") == "C"


class TestMappingConsistency:
    """Tests to verify mapping consistency."""

    def test_all_keycodes_have_keys(self):
        """Test all 24 key codes are mapped."""
        for num in range(1, 13):
            assert f"{num}A" in KEYCODE_TO_KEY
            assert f"{num}B" in KEYCODE_TO_KEY

    def test_roundtrip_keycode_to_key_to_keycode(self):
        """Test converting Key Code -> Key -> Key Code returns same code."""
        for keycode in KEYCODE_TO_KEY:
            key = keycode_to_key(keycode)
            result = key_to_keycode(key)
            assert result == keycode, f"Roundtrip failed for {keycode}: got {result}"

    def test_enharmonic_equivalents_map_same(self):
        """Test that enharmonic keys map to the same key code."""
        assert key_to_keycode("G#m") == key_to_keycode("Abm")
        assert key_to_keycode("D#m") == key_to_keycode("Ebm")
        assert key_to_keycode("F#") == key_to_keycode("Gb")
        assert key_to_keycode("C#") == key_to_keycode("Db")


class TestOpenKey:
    """Tests for Traktor Open Key conversion."""

    def test_known_anchors(self):
        """Key code 8 anchors to Open Key 1 (8B=C=1d, 8A=Am=1m)."""
        assert keycode_to_open_key("8B") == "1d"
        assert keycode_to_open_key("8A") == "1m"
        assert keycode_to_open_key("5A") == "10m"
        assert keycode_to_open_key("2B") == "7d"
        assert keycode_to_open_key("7B") == "12d"
        assert keycode_to_open_key("1A") == "6m"

    def test_minor_uses_m_major_uses_d(self):
        for num in range(1, 13):
            assert keycode_to_open_key(f"{num}A").endswith("m")
            assert keycode_to_open_key(f"{num}B").endswith("d")

    def test_open_key_numbers_in_range(self):
        for keycode in KEYCODE_TO_KEY:
            open_code = keycode_to_open_key(keycode)
            num = int(open_code[:-1])
            assert 1 <= num <= 12

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            keycode_to_open_key("99Z")


class TestRenderKey:
    """Tests for the render_key display helper."""

    def test_traditional(self):
        assert render_key("Am", "8A", "traditional") == "Am"

    def test_open_key(self):
        assert render_key("Am", "8A", "open_key") == "1m"

    def test_keycode(self):
        assert render_key("Am", "8A", "keycode") == "8A"

    def test_unknown_notation_defaults_to_keycode(self):
        assert render_key("Am", "8A", "bogus") == "8A"

    def test_fallbacks_on_empty(self):
        assert render_key("", "8A", "traditional") == "8A"
        assert render_key("Am", "", "open_key") == "Am"
        assert render_key("Am", "", "keycode") == "Am"
