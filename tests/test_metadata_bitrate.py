"""Bitrate comes off the handle the tag read already holds.

It is one of the optional Player columns schema v5 makes room for, and it has
to arrive without a second open of the file — a library add already reads
tags, and doubling that cost for one number would be felt on every add.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.metadata.tags import read_bitrate, read_metadata

SR = 44100


@pytest.fixture
def sf():
    return pytest.importorskip("soundfile")


def write(sf, path, *, fmt=None, subtype=None, channels=1, rate=SR):
    data = np.zeros((rate, channels) if channels > 1 else rate, dtype=np.float32)
    sf.write(str(path), data, rate, format=fmt, subtype=subtype)
    return str(path)


class TestRealFiles:
    def test_a_16_bit_wav_reports_its_uncompressed_rate(self, sf, tmp_path):
        """44100 x 16 x 1 = 705.6 kbps."""
        path = write(sf, tmp_path / "a.wav", subtype="PCM_16")

        assert read_metadata(path).bitrate == 706

    def test_stereo_doubles_it(self, sf, tmp_path):
        path = write(sf, tmp_path / "s.wav", subtype="PCM_16", channels=2)

        assert read_metadata(path).bitrate == 1411

    def test_flac_reports_its_format_rate_not_its_compressed_size(
        self, sf, tmp_path
    ):
        """The bug a real library caught. This fixture is pure silence, so it
        compresses to almost nothing and mutagen reports a handful of kbps —
        which in a column beside MP3s reads as far worse than a 320, when it
        is lossless. A lossless file is worth its format rate.
        """
        path = write(sf, tmp_path / "a.flac", fmt="FLAC", subtype="PCM_16")

        assert read_metadata(path).bitrate == 706

    def test_aiff_is_read_too(self, sf, tmp_path):
        path = write(sf, tmp_path / "a.aiff", fmt="AIFF", subtype="PCM_16")

        assert read_metadata(path).bitrate is not None


class TestWhichNumberWins:
    """`read_bitrate` in isolation. Bit depth decides: a lossy stream has
    none and is taken at its reported rate; a lossless one is measured from
    its format, whatever it managed to compress to."""

    class Lossy:
        bitrate = 320000

    class Lossless:
        bitrate = 16652  # what mutagen measured for a near-silent FLAC
        sample_rate = 44100
        bits_per_sample = 16
        channels = 2

    class HiRes:
        bitrate = 0
        sample_rate = 96000
        bits_per_sample = 24
        channels = 2

    class Silent:
        bitrate = 0

    def test_a_lossy_stream_is_taken_at_its_word(self):
        assert read_bitrate(self.Lossy()) == 320

    def test_a_lossless_stream_beats_its_own_compressed_figure(self):
        assert read_bitrate(self.Lossless()) == 1411

    def test_hi_res_scales_with_rate_and_depth(self):
        assert read_bitrate(self.HiRes()) == 4608

    def test_a_stream_that_says_nothing_gives_nothing(self):
        """Not a zero — a missing bitrate must read as unknown, or the column
        would claim every such file was silent."""
        assert read_bitrate(self.Silent()) is None
