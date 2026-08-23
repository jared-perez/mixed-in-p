"""The Metadata panel's audio-properties line, for files that have no bit depth.

A lossy container carries none, so the second half of the summary read as a
bare dash for every MP3 — which looks like a failure to read the file rather
than a fact about the format. The label changes with the measure, so an MP3
says "Bitrate: 320 kbps" where a WAV says "Bit Depth: 16-bit".
"""

import numpy as np
import pytest
import soundfile as sf

from src.gui.widgets.metadata_panel import _depth_or_bitrate, _format_audio_props


class _Info:
    """Stands in for a mutagen stream info. Only what the formatter reads."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class _Mode:
    def __init__(self, name):
        self.name = name


class TestDepthOrBitrate:
    def test_lossless_shows_bit_depth(self):
        info = _Info(sample_rate=44100, bits_per_sample=16, channels=2)
        assert _depth_or_bitrate(info) == ("Bit Depth:", "16-bit")

    def test_aiff_sample_size_is_a_bit_depth_too(self):
        # mutagen names it differently per container; both are a depth.
        assert _depth_or_bitrate(_Info(sample_size=24))[1] == "24-bit"

    def test_lossy_shows_bitrate_under_its_own_label(self):
        info = _Info(sample_rate=44100, channels=2, bitrate=320000)
        assert _depth_or_bitrate(info) == ("Bitrate:", "320 kbps")

    def test_vbr_is_marked_approximate(self):
        # The figure mutagen reports for a VBR stream is the file's average,
        # not a setting anyone chose.
        info = _Info(bitrate=245000, bitrate_mode=_Mode("VBR"))
        assert _depth_or_bitrate(info) == ("Bitrate:", "~245 kbps")

    def test_cbr_is_not_marked(self):
        info = _Info(bitrate=320000, bitrate_mode=_Mode("CBR"))
        assert _depth_or_bitrate(info)[1] == "320 kbps"

    def test_unmeasurable_stream_still_says_bit_depth(self):
        # Nothing to report is not the same as "this format has a bitrate".
        assert _depth_or_bitrate(_Info(sample_rate=44100)) == ("Bit Depth:", "—")

    def test_a_lossless_stream_is_never_described_by_its_bitrate(self):
        # read_bitrate synthesises one from rate x depth x channels; that
        # number belongs in the Player's column, not in this line.
        info = _Info(sample_rate=44100, bits_per_sample=16, channels=2,
                     bitrate=1411000)
        assert _depth_or_bitrate(info)[0] == "Bit Depth:"


class TestFormatAudioProps:
    def test_real_wav_reads_both_halves(self, tmp_path):
        path = tmp_path / "loop.wav"
        sf.write(path, np.zeros(4410, dtype=np.float32), 44100, subtype="PCM_16")
        assert _format_audio_props(str(path)) == (
            "Sample Rate: 44.1 kHz    Bit Depth: 16-bit"
        )

    def test_unreadable_file_says_nothing(self, tmp_path):
        path = tmp_path / "not-audio.mp3"
        path.write_bytes(b"nonsense")
        assert _format_audio_props(str(path)) == ""
