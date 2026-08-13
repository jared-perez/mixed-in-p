"""Energy gets a field of its own, alongside the comment it already had.

There is no standard ID3 frame for energy — the format has nothing to say
about it — so this is the de-facto convention: a user-defined TXXX frame, a
same-named Vorbis key, an iTunes freeform atom for MP4.

The point is not that a comment cannot hold an energy; it is that a comment
cannot be *read back*. "4" in one is ambiguous with a rating or a crate
number, which is why the v5 backfill recovered an energy from almost no real
row. These tests are therefore mostly round-trips: written here, read back
exactly, on every container that can hold one.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.metadata.tags import (
    ENERGY_FIELD,
    _coerce_energy,
    read_energy,
    read_metadata,
    update_comment_with_energy,
    write_energy,
)


@pytest.fixture
def sf():
    return pytest.importorskip("soundfile")


@pytest.fixture
def flac(sf, tmp_path):
    path = tmp_path / "a.flac"
    sf.write(str(path), np.zeros(44100, dtype=np.float32), 44100, format="FLAC")
    return str(path)


@pytest.fixture
def aiff(sf, tmp_path):
    path = tmp_path / "a.aiff"
    sf.write(str(path), np.zeros(44100, dtype=np.float32), 44100, format="AIFF",
             subtype="PCM_16")
    return str(path)


@pytest.fixture
def mp3(sf, tmp_path):
    """A real MP3, encoded the way the app encodes them."""
    from src.conversion.converter import convert_file

    wav = tmp_path / "src.wav"
    sf.write(str(wav), np.zeros(44100, dtype=np.float32), 44100, subtype="PCM_16")
    result = convert_file(str(wav), "MP3", str(tmp_path))
    if not result.output_path:
        pytest.skip(f"MP3 encoding unavailable: {result.error}")
    return result.output_path


@pytest.fixture
def wav(sf, tmp_path):
    path = tmp_path / "a.wav"
    sf.write(str(path), np.zeros(44100, dtype=np.float32), 44100, subtype="PCM_16")
    return str(path)


class TestRoundTrip:
    def test_flac(self, flac):
        assert write_energy(flac, 7) is True
        assert read_energy(flac) == 7

    def test_aiff(self, aiff):
        assert write_energy(aiff, 7) is True
        assert read_energy(aiff) == 7

    def test_mp3(self, mp3):
        assert write_energy(mp3, 7) is True
        assert read_energy(mp3) == 7

    def test_it_arrives_via_read_metadata_too(self, flac):
        """The one call every add site already makes — otherwise the field
        would be written and never looked at."""
        write_energy(flac, 9)

        assert read_metadata(flac).energy == 9

    def test_rewriting_replaces_rather_than_accumulates(self, mp3):
        """A second analysis must not leave two answers in the file."""
        from mutagen.id3 import ID3

        write_energy(mp3, 7)
        write_energy(mp3, 3)

        frames = [f for f in ID3(mp3).getall("TXXX") if f.desc == ENERGY_FIELD]
        assert len(frames) == 1
        assert read_energy(mp3) == 3


class TestItIsIndependentOfTheComment:
    def test_writing_the_field_leaves_the_comment_alone(self, flac):
        update_comment_with_energy(flac, energy=5, key="8A")
        before = read_metadata(flac).comment

        write_energy(flac, 5)

        assert read_metadata(flac).comment == before

    def test_writing_the_comment_leaves_the_field_alone(self, flac):
        write_energy(flac, 5)

        update_comment_with_energy(flac, energy=9, key="8A")

        assert read_energy(flac) == 5, "the comment write clobbered the field"

    def test_the_field_is_never_parsed_out_of_a_comment(self, flac):
        """The ambiguity this exists to escape. A comment that reads like an
        energy is still not one."""
        update_comment_with_energy(flac, energy=6, mode="replace")

        assert read_energy(flac) is None


class TestEdges:
    def test_a_format_with_nowhere_to_put_it_says_so(self, wav):
        """WAV drops the tags this app writes, and a write that reports
        success while discarding the value is the exact failure stores_tags
        exists to prevent."""
        assert write_energy(wav, 7) is False
        assert read_energy(wav) is None

    def test_no_energy_is_a_no_op_not_a_delete(self, flac):
        """Nothing in the app means "erase the energy", and a detection that
        came back empty must not wipe a good value."""
        write_energy(flac, 7)

        assert write_energy(flac, None) is True
        assert read_energy(flac) == 7

    def test_a_file_with_no_energy_reads_as_none(self, flac):
        assert read_energy(flac) is None

    def test_a_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_energy(str(tmp_path / "nope.flac"))

    def test_an_unreadable_value_is_not_invented(self):
        for junk in ("", None, "high", "0", "11", "-1", "7.5"):
            assert _coerce_energy(junk) is None
        assert _coerce_energy("1") == 1
        assert _coerce_energy(" 10 ") == 10

    def test_another_tools_spelling_is_still_read(self, flac):
        """Vorbis keys are case-insensitive by convention and tools disagree
        about it, so the read must not depend on ours."""
        from mutagen.flac import FLAC

        audio = FLAC(flac)
        audio["energylevel"] = "8"
        audio.save()

        assert read_energy(flac) == 8
